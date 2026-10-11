#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>

enum class GestureMouth : uint8_t { Flat, Frown, Smile, Puzzled };
struct GestureEyeBar { int x = 0, y = 0, width = 12, height = 8; };
struct GestureFaceFrame {
    std::array<std::array<GestureEyeBar, 5>, 2> eyes{};
    bool show_brows = false;
    int brow_y = -98;
    int mouth_x = 0;
    int mouth_y = 58;
    GestureMouth mouth = GestureMouth::Flat;
};

// All positions are relative to the 412 px screen centre. Bounds are kept
// inside 320 x 250 px so the physical round panel never clips the expression.
inline GestureFaceFrame GestureFaceGeometry(uint8_t mode, bool connected, uint32_t tick) {
    GestureFaceFrame frame;
    const float phase = tick / 450.0f;
    const bool puzzled = !connected && mode == 0;
    const bool blink = mode == 0 && connected && tick % 3000 < 150;
    const int sway = mode == 2 ? int(6 * std::sin(phase)) : 0;
    const int breathe = mode == 0 ? int(2 * std::sin(tick / 900.0f)) : 0;
    const int heights[5] = {46, 78, 104, 78, 46};
    for (int eye = 0; eye < 2; ++eye) {
        for (int bar = 0; bar < 5; ++bar) {
            auto& value = frame.eyes[eye][bar];
            value.x = (eye ? 82 : -82) + (bar - 2) * 19 + sway;
            value.y = -30 + breathe;
            value.height = heights[bar];
            if (puzzled) {
                value.height = eye ? heights[bar] * 3 / 4 : heights[bar] / 3;
                value.y += eye ? -9 : 12;
            } else if (blink) {
                value.height = 8;
            } else if (mode == 1) {
                value.height = 16 + heights[bar] / 3 + int(3 * std::sin(phase * 2));
                value.y += (eye ? 2 - bar : bar - 2) * 3;
            } else if (mode == 2 || mode == 3) {
                value.height = mode == 3 ? 14 : 9;
                value.y = -33 + std::abs(bar - 2) * (mode == 3 ? 7 : 4);
            }
        }
    }
    frame.show_brows = mode == 1;
    frame.brow_y += int(2 * std::sin(phase * 2));
    frame.mouth_x = sway;
    frame.mouth = puzzled ? GestureMouth::Puzzled
                  : mode == 1 ? GestureMouth::Frown
                  : mode == 2 || mode == 3 ? GestureMouth::Smile
                  : GestureMouth::Flat;
    return frame;
}

inline GestureFaceFrame BlendGestureFace(const GestureFaceFrame& from,
                                         const GestureFaceFrame& to, float fraction) {
    fraction = std::clamp(fraction, 0.0f, 1.0f);
    auto frame = to;
    const auto blend = [fraction](int a, int b) { return a + int((b - a) * fraction); };
    for (int eye = 0; eye < 2; ++eye) {
        for (int bar = 0; bar < 5; ++bar) {
            const auto& a = from.eyes[eye][bar];
            const auto& b = to.eyes[eye][bar];
            frame.eyes[eye][bar] = {blend(a.x, b.x), blend(a.y, b.y),
                                   blend(a.width, b.width), blend(a.height, b.height)};
        }
    }
    frame.mouth_x = blend(from.mouth_x, to.mouth_x);
    frame.mouth_y = blend(from.mouth_y, to.mouth_y);
    return frame;
}
