#pragma once
#include <cJSON.h>
#include <cmath>
#include <cstring>
#include "onboard_landmarks.h"
namespace onboard {
enum class DecodeResult { Ignore, Frame, Invalid };
class Decoder {
    uint32_t session_ = 0, remote_frame_ = 0, remote_base_ = 0, local_base_ = 0, last_capture_ = 0;
    uint64_t local_frame_ = 0;
    bool seen_ = false, anchored_ = false;
    static bool UInt(cJSON* o, const char* key, uint32_t& value) {
        auto* x = cJSON_GetObjectItemCaseSensitive(o, key);
        if (!cJSON_IsNumber(x) || !std::isfinite(x->valuedouble) || x->valuedouble < 0 ||
            x->valuedouble > UINT32_MAX || std::floor(x->valuedouble) != x->valuedouble)
            return false;
        value = uint32_t(x->valuedouble);
        return true;
    }
    static bool Flag(cJSON* o, const char* key, bool& out) {
        auto* x = cJSON_GetObjectItemCaseSensitive(o, key);
        if (!cJSON_IsBool(x))
            return false;
        out = cJSON_IsTrue(x);
        return true;
    }
    static bool Points(cJSON* a, std::array<Point, 21>& out) {
        if (!cJSON_IsArray(a) || cJSON_GetArraySize(a) != 21)
            return false;
        for (int i = 0; i < 21; i++) {
            auto* p = cJSON_GetArrayItem(a, i);
            if (!cJSON_IsArray(p) || cJSON_GetArraySize(p) != 3)
                return false;
            float xyz[3];
            for (int j = 0; j < 3; j++) {
                auto* v = cJSON_GetArrayItem(p, j);
                if (!cJSON_IsNumber(v) || !std::isfinite(v->valuedouble) ||
                    std::fabs(v->valuedouble) > 100)
                    return false;
                xyz[j] = v->valuedouble;
            }
            out[i] = {xyz[0], xyz[1], xyz[2]};
        }
        return true;
    }

public:
    void Begin(uint32_t session) {
        session_ = session;
        seen_ = false;
        anchored_ = false;
    }
    bool AnchorFromAck(cJSON* root, uint32_t request_started) {
        auto* name = cJSON_GetObjectItemCaseSensitive(root, "name");
        auto* data = cJSON_GetObjectItemCaseSensitive(root, "data");
        uint32_t type, code, version, session, remote_now;
        if (anchored_ || !cJSON_IsString(name) || std::strcmp(name->valuestring, "HANDS") ||
            !UInt(root, "type", type) || type != 0 || !UInt(root, "code", code) || code != 0 ||
            !UInt(data, "version", version) || version != 1 || !UInt(data, "session", session) ||
            session != session_ || !UInt(data, "now_ms", remote_now))
            return false;
        // The remote ACK is generated after request transmission. Mapping it to the
        // local request start charges the complete round trip against frame age.
        remote_base_ = remote_now;
        local_base_ = request_started;
        anchored_ = true;
        return true;
    }
    DecodeResult Decode(cJSON* root, uint32_t received, Frame& out) {
        auto* name = cJSON_GetObjectItemCaseSensitive(root, "name");
        if (!cJSON_IsString(name) || std::strcmp(name->valuestring, "HANDS"))
            return DecodeResult::Ignore;
        out = {};
        out.error = "invalid_landmark_message";
        uint32_t type, code;
        if (!UInt(root, "type", type) || !UInt(root, "code", code) || code != 0)
            return DecodeResult::Invalid;
        if (type == 0)
            return DecodeResult::Ignore;
        if (type != 1)
            return DecodeResult::Invalid;
        auto* data = cJSON_GetObjectItemCaseSensitive(root, "data");
        uint32_t version, session, frame, capture, infer, w, h;
        bool mirrored;
        if (!UInt(data, "session", session))
            return DecodeResult::Invalid;
        if (session != session_ || !anchored_)
            return DecodeResult::Ignore;
        if (!UInt(data, "version", version) || version != 1 || !UInt(data, "frame_id", frame) ||
            !frame || !UInt(data, "capture_ms", capture) || !UInt(data, "inference_ms", infer) ||
            !UInt(data, "width", w) || w < 32 || w > 4096 ||
            !UInt(data, "height", h) || h < 32 || h > 4096 || !Flag(data, "mirrored", mirrored) ||
            mirrored || !Flag(data, "model_ready", out.model_ready) ||
            !Flag(data, "calibrated", out.calibrated) || !Flag(data, "valid", out.valid))
            return DecodeResult::Invalid;
        if (infer >= 800) {
            out.error = "landmark_inference_expired";
            return DecodeResult::Invalid;
        }
        if (seen_ && frame <= remote_frame_)
            return DecodeResult::Ignore;
        if (seen_ && int32_t(capture - last_capture_) <= 0)
            return DecodeResult::Invalid;
        auto* model = cJSON_GetObjectItemCaseSensitive(data, "model");
        auto* error = cJSON_GetObjectItemCaseSensitive(data, "error");
        if (!cJSON_IsString(model) || !model->valuestring[0] ||
            std::strlen(model->valuestring) > 96)
            return DecodeResult::Invalid;
        out.model = model->valuestring;
        out.error = cJSON_IsString(error) ? std::string(error->valuestring).substr(0, 96) : "";
        auto* hands = cJSON_GetObjectItemCaseSensitive(data, "hands");
        if (!cJSON_IsArray(hands) || cJSON_GetArraySize(hands) > 2)
            return DecodeResult::Invalid;
        out.hand_count = cJSON_GetArraySize(hands);
        for (int i = 0; i < out.hand_count; i++) {
            auto* hand = cJSON_GetArrayItem(hands, i);
            auto& dst = out.hands[i];
            auto* side = cJSON_GetObjectItemCaseSensitive(hand, "handedness");
            auto* presence = cJSON_GetObjectItemCaseSensitive(hand, "presence");
            if (!UInt(hand, "id", dst.id) || !cJSON_IsString(side) || !cJSON_IsNumber(presence) ||
                !std::isfinite(presence->valuedouble) || presence->valuedouble < 0 ||
                presence->valuedouble > 1 ||
                !Points(cJSON_GetObjectItemCaseSensitive(hand, "landmarks"), dst.points))
                return DecodeResult::Invalid;
            dst.presence = presence->valuedouble;
            dst.side = !std::strcmp(side->valuestring, "left")    ? Side::Left
                       : !std::strcmp(side->valuestring, "right") ? Side::Right
                                                                  : Side::Unknown;
            auto* world = cJSON_GetObjectItemCaseSensitive(hand, "world_landmarks");
            if (world && !cJSON_IsNull(world)) {
                if (!Points(world, dst.world))
                    return DecodeResult::Invalid;
                dst.has_world = true;
            }
            if (i && dst.id == out.hands[0].id)
                return DecodeResult::Invalid;
        }
        uint32_t local_capture = local_base_ + uint32_t(capture - remote_base_);
        // A fixed per-session clock bridge preserves queue age. Repeated/slow replies
        // never rebase the clock and cannot make old capture timestamps look fresh.
        if (int32_t(received - local_capture) < 0) {
            out.error = "landmark_frame_future";
            return DecodeResult::Invalid;
        }
        if (uint32_t(received - local_capture) >= 800) {
            out.error = "landmark_frame_stale";
            return DecodeResult::Invalid;
        }
        seen_ = true;
        remote_frame_ = frame;
        last_capture_ = capture;
        out.id = ++local_frame_;
        out.captured_ms = local_capture;
        out.width = w;
        out.height = h;
        return DecodeResult::Frame;
    }
};
}  // namespace onboard
