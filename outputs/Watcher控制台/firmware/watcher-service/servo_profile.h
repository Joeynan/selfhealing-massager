#pragma once
#include <cstdint>
constexpr uint16_t kNeutralUs[3] = {1500, 1500, 1500};
constexpr uint16_t kRunUs[3] = {2000, 2000, 2000};
constexpr uint32_t kServoProfileVersion = 2;
struct ServoProfile {
    uint16_t neutral[3] = {1500, 1500, 1500}, run[3] = {2000, 2000, 2000};
    bool Valid() const {
        for (int i = 0; i < 3; ++i) {
            if (neutral[i] < 1400 || neutral[i] > 1600 || neutral[i] % 10 ||
                run[i] <= neutral[i] || run[i] > 2000 || run[i] % 10)
                return false;
        }
        return true;
    }
    // Upgrade only the exact old default. Preserve deliberate user calibration.
    bool MigrateLegacyDefault(uint32_t version) {
        if (version >= kServoProfileVersion) return false;
        for (int i=0;i<3;++i)
            if (neutral[i] != 1500 || run[i] != 1560) return false;
        for (int i=0;i<3;++i) run[i] = 2000;
        return true;
    }
    uint32_t Id() const {
        uint32_t h = 2166136261u;
        for (int i = 0; i < 3; ++i) {
            h = (h ^ neutral[i]) * 16777619u;
            h = (h ^ run[i]) * 16777619u;
        }
        return h;
    }
};
