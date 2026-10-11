#pragma once
#include <array>
#include <cstdint>
#include <string>
namespace onboard {
struct Point {
    float x = 0, y = 0, z = 0;
};
enum class Side { Unknown, Left, Right };
struct Hand {
    uint32_t id = 0;
    Side side = Side::Unknown;
    std::array<Point, 21> points{}, world{};
    bool has_world = false;
    float presence = 1;
};
struct Frame {
    uint64_t id = 0;
    uint32_t captured_ms = 0;
    int width = 0, height = 0;
    uint8_t hand_count = 0;
    std::array<Hand, 2> hands{};
    bool model_ready = false, valid = false, calibrated = false;
    std::string model, error;
};
}  // namespace onboard
