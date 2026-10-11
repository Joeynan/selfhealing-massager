# selfhealing 按摩仪工程

本目录是后续代码迭代的工程根。原 Documents 项目和旧 .codex 构建目录仅作备份，禁止双份维护。

- 活动控制台：outputs/Watcher控制台；采集识别仍在电脑，Watcher 通过 Wi-Fi 提供画面；支持 macOS Apple Silicon 与 Windows x64，不宣称未验证的板上节点模型可独立运行。
- 活动 Watcher 工程：work/xiaozhi-esp32；遵守它的 AGENTS.md。使用已锁定 ESP-IDF 6.0.1，不升级整个 SDK。
- 固定构建工具：work/esp-idf、work/idf-tools；基础 Python 在 work/tools/python-base。以上是完整本地工程环境；新克隆按 docs/使用指南.md 安装本机平台的固定 SDK、Python 和编译器，不复制 Mac 工具或虚拟环境到 Windows。
- 黑板源码：outputs/Watcher控制台/firmware/esp8266/watcher_controller；ESP8266 Core 3.1.2 / NodeMCU 1.0，当前不使用 Uno。
- 历史源码、发布包及设备记录保留。交付包源码是版本快照，活动 Watcher 代码以 work/xiaozhi-esp32 为准；生成新交付包时从该工程同步专用板型，不手工维护两套。
- 标准入口位于工程根：启动控制台.command、构建小智固件.command、烧录小智.command、回滚小智.command；Windows 对应 .ps1，安装及重建环境入口同样位于根目录，共用 tools 中的逻辑。
- 保留 D1 捶打/D2 揉搓/D3 轻捏，2000µs 运行/1500µs 停止/50Hz、SET2 截止时间守卫和现有 UI/电源交互。
- 修改路径时使用工程根推导，不重新依赖旧目录、临时运行副本或用户私有 Codex 缓存。
- 迁移及离线测试禁止连接设备、枚举串口或驱动舵机。烧录与实机运动必须是用户另外授权的任务。
- 构建通过不代表已经烧录或机械运动通过。先执行离线烧录检查再报告完成。

- GitHub 源码交付使用 tools/package_team.py 的白名单导出。私有 Wi-Fi、身份认证密码、设备备份、含密码的两板构建镜像、图片和日志不提交；保留第三方许可证，不擅自为自写代码增加开源授权。
- 新构建不会自动替换已验证发布镜像；原 v9 / v8 镜像与清单保持原文件。Windows CI 在实际推送运行前标记未运行，软件检查和实物验收分开报告。
