# Watcher Wi-Fi 图像接收：校验设备身份、JPEG 完整性、采集会话、帧号和画面年龄。
# 两台设备时钟不同，因此用本机请求时间扣除设备帧年龄，不直接比较绝对时间。
"""Bounded Wi-Fi snapshots. Device clocks are never compared with Mac clocks."""
from collections import deque
from dataclasses import dataclass
import re
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler

MAX_JPEG = 98304


@dataclass(frozen=True)
class WiFiFrame:
    jpeg: bytes
    timestamp_ms: int
    session_id: str
    frame_id: int
    width: int
    height: int
    transfer_ms: int


class WiFiFrameReader:
    def __init__(self, url, expected_id, timeout=.65):
        parsed = urlsplit(url)
        if (parsed.scheme != 'http' or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path != '/frame'):
            raise ValueError('摄像头地址应为 http://小智地址:8081/frame')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,96}', expected_id or ''):
            raise ValueError('请指定小智设备 ID')
        self.url=url;self.expected_id=expected_id;self.timeout=timeout
        self.opener=build_opener(ProxyHandler({}))
        self.session=None;self.last_id=0;self.retired=deque(maxlen=16)

    @staticmethod
    def integer(headers, key, low, high):
        value=headers.get(key, '')
        if not isinstance(value,str) or not re.fullmatch(r'[0-9]{1,10}',value):
            raise ValueError('无效画面元数据：'+key)
        value=int(value)
        if not low<=value<=high:raise ValueError('画面元数据超出范围：'+key)
        return value

    # 拒绝重复帧、已结束的会话和总年龄达到 800ms 的图像；它们不能延长动作。
    def decode(self, jpeg, headers, request_start_ms, receive_ms):
        # HTTP field names are case insensitive, including in offline fixtures.
        h={str(k).lower():v for k,v in headers.items()}
        if h.get('content-type','').split(';')[0].strip().lower()!='image/jpeg':
            raise ValueError('设备没有返回 JPEG 画面')
        if h.get('x-watcher-id')!=self.expected_id:raise ValueError('摄像头设备 ID 不匹配')
        length=self.integer(h,'content-length',4,MAX_JPEG)
        if len(jpeg)!=length or not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'):
            raise ValueError('画面不完整或 JPEG 格式无效')
        session=h.get('x-capture-session','')
        if not isinstance(session,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,96}',session):
            raise ValueError('无效摄像头会话')
        frame_id=self.integer(h,'x-frame-id',1,0xffffffff)
        age=self.integer(h,'x-frame-age-ms',0,799)
        width=self.integer(h,'x-frame-width',32,4096)
        height=self.integer(h,'x-frame-height',32,4096)
        transfer=receive_ms-request_start_ms
        if transfer<0 or transfer+age>=800:raise ValueError('无线画面已过期')
        if session in self.retired:return None
        if session!=self.session:
            if self.session is not None:self.retired.append(self.session)
            self.session=session;self.last_id=0
        if frame_id<=self.last_id:return None
        self.last_id=frame_id
        return WiFiFrame(jpeg,request_start_ms-age,session,frame_id,width,height,transfer)

    def fetch(self):
        start=time.monotonic_ns()//1_000_000
        request=Request(self.url,headers={'Accept':'image/jpeg','Cache-Control':'no-cache'})
        with self.opener.open(request,timeout=self.timeout) as response:
            if response.geturl()!=self.url:raise ValueError('摄像头地址发生重定向')
            h=response.headers
            length=self.integer(h,'Content-Length',4,MAX_JPEG)
            chunks=[];size=0
            while size<=length:
                if time.monotonic_ns()//1_000_000-start>=self.timeout*1000:
                    raise TimeoutError('无线画面传输超时')
                chunk=response.read1(min(8192,length+1-size))
                if not chunk:break
                chunks.append(chunk);size+=len(chunk)
            body=b''.join(chunks)
        return self.decode(body,h,start,time.monotonic_ns()//1_000_000)
