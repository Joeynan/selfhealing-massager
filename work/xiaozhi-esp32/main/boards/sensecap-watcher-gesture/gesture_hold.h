// 表情与动作保持状态：新有效确认启动/刷新 5 秒，另一手势立即切换。
// 无手超过 800ms 停止动作；表情可保留至 5 秒，短通信租约仍单独检查。
#pragma once
#include <algorithm>
#include <cstdint>
#include <cstring>

enum class ObservationKind { Confirmed, Confirming, Unrecognized, NoHand, Conflict, Error };
inline const char* ObservationLabel(ObservationKind k) {
    switch (k) {
    case ObservationKind::Confirmed: return "confirmed";
    case ObservationKind::Confirming: return "confirming";
    case ObservationKind::Unrecognized: return "unrecognized";
    case ObservationKind::NoHand: return "no_hand";
    case ObservationKind::Conflict: return "conflict";
    default: return "error";
    }
}
inline bool ParseObservation(const char* s, ObservationKind& k) {
    if (!s) return false;
    for (auto v : {ObservationKind::Confirmed, ObservationKind::Confirming,
                  ObservationKind::Unrecognized, ObservationKind::NoHand,
                  ObservationKind::Conflict, ObservationKind::Error})
        if (!std::strcmp(s, ObservationLabel(v))) { k = v; return true; }
    return false;
}
inline uint32_t Until(uint32_t deadline, uint32_t now) {
    return int32_t(deadline - now) > 0 ? deadline - now : 0;
}

// Five-second presentation/action state is independent of the short wire lease.
// Only verified unique observations may be passed here (Ledger owns frame proofs).
class GestureHold {
    bool seen_ = false, hand_seen_ = false, epoch_seen_ = false;
    uint8_t face_ = 0, motion_ = 0;
    uint32_t observed_ = 0, hand_ = 0, deadline_ = 0, armed_at_ = 0;
    uint32_t events_ = 0;
    const char* reason_ = "startup";
    ObservationKind kind_ = ObservationKind::Unrecognized;
public:
    void Reset() {
        seen_ = hand_seen_ = epoch_seen_ = false;
        face_ = motion_ = 0;
        observed_ = hand_ = deadline_ = armed_at_ = 0;
        kind_ = ObservationKind::Unrecognized;
        reason_ = "reset";
    }
    // Cancelling an action does not manufacture new recognition health.
    void Cancel() {
        face_ = motion_ = 0; deadline_ = 0; epoch_seen_ = false;
        reason_ = "cancelled";
    }
    void ArmEpoch(uint32_t now) {
        face_ = motion_ = 0;
        epoch_seen_ = true;
        armed_at_ = now;
        reason_ = "arming";
    }
    bool Observe(uint32_t captured, uint8_t mode, ObservationKind kind, bool confirmed,
                 bool hand, uint32_t confirmation_age, uint32_t now) {
        if (now - captured >= 800 || mode > 3 ||
            confirmed != (kind == ObservationKind::Confirmed) ||
            (confirmed && (!mode || !hand || confirmation_age < 300 || confirmation_age > 2500)) ||
            (!confirmed && mode) || (kind == ObservationKind::NoHand && hand) ||
            (kind != ObservationKind::NoHand && kind != ObservationKind::Error && !hand))
            return false;
        Tick(now);
        seen_ = true;
        observed_ = captured;
        kind_ = kind;
        if (kind == ObservationKind::Error || kind == ObservationKind::Conflict) {
            face_ = motion_ = 0;
            reason_ = kind == ObservationKind::Error ? "recognition_error" : "hand_conflict";
            if (kind == ObservationKind::Error) seen_ = false;
            return true;
        }
        if (hand) { hand_seen_ = true; hand_ = captured; }
        if (confirmed && (!epoch_seen_ || int32_t(captured - confirmation_age - armed_at_) >= 0)) {
            reason_ = face_ != mode ? "gesture_switch" : "gesture_refresh";
            face_ = motion_ = mode;
            deadline_ = captured + 5000;
            ++events_;
        }
        return true;
    }
    bool Healthy(uint32_t now) const { return seen_ && now - observed_ < 800; }
    void Tick(uint32_t now) {
        if (face_ && !Until(deadline_, now)) face_ = 0;
        if (!motion_) return;
        if (!Healthy(now)) { motion_ = 0; reason_ = "observation_timeout"; }
        else if (!hand_seen_ || now - hand_ >= 800) { motion_ = 0; reason_ = "no_hand"; }
        else if (!Until(deadline_, now)) { motion_ = 0; reason_ = "hold_expired"; }
    }
    uint8_t Face(uint32_t now) const { return Until(deadline_, now) ? face_ : 0; }
    uint8_t Motion(uint32_t now) { Tick(now); return motion_; }
    uint32_t FaceRemaining(uint32_t now) const { return Face(now) ? Until(deadline_, now) : 0; }
    // 可转发时间取所有剩余期限的最小值；普通未识别不能把 5 秒重新计满。
    uint32_t MotionRemaining(uint32_t now, uint32_t camera_captured) {
        if (!Motion(now) || now - camera_captured >= 800) return 0;
        return std::min({Until(deadline_, now), 800u - (now - observed_),
                         800u - (now - hand_), 800u - (now - camera_captured)});
    }
    uint32_t Events() const { return events_; }
    const char* Reason() const { return reason_; }
    ObservationKind Kind() const { return kind_; }
};
