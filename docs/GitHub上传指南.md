# GitHub 上传指南

当前源码已上传私有仓库 [Joeynan/selfhealing-massager](https://github.com/Joeynan/selfhealing-massager)，原样 v9 应用与 v8 回滚附件在 [Watcher v9 Release](https://github.com/Joeynan/selfhealing-massager/releases/tag/watcher-v9-wheel)。队友需要仓库访问权限；私有仓库也不保存真实 Wi-Fi 密码或设备备份。以下保留首次上传和后续更新的方法，已有项目更新时使用当前仓库，不重复创建。

## 1. 先导出待提交源码

在完整 `selfhealing 按摩仪` 工程根运行，Python 使用本机 3.12：

```text
python tools/package_team.py audit
python tools/package_team.py export --destination "work/team-delivery/source"
python tools/package_team.py releases --destination "work/team-delivery/releases"
```

Mac 可把 `python` 换为 `python3.12`，Windows 可用 `py -3.12`。目标必须为新的空目录；已有交付目录不要覆盖，用新的目录名生成下一版。导出遵循提交白名单，并再次扫描可提交文本，只显示问题文件位置，不显示密码。审计失败先修复，不继续上传。

- `source`：源码、入口、锁、示例、补丁、测试及说明，适合作为 Git 根。
- `releases`：`selfhealing-watcher-v9.zip` 等附件，适合上传 Release，不加入源码提交。
- `releases/release-index.json`：源码内的附件索引，记录版本、文件名、大小及 SHA256；远程 URL 为空表示尚未上传。

不要在整套完整工程直接 `git init` 或 `git add .`。SDK、编译器、venv、缓存、历史实验、照片、日志、NVS／EEPROM 与烧录前设备镜像均只留本地。黑板固件含本地 Wi-Fi 密码，由每位队友填写私有头文件后自行构建，不发黑板二进制。

## 2. 建私有仓库并上传

1. 登录 GitHub，新建私有仓库，例如 `selfhealing-massager`。首次建空仓库，不勾选初始化 README、许可证或 gitignore，避免与导出源码冲突。
2. 进入刚导出的 `source` 目录，初始化 Git；这里的 `git add .` 仅针对已审计的导出内容：

   ```text
   git init -b main
   python tools/package_team.py audit
   git add .
   git diff --cached --stat
   git status --short
   python tools/package_team.py audit --staged
   git commit -m "Prepare teammate source and usage guide"
   git remote add origin https://github.com/YOUR_ACCOUNT/YOUR_PRIVATE_REPO.git
   git remote -v
   git push -u origin main
   ```

3. 替换仓库 URL，不把个人访问令牌写入地址或脚本；使用 GitHub Desktop 或 Git 的认证流程。
4. GitHub 仓库 Settings → Collaborators 中添加队友；组织仓库按组织权限邀请。确认队友可以访问源码及私有 Release。

如果上传前检查报告私有文件，即使它被 `.gitignore` 忽略也检查是否曾被 Git 跟踪；忽略规则不会自动移除已跟踪内容。先移出提交，必要时撤销暂存重新检查。如果真实凭据已推送，立即更换相应凭据并按 GitHub 的敏感数据处理说明处理历史。

流程参考 [GitHub 官方本地代码上传指南](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)。

## 3. 上传应用与回滚附件

在仓库 Releases 创建版本，例如 `watcher-v9-wheel`；附上 `selfhealing-watcher-v9.zip`。ZIP 内保持已验证文件原样：

```text
release-manifest.json
watcher-controller-v9-wheel-face.bin
上一版回滚/release-manifest.json
上一版回滚/watcher-controller-v8-continuous-output.bin
```

不要附上黑板含密码的 `.bin`、全片备份、NVS／EEPROM 或原始串口日志。源码仓库不放大镜像。Release 说明应写清当前应用／回滚版本、指定设备身份、仅写应用 `0x200000`、固定 SDK、校验和，以及还需队友实机验证的事项。

上传后下载附件对照 `releases/release-index.json` 的 SHA256，再把真实 Release 下载链接填入索引中预留的 URL 字段并提交；未上传前保持空值，不生成虚构链接。队友按 [使用指南](队友使用指南.md) 解压至 `work/releases/watcher-v9`，先离线检查再写入。

## 4. 后续迭代

完整本地工程仍是活动源；导出目录是可提交快照。每次从活动工程重新审计、导出到新空目录，比较导出清单，再把通过检查的变动同步到 Git 工作副本。不要将队友私有配置、现场日志或运行目录反向并入活动源码。

建议一项功能一分支，经回归与队友验收后合并；GitHub 的 `Team validation` 流程只做软件检查，不连接设备。Windows 自动流程仅在仓库实际推送后运行，其结果不等于 Windows 实物烧录成功。

新应用版本使用新清单和 Release 附件，旧 v9／v8 校验值不改；记录源码版本、依赖锁、镜像 SHA、已验证内容及待验证项目。队友现场测试按 [验收清单](队友验收清单.md) 反馈。
