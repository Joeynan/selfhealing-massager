# selfhealing Watcher 专用板型

这里是活动小智固件的硬件、摄像头、手势保持、表情与舵机转发代码，属于 `work/xiaozhi-esp32` 的 ESP-IDF 工程。电脑识别代码在工程根的 `outputs/Watcher控制台/camera`，不烧入小智；黑板 `.ino` 另用 Arduino IDE 2 上传。完整操作见 [使用指南](../../../../../docs/使用指南.md)。

## 主要源码

| 文件 | 作用 |
|---|---|
| `sensecap_watcher.cc` | 初始化硬件、配网命令与源码配网、长按电源、滚轮切换 |
| `onboard_camera.cc` | 与预装视觉固件取图，向电脑提供 Wi-Fi 画面 |
| `gesture_service.cc` | 接收电脑确认、维护设备状态、与黑板握手及 SET2 转发 |
| `gesture_hold.h` | 5 秒动作／表情期限及输入失效守卫 |
| `gesture_ui.h`、`gesture_face.h` | 数据页与全黑背景表情动画 |
| `wifi_settings.example.h` | 本地源码配网模板；复制为私有 `wifi_settings.h` 后填写 |

保留捶打→D1、揉搓→D2、轻捏→D3，运行 2000µs、中立 1500µs、50Hz，每次只运行一组。表情保持与停止守卫分开，软件回执不代表实际机械运动。

## 编译与上传软件

使用固定 **ESP-IDF 6.0.1**，不是 Arduino IDE，也不使用其他板型的 `idf.py build flash`。先按使用指南准备并激活本平台 SDK，再回到完整工程根运行：

macOS：

```zsh
./构建小智固件.command --clean --jobs 6 --idf-path "work/esp-idf"
./烧录小智.command --build-dir "work/xiaozhi-esp32/build" --dry-run
```

Windows PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File .\构建小智固件.ps1 --clean --jobs 6 --idf-path "work/esp-idf"
powershell -ExecutionPolicy Bypass -File .\烧录小智.ps1 --build-dir "work/xiaozhi-esp32/build" --dry-run
```

构建入口锁定 ESP32-S3、专用板型 `sensecap-watcher-wheel-v9`、32MB Flash 和当前 4MiB 应用构建布局。输出为 `build/xiaozhi.bin` 与 `build/selfhealing-build-report.json`；不替换历史 v9／v8 发布镜像。

烧录入口使用 **esptool 5.4.0**，离线检查通过后指定本机实际控制串口，例如在上述命令中将 `--dry-run` 改为 `--port COM7`（Windows）或实际 `/dev/cu.usbmodem...703`（Mac）。烧录前舵机独立 5V 断电，并关闭串口监视器。入口继续核验设备 MAC、实际分区及启动槽，只写应用 **`0x200000`**，保留 NVS、Wi-Fi 和视觉固件。不能把此板型当成通用 SenseCAP 示例进行全片烧录。

原样发布包使用 `--release-dir "work/releases/watcher-v9"`，回滚使用根目录回滚入口；`--build-dir` 与发布包、回滚模式互斥。设备身份或分区校验失败需查明原因，不修改检查绕过。

## 网络与私有配置

小智可在 115200 串口用 `lan_wifi "YOUR WIFI NAME" "YOUR_WIFI_PASSWORD"` 保存网络后重启；原 v9 附件只支持这条配网路线。

新源码还支持在本目录的私有 `wifi_settings.h` 中设置 `WATCHER_SOURCE_WIFI_ENABLED = true`、`WIFI_SSID` 和 `WIFI_PASSWORD`，再构建上传。首次或内容改变时应用一次；以后相同代码配置不会覆盖串口修改。模板默认关闭。完整输入规则、优先级与 IP 设置见使用指南第 7 节。

私有头文件以及开启源码配网后生成的应用镜像会携带网络信息，只保留本地。构建成功或软件回执通过不等于设备和机械验收通过；实机项目按 [验收清单](../../../../../docs/验收清单.md) 记录。
