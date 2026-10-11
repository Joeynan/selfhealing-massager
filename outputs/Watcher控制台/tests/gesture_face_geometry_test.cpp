#include "../firmware/watcher-service/gesture_face_geometry.h"
#include <cassert>
#include <cmath>

int main() {
    for (uint8_t mode = 0; mode <= 3; ++mode) {
        for (bool connected : {false, true}) {
            for (uint32_t tick = 0; tick < 6000; tick += 50) {
                const auto face = GestureFaceGeometry(mode, connected, tick);
                for (const auto& eye : face.eyes) {
                    for (const auto& bar : eye) {
                        assert(bar.width > 0 && bar.height >= 6);
                        assert(std::abs(bar.x) + bar.width / 2 <= 160);
                        assert(std::abs(bar.y) + bar.height / 2 <= 125);
                        const float x = std::abs(bar.x) + bar.width / 2.0f;
                        const float y = std::abs(bar.y) + bar.height / 2.0f;
                        assert(x * x + y * y < 206 * 206);
                    }
                }
                assert(face.show_brows == (mode == 1));
            }
        }
    }
    const auto waiting = GestureFaceGeometry(0, true, 600);
    const auto blink = GestureFaceGeometry(0, true, 3050);
    assert(waiting.eyes[0][2].height > blink.eyes[0][2].height);
    const auto kneading = GestureFaceGeometry(2, true, 900);
    const auto pinch = GestureFaceGeometry(3, true, 900);
    assert(kneading.mouth == GestureMouth::Smile);
    assert(pinch.mouth == GestureMouth::Smile);
    assert(GestureFaceGeometry(0, false, 900).mouth == GestureMouth::Puzzled);
    // A recognized gesture always wins over an outstanding/disconnected receipt.
    assert(GestureFaceGeometry(3, false, 900).mouth == GestureMouth::Smile);
    const auto blend0 = BlendGestureFace(waiting, kneading, 0);
    const auto blend1 = BlendGestureFace(waiting, kneading, 1);
    assert(blend0.eyes[0][2].height == waiting.eyes[0][2].height);
    assert(blend1.eyes[0][2].height == kneading.eyes[0][2].height);
    assert(blend1.mouth == kneading.mouth);
}
