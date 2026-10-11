#pragma once
#include <algorithm>
#include <cmath>
#include "onboard_landmarks.h"
namespace onboard {
struct Config {
    int back_sign[2] = {0, 0};
    uint32_t lost_ms = 800, confirm_ms = 300;
    unsigned confirm_frames = 3;
};
struct Features {
    float palm = 0, normal_z = 0, pinch = 0, thumb_open = 0, thumb_length = 0, cluster = 0;
    std::array<float, 4> angles{}, ratios{}, lengths{};
    std::array<bool, 4> folded{}, extended{};
};
inline float Distance(Point a, Point b, bool xy = false) {
    return std::sqrt((a.x - b.x) * (a.x - b.x) + (a.y - b.y) * (a.y - b.y) +
                     (xy ? 0 : (a.z - b.z) * (a.z - b.z)));
}
inline bool Finite(Point p) {
    return std::isfinite(p.x) && std::isfinite(p.y) && std::isfinite(p.z);
}
inline bool Extract(const Hand& h, int w, int height, Features& f) {
    if (w < 1 || height < 1 || h.presence < .5f || !std::isfinite(h.presence))
        return false;
    std::array<Point, 21> p, geo;
    for (int i = 0; i < 21; i++) {
        auto q = h.points[i];
        if (!Finite(q) || q.x < -.05f || q.x > 1.05f || q.y < -.05f || q.y > 1.05f ||
            std::fabs(q.z) > 10)
            return false;
        p[i] = {q.x * w, q.y * height, q.z * w};
        geo[i] = h.has_world ? h.world[i] : p[i];
        if (!Finite(geo[i]))
            return false;
    }
    f.palm = Distance(p[0], p[9], true);
    if (f.palm < 30)
        return false;
    for (int j = 0; j < 4; j++) {
        int b = 5 + 4 * j;
        Point u{geo[b].x - geo[b + 1].x, geo[b].y - geo[b + 1].y, geo[b].z - geo[b + 1].z},
            v{geo[b + 2].x - geo[b + 1].x, geo[b + 2].y - geo[b + 1].y,
              geo[b + 2].z - geo[b + 1].z};
        float den = Distance(u, {}) * Distance(v, {});
        if (den < 1e-9f)
            return false;
        f.angles[j] = std::acos(std::clamp((u.x * v.x + u.y * v.y + u.z * v.z) / den, -1.f, 1.f)) *
                      180 / 3.14159265358979323846f;
        f.folded[j] =
            f.angles[j] < 145 && Distance(p[b + 3], p[0], true) < Distance(p[b + 1], p[0], true);
        f.extended[j] = f.angles[j] > 150 &&
                        Distance(p[b + 3], p[0], true) > 1.1f * Distance(p[b + 1], p[0], true) &&
                        Distance(p[b + 3], p[b], true) > .6f * f.palm;
        f.ratios[j] = Distance(p[4], p[b + 3], true) / f.palm;
        f.lengths[j] = Distance(p[b], p[b + 3], true) / f.palm;
    }
    Point u{p[5].x - p[0].x, p[5].y - p[0].y, p[5].z - p[0].z},
        v{p[17].x - p[0].x, p[17].y - p[0].y, p[17].z - p[0].z},
        n{u.y * v.z - u.z * v.y, u.z * v.x - u.x * v.z, u.x * v.y - u.y * v.x};
    float norm = Distance(n, {});
    f.normal_z = norm > 1e-6f ? n.z / norm : 0;
    f.pinch = f.ratios[0];
    f.thumb_open = Distance(p[4], p[5], true) / f.palm;
    f.thumb_length = Distance(p[4], p[0], true) / f.palm;
    f.cluster = 0;
    for (int a = 8; a <= 20; a += 4)
        for (int b = 8; b <= 20; b += 4)
            f.cluster = std::max(f.cluster, Distance(p[a], p[b], true) / f.palm);
    return true;
}
struct HandState {
    bool pinching = false, has_start = false, has_completed = false, baseline = false;
    enum Phase { Waiting, Closed, Opened } phase = Waiting;
    uint32_t cycle_start = 0, phase_at = 0, completed_at = 0, active_until = 0, last_seen = 0;
    std::array<float, 4> open_ratios{}, open_angles{}, open_lengths{};
    uint8_t Classify(const Features& f, Side side, uint32_t t, const Config& c) {
        unsigned spread = 0, folds = 0, extends = 0, gathers = 0, curls = 0, opens = 0;
        for (int i = 0; i < 4; i++) {
            folds += f.folded[i];
            extends += f.extended[i];
            gathers += f.ratios[i] <= .55f;
            curls += f.lengths[i] <= .65f;
            opens += f.ratios[i] >= .85f;
            if (i && f.extended[i] && f.ratios[i] >= .7f)
                spread++;
        }
        pinching = f.pinch < (pinching ? .35f : .25f) && spread >= 2;
        int sign = side == Side::Left ? c.back_sign[0] : side == Side::Right ? c.back_sign[1] : 0;
        bool pounding = sign && f.normal_z * sign >= .45f && folds == 4 && f.thumb_open >= .15f &&
                        f.thumb_open <= 1.25f && f.thumb_length <= 1.95f && f.pinch > .35f;
        bool gathered = f.pinch <= .35f && gathers >= 3 &&
                        *std::max_element(f.ratios.begin(), f.ratios.end()) <= .95f;
        bool curled = curls >= 3 && folds >= 2 && !extends && f.cluster <= 1.f;
        bool closed = gathered || curled,
             opened = !closed && (extends >= 3 || (folds <= 1 && opens >= 3));
        auto moving = [&] {
            int gathering = 0, curling = 0;
            if (baseline)
                for (int i = 0; i < 4; i++) {
                    gathering += open_ratios[i] - f.ratios[i] >= .35f;
                    curling += open_lengths[i] - f.lengths[i] >= .4f;
                }
            return gathered ? gathering : curled ? curling : std::max(gathering, curling);
        };
        if (phase == Opened && !has_start && baseline && moving() >= 3) {
            cycle_start = std::max(phase_at, last_seen);
            has_start = true;
        }
        if (has_start && uint32_t(t - cycle_start) > 2500) {
            phase = Waiting;
            has_start = baseline = false;
        }
        auto save = [&] {
            open_ratios = f.ratios;
            open_angles = f.angles;
            open_lengths = f.lengths;
            baseline = true;
        };
        if (phase == Waiting && closed) {
            phase = Closed;
            has_start = true;
            cycle_start = phase_at = t;
        } else if (phase == Waiting && opened) {
            phase = Opened;
            has_start = false;
            phase_at = t;
            save();
        } else if (phase == Closed && opened && uint32_t(t - phase_at) >= 80) {
            phase = Opened;
            cycle_start = std::max(phase_at, last_seen);
            has_start = true;
            phase_at = t;
            save();
            if (has_completed && uint32_t(t - completed_at) <= 2500)
                active_until = t + c.lost_ms;
        } else if (phase == Opened && closed && uint32_t(t - phase_at) >= 80) {
            uint32_t duration = has_start ? t - cycle_start : 0;
            int bends = 0;
            if (baseline)
                for (int i = 0; i < 4; i++)
                    bends += open_angles[i] - f.angles[i] >= 10;
            if (duration >= 400 && duration <= 2500 && moving() >= 3 && bends >= 2) {
                has_completed = true;
                completed_at = t;
                active_until = t + c.lost_ms;
            }
            phase = Closed;
            has_start = true;
            cycle_start = phase_at = t;
            baseline = false;
        }
        bool kneading =
            has_completed && int32_t(active_until - t) > 0 && uint32_t(t - completed_at) <= 2500;
        last_seen = t;
        return (pounding && !kneading ? 1 : 0) | (kneading ? 2 : 0) | (pinching ? 4 : 0);
    }
};
struct Result {
    uint8_t raw = 0, stable = 0;
    unsigned confirms = 0;
    uint32_t remaining = 0;
};
class Engine {
    struct Slot {
        bool used = false;
        uint32_t id = 0;
        HandState state;
    };
    Config config_;
    std::array<Slot, 2> slots_{};
    bool seen_ = false, valid_seen_ = false;
    uint64_t frame_ = 0;
    uint32_t stamp_ = 0, last_valid_ = 0, candidate_at_ = 0;
    uint8_t raw_ = 0, stable_ = 0, candidate_ = 0, candidate_mask_ = 0, stable_mask_ = 0;
    unsigned confirms_ = 0;
    void Stop(bool preserve = false) {
        raw_ = stable_ = candidate_ = candidate_mask_ = stable_mask_ = 0;
        confirms_ = 0;
        valid_seen_ = false;
        for (auto& s : slots_) {
            if (preserve) {
                s.state.has_completed = false;
                s.state.active_until = 0;
            } else
                s = {};
        }
    }

public:
    explicit Engine(Config c = {}) : config_(c) {}
    void Reset() {
        Stop();
        seen_ = false;
        frame_ = 0;
    }
    void Calibrate(Side side, int sign) {
        if (side == Side::Left)
            config_.back_sign[0] = sign;
        if (side == Side::Right)
            config_.back_sign[1] = sign;
        Stop();
    }
    Result Snapshot(uint32_t now) {
        if (seen_ && (int32_t(now - stamp_) < 0 || uint32_t(now - stamp_) >= config_.lost_ms))
            Stop();
        else if (valid_seen_ && uint32_t(now - last_valid_) >= config_.lost_ms)
            Stop(true);
        return {raw_, stable_, confirms_,
                stable_ && valid_seen_ ? config_.lost_ms - uint32_t(now - last_valid_) : 0};
    }
    void Process(const Frame& f, uint32_t now) {
        Snapshot(now);
        if (!f.valid || !f.model_ready || int32_t(now - f.captured_ms) < 0 ||
            uint32_t(now - f.captured_ms) >= config_.lost_ms) {
            Stop();
            return;
        }
        if (seen_ && f.id <= frame_)
            return;
        if (seen_ && int32_t(f.captured_ms - stamp_) <= 0) {
            Stop();
            return;
        }
        if (seen_ && uint32_t(f.captured_ms - stamp_) >= config_.lost_ms)
            Stop();
        seen_ = true;
        frame_ = f.id;
        stamp_ = f.captured_ms;
        uint8_t mask = 0, choices = 0;
        bool conflict = false;
        std::array<uint32_t, 2> ids{};
        for (int i = 0; i < f.hand_count && i < 2; i++)
            ids[i] = f.hands[i].id;
        for (int j = 0; j < 2; j++)
            if (slots_[j].used && std::find(ids.begin(), ids.end(), slots_[j].id) == ids.end()) {
                slots_[j] = {};
                candidate_mask_ &= ~(1u << j);
                stable_mask_ &= ~(1u << j);
                if (!candidate_mask_) {
                    candidate_ = 0;
                    confirms_ = 0;
                }
                if (!stable_mask_)
                    stable_ = 0;
            }
        for (int i = 0; i < f.hand_count && i < 2; i++) {
            const auto& h = f.hands[i];
            Features features;
            Slot* slot = nullptr;
            for (auto& s : slots_)
                if (s.used && s.id == h.id)
                    slot = &s;
            if (!Extract(h, f.width, f.height, features)) {
                if (slot) {
                    int j = int(slot - slots_.data());
                    *slot = {};
                    candidate_mask_ &= ~(1u << j);
                    stable_mask_ &= ~(1u << j);
                    if (!candidate_mask_) {
                        candidate_ = 0;
                        confirms_ = 0;
                    }
                    if (!stable_mask_)
                        stable_ = 0;
                }
                continue;
            }
            if (!slot)
                for (auto& s : slots_)
                    if (!s.used) {
                        s.used = true;
                        s.id = h.id;
                        slot = &s;
                        break;
                    }
            if (!slot) {
                conflict = true;
                continue;
            }
            uint8_t choice = slot->state.Classify(features, h.side, stamp_, config_);
            if (choice && (choice & (choice - 1)))
                conflict = true;
            choices |= choice;
            if (choice)
                mask |= 1u << int(slot - slots_.data());
        }
        if (conflict || (choices && (choices & (choices - 1)))) {
            Stop();
            return;
        }
        raw_ = choices == 1 ? 1 : choices == 2 ? 2 : choices == 4 ? 3 : 0;
        if (!raw_) {
            candidate_ = candidate_mask_ = 0;
            confirms_ = 0;
            return;
        }
        last_valid_ = stamp_;
        valid_seen_ = true;
        if (raw_ == 2) {
            uint32_t latest = 0;
            bool found = false;
            for (auto& s : slots_)
                if (s.used && s.state.has_completed) {
                    uint32_t at = s.state.active_until - config_.lost_ms;
                    if (!found || int32_t(at - latest) > 0)
                        latest = at;
                    found = true;
                }
            last_valid_ = latest;
            stable_ = candidate_ = 2;
            return;
        }
        if (stable_ && (stable_ != raw_ || !(stable_mask_ & mask)))
            stable_ = 0;
        uint8_t continuing = candidate_mask_ & mask;
        if (candidate_ != raw_ || !continuing) {
            candidate_ = raw_;
            candidate_at_ = stamp_;
            confirms_ = 1;
            candidate_mask_ = mask;
        } else {
            confirms_++;
            candidate_mask_ = continuing;
        }
        if (confirms_ >= config_.confirm_frames &&
            uint32_t(stamp_ - candidate_at_) >= config_.confirm_ms) {
            stable_ = raw_;
            stable_mask_ = candidate_mask_;
        }
    }
};
// Native vision IDs only group one frame. Match wrists/side across adjacent frames.
class Tracker {
    struct Track {
        bool used = false;
        uint32_t id = 0, last = 0;
        Point wrist;
        Side side;
    };
    std::array<Track, 2> tracks_{};
    uint32_t next_ = 0;

public:
    void Reset() { tracks_ = {}; }
    bool Assign(Frame& f) {
        std::array<bool, 2> assigned{};
        for (auto& t : tracks_)
            if (t.used && uint32_t(f.captured_ms - t.last) >= 800)
                t = {};
        for (int i = 0; i < f.hand_count && i < 2; i++) {
            auto& h = f.hands[i];
            int best = -1;
            float distance = .3f;
            for (int j = 0; j < 2; j++)
                if (tracks_[j].used && !assigned[j] &&
                    (h.side == Side::Unknown || tracks_[j].side == h.side)) {
                    float d = Distance(h.points[0], tracks_[j].wrist, true);
                    if (d < distance) {
                        distance = d;
                        best = j;
                    }
                }
            if (best < 0)
                for (int j = 0; j < 2; j++)
                    if (!tracks_[j].used && !assigned[j]) {
                        best = j;
                        break;
                    }
            if (best < 0) {
                Reset();
                return false;
            }
            auto& t = tracks_[best];
            if (!t.used)
                t.id = ++next_;
            t.used = true;
            t.last = f.captured_ms;
            t.wrist = h.points[0];
            t.side = h.side;
            h.id = t.id;
            assigned[best] = true;
        }
        for (int j = 0; j < 2; j++)
            if (!assigned[j])
                tracks_[j] = {};
        return true;
    }
};
}  // namespace onboard
