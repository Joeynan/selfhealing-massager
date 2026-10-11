"""Capture a SenseCAP Watcher JPEG over USB using its existing SSCMA firmware.

macOS, Python 3 standard library only. Does not erase or flash either processor.
"""

import argparse
import array
import base64
from datetime import datetime
import fcntl
import glob
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import termios
import time
from zoneinfo import ZoneInfo


class ResponseStream:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, chunk):
        self.buffer.extend(chunk)
        if len(self.buffer) > 2 * 1024 * 1024:
            raise ValueError("摄像头数据过大或数据包不完整，请重新连接后再试。")
        replies = []
        while b"\n" in self.buffer:
            line, _, remaining = self.buffer.partition(b"\n")
            self.buffer[:] = remaining
            start = line.find(b"{")
            if start < 0:
                continue
            try:
                reply = json.loads(line[start:])
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(reply, dict):
                replies.append(reply)
        return replies


def decode_image(reply):
    if reply.get("code") != 0:
        raise ValueError("摄像头报告拍照失败。")
    value = reply.get("data", {}).get("image")
    if not isinstance(value, str):
        raise ValueError("摄像头没有返回图片。")
    try:
        # This Watcher firmware pads some JPEG buffers with zero bytes.
        jpeg = base64.b64decode(value, validate=True).rstrip(b"\x00")
    except (ValueError, TypeError) as exc:
        raise ValueError("图片传输损坏，请重试。") from exc
    if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
        raise ValueError("返回的 JPEG 不完整，请重试。")
    return jpeg


def option_for_resolution(sensor, resolution):
    for option, description in sensor.get("opts", {}).items():
        if description.split()[0] == resolution:
            return int(option)
    raise ValueError("摄像头不支持所选分辨率：" + resolution)


class SerialPort:
    def __init__(self, path):
        self.path = path
        self.fd = None
        self.previous = None
        self.stream = ResponseStream()

    def __enter__(self):
        busy = subprocess.run(["/usr/sbin/lsof", "-t", self.path],
                              capture_output=True, text=True)
        if busy.stdout.strip():
            raise RuntimeError("串口正被使用，请关闭网页串口连接或其他串口工具。")
        self.fd = os.open(self.path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            self.previous = termios.tcgetattr(self.fd)
            attrs = termios.tcgetattr(self.fd)
            attrs[0] = attrs[1] = attrs[3] = 0
            attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            attrs[4] = attrs[5] = termios.B115200
            attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
            termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
            # Darwin IOKit IOSSIOSPEED; no DTR/RTS reset sequence is sent.
            fcntl.ioctl(self.fd, 0x80045402, array.array("i", [921600]), 1)
            end = time.monotonic() + 1.2
            while time.monotonic() < end:
                self.read_chunk(0.1)
            self.stream = ResponseStream()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        if self.fd is not None:
            try:
                if self.previous is not None:
                    termios.tcsetattr(self.fd, termios.TCSANOW, self.previous)
            except OSError:
                pass
            finally:
                os.close(self.fd)
                self.fd = None

    def read_chunk(self, timeout):
        if not select.select([self.fd], [], [], timeout)[0]:
            return b""
        try:
            return os.read(self.fd, 65536)
        except BlockingIOError:
            return b""

    def request(self, command, timeout=3, want_image=False):
        expected = command[3:].split("=")[0]
        payload = (command + "\r").encode("ascii")
        while payload:
            count = os.write(self.fd, payload)
            payload = payload[count:]
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            chunk = self.read_chunk(min(0.2, max(0, end - time.monotonic())))
            for reply in self.stream.feed(chunk):
                if reply.get("name", "").split("@")[-1] != expected:
                    continue
                if reply.get("code") != 0:
                    raise RuntimeError("摄像头返回错误，代码：" + str(reply.get("code")))
                if not want_image or isinstance(reply.get("data", {}).get("image"), str):
                    return reply
        raise TimeoutError("等待摄像头响应超时，请检查连接、设备电源和串口占用。")


def capture_once(port, resolution):
    with SerialPort(port) as serial:
        # Opening the USB interface can precede the vision chip's readiness.
        for attempt in range(3):
            try:
                sensors = serial.request("AT+SENSORS?", timeout=2)["data"]
                break
            except TimeoutError:
                if attempt == 2:
                    raise
        sensor = next((item for item in sensors if item.get("type") == 1), None)
        if sensor is None:
            raise RuntimeError("这块设备没有报告摄像头，请确认购买的是带摄像头版本。")
        sensor_id = int(sensor["id"])
        original_option = int(sensor.get("opt_id", 0))
        desired_option = option_for_resolution(sensor, resolution)
        state = serial.request("AT+INVOKE?").get("data")
        if state == 1:
            raise RuntimeError("视觉检测正在运行，请先关闭小智的视觉推理，再拍照。")
        changed = desired_option != original_option
        try:
            if changed:
                serial.request("AT+SENSOR={0},1,{1}".format(sensor_id, desired_option), timeout=5)
            return decode_image(serial.request("AT+SAMPLE=1", timeout=15, want_image=True))
        finally:
            if changed:
                serial.request("AT+SENSOR={0},1,{1}".format(sensor_id, original_option), timeout=5)


def main():
    parser = argparse.ArgumentParser(description="通过 USB 拍摄 SenseCAP Watcher 的照片。")
    parser.add_argument("--port", help="视觉芯片串口，例如 /dev/cu.usbmodem…01")
    parser.add_argument("--resolution", default="640x480",
                        choices=["240x240", "416x416", "480x480", "640x480"])
    parser.add_argument("--output", type=Path, help="保存照片的完整路径")
    parser.add_argument("--no-open", action="store_true", help="保存后不打开照片")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("此工具适用于 macOS。")
    ports = [args.port] if args.port else sorted(glob.glob("/dev/cu.usbmodem*"))
    preferred = [port for port in ports if port.endswith("1")]
    if not args.port and preferred:
        ports = preferred
    if not ports:
        print("未发现 USB 串口。请用数据线连接 Watcher 底部 USB-C，并允许 Mac 连接。", file=sys.stderr)
        return 1
    errors = []
    for port in ports:
        try:
            print("正在连接摄像头：" + port, flush=True)
            jpeg = capture_once(port, args.resolution)
            break
        except (OSError, ValueError, RuntimeError) as exc:
            errors.append(port + "：" + str(exc))
    else:
        print("拍照未完成。\n" + "\n".join(errors), file=sys.stderr)
        return 1
    if args.output:
        target = args.output.expanduser().resolve()
    else:
        timestamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d-%H%M%S-%f")
        target = Path(__file__).resolve().parent / "photos" / (timestamp + ".jpg")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    temporary.write_bytes(jpeg)
    temporary.replace(target)
    print("照片已保存：" + str(target), flush=True)
    if not args.no_open:
        subprocess.run(["/usr/bin/open", str(target)], check=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("已取消拍照。", file=sys.stderr)
        sys.exit(130)
