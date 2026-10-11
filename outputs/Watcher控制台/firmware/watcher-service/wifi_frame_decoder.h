#pragma once
#include <cJSON.h>
#include <cmath>
#include <cstring>
#include "wifi_frame.h"
namespace wifi_camera {
inline bool UInt(cJSON* root, const char* key, uint32_t& value) {
    auto* x = cJSON_GetObjectItemCaseSensitive(root, key);
    if (!cJSON_IsNumber(x) || !std::isfinite(x->valuedouble) || x->valuedouble < 0 ||
        x->valuedouble > UINT32_MAX || std::floor(x->valuedouble) != x->valuedouble)
        return false;
    value = uint32_t(x->valuedouble);
    return true;
}
inline int Base64Digit(char c) {
    if (c >= 'A' && c <= 'Z')
        return c - 'A';
    if (c >= 'a' && c <= 'z')
        return c - 'a' + 26;
    if (c >= '0' && c <= '9')
        return c - '0' + 52;
    if (c == '+')
        return 62;
    if (c == '/')
        return 63;
    return -1;
}
inline bool Decode(cJSON* root, uint32_t expected_session, uint32_t request_started,
                   uint32_t received, Frame& frame) {
    auto* name = cJSON_GetObjectItemCaseSensitive(root, "name");
    auto* data = cJSON_GetObjectItemCaseSensitive(root, "data");
    uint32_t type, code, version, w, h, capture, send;
    if (!cJSON_IsString(name) || strcmp(name->valuestring, "FRAME") || !UInt(root, "type", type) ||
        type != 0 || !UInt(root, "code", code) || code != 0 || !UInt(data, "version", version) ||
        version != 1 || !UInt(data, "session", frame.session) ||
        frame.session != expected_session || !UInt(data, "frame_id", frame.id) || !frame.id ||
        !UInt(data, "width", w) || w < 32 || w > 4096 || !UInt(data, "height", h) || h < 32 ||
        h > 4096 || !UInt(data, "capture_ms", capture) || !UInt(data, "send_ms", send) ||
        !CaptureTime(request_started, received, capture, send, frame.captured))
        return false;
    auto* image = cJSON_GetObjectItemCaseSensitive(data, "image");
    if (!cJSON_IsString(image))
        return false;
    const char* text = image->valuestring;
    size_t length = strlen(text);
    if (length < 8 || length > 4 * ((kMaxJpeg + 2) / 3) || length % 4)
        return false;
    frame.jpeg.clear();
    frame.jpeg.reserve(length / 4 * 3);
    for (size_t i = 0; i < length; i += 4) {
        int a = Base64Digit(text[i]), b = Base64Digit(text[i + 1]);
        int c = text[i + 2] == '=' ? 0 : Base64Digit(text[i + 2]);
        int d = text[i + 3] == '=' ? 0 : Base64Digit(text[i + 3]);
        bool p2 = text[i + 2] == '=', p3 = text[i + 3] == '=';
        if (a < 0 || b < 0 || c < 0 || d < 0 || (p2 && !p3) || ((p2 || p3) && i + 4 != length) ||
            (p2 && (b & 15)) || (!p2 && p3 && (c & 3)))
            return false;
        frame.jpeg.push_back(uint8_t((a << 2) | (b >> 4)));
        if (!p2)
            frame.jpeg.push_back(uint8_t((b << 4) | (c >> 2)));
        if (!p3)
            frame.jpeg.push_back(uint8_t((c << 6) | d));
    }
    auto& j = frame.jpeg;
    if (j.size() < 4 || j.size() > kMaxJpeg || j[0] != 0xff || j[1] != 0xd8 ||
        j[j.size() - 2] != 0xff || j.back() != 0xd9)
        return false;
    frame.width = w;
    frame.height = h;
    return true;
}
}  // namespace wifi_camera
