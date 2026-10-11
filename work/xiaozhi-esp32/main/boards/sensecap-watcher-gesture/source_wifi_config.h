#pragma once

namespace watcher_source_wifi {

// 成功与故障分开回报；故障不记录已应用指纹，也不输出网络凭据。
enum class Result { Disabled, Unchanged, Applied, Invalid, ListFull, StorageError };

// NVS 已初始化、SsidManager 尚未首次实例化时调用，避免它缓存导入前的网络列表。
Result ApplyCompiled();

// 核心导入逻辑独立于私有头文件；便于用隔离 NVS 存储验证失败处理。
Result Apply(bool enabled, const char* ssid, const char* password);

}  // namespace watcher_source_wifi
