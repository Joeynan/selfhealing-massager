ESP8266 黑色板控制器 v7（hold_protocol=2）

本程序适用 ESP-12F / NodeMCU 引脚定义；三路分别为 D1/GPIO5、D2/GPIO4、D3/GPIO0。
默认中立脉宽为 1500 µs，运行脉宽为 2000 µs。这是连续旋转舵机的转速信号，
板子回报的软件脉宽不能证明机械运动。实际停止和运行需观察实物并校准。

联网与身份
1. 将 wifi_settings.example.h 复制为私有 wifi_settings.h，填写 2.4 GHz Wi-Fi。
   不要把私有文件、USB 配置密码或包含它们的构建目录公开。
2. Node 自动查找 _watcher-servo._tcp 的 8888 服务。服务主机名须为
   watcher-<小智 STA MAC 去掉冒号后的 12 位小写十六进制>。
3. 先发送 HELLO SERVO360 <MAC> <IP> <输出能力 0/1> <profile_id> 6 hold_protocol=2。
   收到精确 WELCOME SERVO360 <Watcher 设备编号> 6 hold_protocol=2 后，
   回报 READY SERVO360 <Watcher 设备编号> hold_protocol=2。旧 WELCOME 6
   可验证身份，但没有截止协议能力，只能观察，不能 ARM 启用输出。
   首次配对登记设备编号；之后必须匹配已登记编号，IP 更新不会更换身份。
4. mDNS 不可用时，用同一局域网的手机访问 http://<黑色板 IP>/。
   用户名 admin；密码只在本地 USB 启动信息 CONFIG_AUTH 中显示，存于 EEPROM。
   页面使用 Digest 认证、每次启动随机请求令牌，填写小智实体屏幕显示的 IP。
   首次设备编号可留空，以目标 IP 的 v6 WELCOME 登记；已有编号会保留校验。
   打开已认证配置页面会禁用输出并 detach；保存后不会自动启用。
5. 设备编号用于防止连接错板，不是加密的设备证明；仅在可信局域网使用。
   Digest 配置认证保护密码传输，但页面与 TCP 指令没有 TLS 加密。

输出与持久化
- 上电、重连、配置时默认禁用，三个 Servo 都不 attach，不产生控制波形。
- 每个新会话须双方确认 hold_protocol=2、成功提交 PROFILE 并持久化后，
  才接受显式 ARM 1。
- ARM 0 / 断线先提交中立，然后 detach。事件记录的 attached_mask 来自实际
  Servo.attached()，禁用事件在 detach 后记录，不把 1500 µs 误称为输出已关闭。
- SET2 租约字段 100–600 ms；真实有效期为收到时租约与黑板本地截止时间
  的较早值，可以少于 100 ms。迟到指令消费序号、立即设置中立，不能重新续期。
- 旧 SET 仅允许未启用时 mode=0，用本次 APPLIED 的 uptime 建立时钟锚。
  启用后旧 SET 一律拒绝；停止应发送 SET2 mode=0 或 ARM 0。
- TEST 为 100–500 ms。重复或旧序号不延长租约。
- 租约到期提交中立；有效指令中断超过 650 ms 后禁用并 detach。
- EEPROM 持久化目标 IP、设备编号、中立/运行脉宽、参数版本及配置密码；
  数据损坏/未来版本均恢复禁用默认状态。写入失败禁止启用输出。
- 参数版本 2 只迁移旧版本三路全为 1500/1560 的默认参数到 1500/2000；
  自定义参数保持不变。运行时修改的参数必须合法并写入成功才确认。
- 不持久化 ARM 状态，不自动重新启用。

协议
PROFILE <seq> <neutral1> <neutral2> <neutral3> <run1> <run2> <run3>
PROFILED <seq> <profile_id>
ARM <seq> <0|1> / ARMED <seq> <0|1>
SET2 <seq> <mode 0..3> <lease_ms> <deadline_ms uint32 黑板本地 millis>
SET <seq> 0 <lease_ms>（仅未启用时的中立时钟基线）
TEST <seq> <channel 1..3> <pulse_us 1000..2000> <lease_ms>
APPLIED / TEST_APPLIED <seq> <mode> <submitted_us1> <submitted_us2> <submitted_us3> <uptime_ms>
EVENT <id> <seq> <reason> <mode> <submitted_us1> <submitted_us2> <submitted_us3>
      <uptime_ms> <historical 0|1> <attached_mask> 5 4 0
reason: 1 SET 活动、2 SET 停止、3 租约到期、4 断线禁用、5 启用/禁用、6 TEST、
        7 PROFILE、8 截止时间已过的指令。
历史 EVENT 仅是历史日志，不替代本次 APPLIED 确认。协议 v4 不兼容 v6 握手，
请同时升级 Watcher 服务；旧服务无匹配 WELCOME 时，黑色板一直保持输出禁用。
