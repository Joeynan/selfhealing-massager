# selfhealing 按摩仪

这是当前小智 Watcher、黑色 ESP-12F 板与三路舵机的工程。使用者可以在 macOS Apple Silicon 或 Windows x64 上运行控制台、修改源码及给现有设备烧录。

```text
Watcher 摄像头 → Wi-Fi → 电脑提取 21 手节点并识别
                            ↓
                 Watcher 表情与控制服务
                            ↓ Wi-Fi / SET2
                 黑色 ESP8266 板 → 三路舵机
```

小智可以使用电池、不插电脑 USB；**电脑仍须运行识别服务**。当前没有交付可独立运行的板上 21 节点模型。网页不需要 Node.js 或 npm。

私有仓库：[Joeynan/selfhealing-massager](https://github.com/Joeynan/selfhealing-massager)；小智应用与回滚附件：[Watcher v9 Release](https://github.com/Joeynan/selfhealing-massager/releases/tag/watcher-v9-wheel)。使用者需先取得仓库访问权限。

## 从这里开始

1. 阅读 [使用指南](docs/使用指南.md)，先准备 Python 3.12、可互通的 Wi-Fi 和两块现有设备。
2. 安装项目环境，按指南填写本地地址；首次只在舵机断电时验证显示和摄像头。
3. 需要烧录已验证应用时，从私有仓库 Release 取得附件并按 [发布索引](releases/release-index.json) 校验。源码下载不包含应用镜像、SDK 或编译器。
4. 代码修改后按 [验收清单](docs/验收清单.md) 分别记录自动检查和实物测试。

上传者使用 [GitHub 上传指南](docs/GitHub上传指南.md)，先导出可提交源码，再在导出目录建立 Git 仓库。第三方来源与许可证见 [许可说明](docs/第三方来源与许可.md)。

## 代码和操作软件

电脑手节点与手势规则位于 `outputs/Watcher控制台/camera`：`landmark_server.py` 提取节点，`gesture_rules.py` 判断手势，`wifi_camera.py` 获取 Wi-Fi 画面。它们由 Python 运行，不烧入设备。

小智代码在 `work/xiaozhi-esp32/main/boards/sensecap-watcher-gesture`，使用固定 **ESP-IDF 6.0.1** 编译、根目录烧录入口调用 **esptool 5.4.0** 上传；**Arduino IDE 2** 用于黑板 `.ino`，选择 **ESP8266 Core 3.1.2 / NodeMCU 1.0**。具体源码、库、Wi-Fi 修改及两平台步骤见 [使用指南](docs/使用指南.md)。

## 现有行为

| 手势 | 黑板引脚 | GPIO | 运行 / 中立 |
|---|---|---:|---|
| 捶打 | D1 | 5 | 2000 / 1500µs |
| 揉搓 | D2 | 4 | 2000 / 1500µs |
| 轻捏 | D3 | 0 | 2000 / 1500µs |

舵机控制为 50Hz，每次只运行一组；已保存的自定义校准以设备实际同步值为准。稳定手势确认后表情保持 5 秒，同一手势新确认刷新，新手势立即切换；完全失去手超过 800ms 时停止运动，表情可保留至期限结束。断线、故障、待机和停止按钮受独立停止守卫约束。

输出偏好默认启用；黑板上电仍先保持输出脱离，Watcher 等待中立回执、协议、校准与新鲜输入后才允许动作。无需每次手势或短测重新启用。软件回执只说明指令被接收及提交，实际运动和停转另看实物。

小智 v9 为长按 3 秒开关机／USB 待机，顺时针滚轮进入数据页、逆时针返回大表情页。当前黑板 v7 使用 `hold_protocol=2`，与 v9 兼容。

## 入口和目录

| 入口 | 用途 |
|---|---|
| `启动控制台.command` / `启动控制台.ps1` | 启动 Wi-Fi 画面识别与网页；本机页面默认 `http://127.0.0.1:8890/` |
| `重建运行环境.command` / `重建运行环境.ps1` | 按固定版本安装本机 Python 依赖；不复制别人的虚拟环境 |
| `构建小智固件.command` / `构建小智固件.ps1` | 构建活动 Watcher 应用；不烧录 |
| `烧录小智.command` / `烧录小智.ps1` | 核验 Release 或本机构建应用与设备身份，仅写 `0x200000` |
| `回滚小智.command` / `回滚小智.ps1` | 使用配套 v8 回滚应用，同样执行身份和分区检查 |

- `outputs/Watcher控制台`：网页、服务、电脑识别、黑板源码和测试。
- `work/xiaozhi-esp32`：活动 Watcher 源码；只维护这一份，发布包中的源码是快照。
- `work/requirements`、`tools`：固定依赖、安装、构建、检查与打包程序。
- `docs`、`releases`：中文使用说明、验收记录格式和固件附件索引。

完整本地工程另有 `work/esp-idf`、`work/idf-tools`、运行环境、历史实验、图像和设备备份，均不提交到 GitHub。使用者首次克隆时按指南创建自己的环境与配置。中文和空格路径使用入口程序推导，命令中的路径应加引号。

## 开发与交付边界

本地后续迭代以 `selfhealing 按摩仪` 为唯一活动工程；原 Documents 项目及旧构建目录仅作备份。不要把已下载的整套本地工程直接 `git add .`。可提交文件由 `tools/package_team.py` 的白名单和检查程序决定，私有 Wi-Fi、设备备份及含密码的两板构建镜像留在本机。

构建产物不会自动替换已验证 v9 发布镜像。自行修改的小智应用使用 `--build-dir` 接受同样的身份与分区检查；共享新版本时另建发布清单并记录设备验收，原 v9 / v8 附件保持不变。当前源码和原样固件附件已上传私有 GitHub；本次上传没有烧录设备或测试舵机。最新指南与源码改动验证见 [使用指南更新记录](docs/交付验证/使用指南更新记录.md)，首次上传见 [GitHub 发布记录](docs/交付验证/GitHub发布记录.md)；逐文件校验见导出目录根的 `source-manifest.json`。Windows 和使用者设备结果需按清单填写。
