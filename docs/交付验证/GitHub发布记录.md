# GitHub 发布记录

记录时间：2026-10-11T16:02:25.113977+08:00

本页保留首次上传记录。后续使用指南、源码配网、中文注释及本机构建烧录的验证见 [使用指南更新记录](使用指南更新记录.md)。

- 私有仓库：[Joeynan/selfhealing-massager](https://github.com/Joeynan/selfhealing-massager)。
- 已验证的小智 v9 应用与 v8 回滚附件：[Watcher v9 Release](https://github.com/Joeynan/selfhealing-massager/releases/tag/watcher-v9-wheel)。
- 使用者安装、联网修改、控制台、烧录与回滚：[使用指南](../使用指南.md)。
- 后续上传与邀请使用者：[GitHub上传指南](../GitHub上传指南.md)。

源码提交前已按白名单及逐文件清单审计；真实网络凭据、SDK、虚拟环境、缓存、日志、设备备份与含密码的黑板二进制未上传。仓库为私有，使用者需要维护者邀请。

Release 上传后已通过认证下载并核对 SHA256：`fa4a3fdb3d3242f622feae7e70b45fb2f55c1f31ce725738e8442a3ccb498373`。原 v9、v8 镜像与清单内容保持不变；修改了电脑安装／验证入口、测试和交付说明，并修正控制台兼容旧版设备时的状态时间边界及 Windows 中文路径下的模型加载。本次没有枚举串口、烧录设备或驱动舵机。

## 软件检查

上传快照的本地工具测试 88 项：86 项通过，2 项固定 SDK 组件复放测试留待获取组件后的完整构建；控制台和识别规则 222 项通过。此前的完整固定 SDK 构建证据仍见 [交付报告](交付报告.md)。本次未改动两端固件或镜像。

Windows GitHub Actions 自动验证已通过：固定依赖与模型安装、源码审计、88 项工具测试（86 项通过、2 项 SDK 组件测试跳过）、222 项控制台回归、CPU 模型加载、网页语法、离线烧录与回滚保护及离线页面启动。

实际结果：[Windows 自动验证](https://github.com/Joeynan/selfhealing-massager/actions/runs/38123231664)；验证代码提交：`b4a813cf7c88b76c4225452aee4fa91bde974f76`。

本次实际运行中发现并修正了 UTF-8、Windows 虚拟环境重建、目录别名、重定向输出下的等待、测试子进程保护及同一时钟刻度下的旧状态边界，均保留回归测试。

Windows 完整 SDK 构建、串口烧录、摄像头与两板联动、圆屏电源及机械运动仍按 [验收清单](../验收清单.md)现场确认。

## 后续迭代

活动源码继续保留在完整 `selfhealing 按摩仪` 工程；`work/team-delivery/source` 是当前已上传的 Git 工作副本。先在活动工程修改、验证和重新审计，再同步到该工作副本提交，避免两处独立修改同一功能。私有配置和设备日志保留本机。

机器可读记录：[GitHub发布记录.json](GitHub发布记录.json)。
