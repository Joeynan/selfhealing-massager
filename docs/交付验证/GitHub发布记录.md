# GitHub 发布记录

记录时间：2026-10-11T15:31:01.051491+08:00

- 私有仓库：[Joeynan/selfhealing-massager](https://github.com/Joeynan/selfhealing-massager)。
- 已验证的小智 v9 应用与 v8 回滚附件：[Watcher v9 Release](https://github.com/Joeynan/selfhealing-massager/releases/tag/watcher-v9-wheel)。
- 队友安装、联网修改、控制台、烧录与回滚：[队友使用指南](../队友使用指南.md)。
- 后续上传与邀请队友：[GitHub上传指南](../GitHub上传指南.md)。

源码提交前已按白名单及逐文件清单审计；真实网络凭据、SDK、虚拟环境、缓存、日志、设备备份与含密码的黑板二进制未上传。仓库为私有，队友需要维护者邀请。

Release 上传后已通过认证下载并核对 SHA256：`fa4a3fdb3d3242f622feae7e70b45fb2f55c1f31ce725738e8442a3ccb498373`。原 v9、v8 镜像与清单内容保持不变；仅修改了电脑安装／验证入口、测试和交付说明。本次没有枚举串口、烧录设备或驱动舵机。

## 软件检查

上传快照的本地工具测试 87 项：85 项通过，2 项固定 SDK 组件复放测试留待获取组件后的完整构建；控制台和识别规则 220 项通过。此前的完整固定 SDK 构建证据仍见 [交付报告](交付报告.md)。本次未改动两端控制代码或固件镜像。

Windows GitHub Actions 已实际启动。首次验证发现 UTF-8、正在运行的虚拟环境重建、Windows 目录别名和捕获输出后按键等待的问题，相关修复均已添加回归测试。最终 Windows 自动复测结果请查看 [Team validation](https://github.com/Joeynan/selfhealing-massager/actions/workflows/team-validation.yml)；截至本记录，最终复测尚待完成，不能据本地测试宣称 Windows 全部通过。

Windows 完整 SDK 构建、串口烧录、摄像头与两板联动、圆屏电源及机械运动仍按 [队友验收清单](../队友验收清单.md)现场确认。

## 后续迭代

活动源码继续保留在完整 `selfhealing 按摩仪` 工程；`work/team-delivery/source` 是当前已上传的 Git 工作副本。先在活动工程修改、验证和重新审计，再同步到该工作副本提交，避免两处独立修改同一功能。私有配置和设备日志保留本机。

机器可读记录：[GitHub发布记录.json](GitHub发布记录.json)。
