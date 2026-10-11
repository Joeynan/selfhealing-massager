// 复制为本目录的 wifi_settings.h，填写实际 2.4GHz Wi-Fi 后在 Arduino IDE 重新编译上传。
// 这是私有配置：不要将填写后的头文件或包含密码的构建镜像上传 GitHub。
#pragma once
// Copy to wifi_settings.h and enter the current 2.4 GHz network locally.
constexpr const char* WIFI_SSID = "YOUR_WIFI_NAME";
constexpr const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
// Watcher is discovered on TCP 8888 and bound by its device ID after WELCOME.
// If mDNS is blocked, enter its screen IP through the authenticated phone page.
