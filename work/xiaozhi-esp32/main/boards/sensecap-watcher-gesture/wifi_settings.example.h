#pragma once

// 复制为本目录的 wifi_settings.h 后填写。私有头文件与含凭据的构建镜像只保留本地。
// false：沿用设备已保存的网络；true：首次或名称/密码改变后导入一次。
// 导入成功后，此文件不变时，不覆盖随后通过 lan_wifi 保存的修改。
constexpr bool WATCHER_SOURCE_WIFI_ENABLED = false;

// 使用普通 UTF-8 字符串：名称允许 1–32 字节，密码允许 8–63 字节。
// 空格直接写；双引号写成 \"，反斜杠写成 \\；不要保留 YOUR_ 占位。
constexpr const char* WIFI_SSID = "YOUR_WIFI_NAME";
constexpr const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
