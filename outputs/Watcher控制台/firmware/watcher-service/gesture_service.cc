#include "gesture_service.h"
#include <esp_mac.h>
#include <esp_netif.h>
#include <esp_timer.h>
#include <esp_wifi.h>
#include <esp_system.h>
#include <esp_heap_caps.h>
#include "wifi_frame_decoder.h"
#if __has_include("mdns.h")
#include <mdns.h>
#define GESTURE_MDNS_AVAILABLE 1
#endif
#include <cJSON.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <lwip/sockets.h>
#include <strings.h>
#include <unistd.h>
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include "application.h"
#include "board.h"
#include "display/display.h"
#include "display_receipt.h"
#include "gesture_face.h"
#include "gesture_status_text.h"
#include "settings.h"
#include "stop_protocol.h"
#include "servo_test_tail.h"
#include "arm_stop_barrier.h"
#include "camera_source_switch.h"
#include "mode_lease_tail.h"
namespace {
uint32_t Now() { return esp_timer_get_time() / 1000; }
const char* Label(uint8_t m) {
    return m == 1 ? "pounding" : m == 2 ? "kneading" : m == 3 ? "pinch" : "stop";
}
const char* Reason(uint8_t n) {
    return n == 1   ? "command"
           : n == 2 ? "stop"
           : n == 3 ? "lease_expired"
           : n == 4 ? "link_lost"
           : n == 5 ? "arm_changed"
           : n == 6 ? "calibration_test"
                    : n == 8 ? "late_deadline"
                    : "profile_changed";
}
void Network() {
    while (!esp_netif_get_handle_from_ifkey("WIFI_STA_DEF"))
        vTaskDelay(pdMS_TO_TICKS(200));
    esp_netif_ip_info_t ip{};
    while (esp_netif_get_ip_info(esp_netif_get_handle_from_ifkey("WIFI_STA_DEF"), &ip) != ESP_OK ||
           !ip.ip.addr)
        vTaskDelay(pdMS_TO_TICKS(200));
}
int Listener(int port) {
    int fd = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
    if (fd < 0)
        return -1;
    int yes = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_port = htons(port);
    a.sin_addr.s_addr = htonl(INADDR_ANY);
    if (bind(fd, (sockaddr*)&a, sizeof(a)) < 0 || listen(fd, 3) < 0) {
        close(fd);
        return -1;
    }
    return fd;
}
void Timeout(int fd, int ms) {
    // Camera headers and control lines are latency-sensitive, not bulk batches.
    int no_delay = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &no_delay, sizeof(no_delay));
    timeval t{ms / 1000, (ms % 1000) * 1000};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &t, sizeof(t));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &t, sizeof(t));
}
bool Send(int fd, const std::string& s) {
    size_t at = 0;
    while (at < s.size()) {
        int n = send(fd, s.data() + at, s.size() - at, 0);
        if (n <= 0)
            return false;
        at += n;
    }
    return true;
}
bool SendControlNow(int fd, const char* line) {
    const size_t size = strlen(line);
    // Control records fit in a single tiny write. Never wait for socket space
    // while holding the admission lock; a partial/would-block write drops link.
    return send(fd, line, size, MSG_DONTWAIT) == int(size);
}
void Reply(int fd, int code, const std::string& body) {
    Send(fd, "HTTP/1.1 " + std::to_string(code) + (code == 200 ? " OK" : " Error") +
                 "\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: " +
                 std::to_string(body.size()) + "\r\n\r\n" + body);
}
bool Number(cJSON* o, const char* key, int low, int high, int& value) {
    auto* x = cJSON_GetObjectItemCaseSensitive(o, key);
    if (!cJSON_IsNumber(x) || x->valuedouble != x->valueint || x->valueint < low ||
        x->valueint > high)
        return false;
    value = x->valueint;
    return true;
}
void ProfileJson(cJSON* o, const ServoProfile& p) {
    auto* a = cJSON_AddArrayToObject(o, "neutral_us");
    auto* b = cJSON_AddArrayToObject(o, "run_us");
    for (int i = 0; i < 3; ++i) {
        cJSON_AddItemToArray(a, cJSON_CreateNumber(p.neutral[i]));
        cJSON_AddItemToArray(b, cJSON_CreateNumber(p.run[i]));
    }
    cJSON_AddNumberToObject(o, "id", p.Id());
}
}  // namespace
GestureService& GestureService::Instance() {
    static GestureService s;
    return s;
}
void GestureService::Start(bool ready) {
    owner_.Switch("camera");
    model_ready_ = false;  // Class-label/RPS readiness never implies 21 landmarks.
    uint8_t mac[6] = {};
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    char device[32];
    snprintf(device, sizeof(device), "watcher-%02x%02x%02x%02x%02x%02x", mac[0], mac[1], mac[2],
             mac[3], mac[4], mac[5]);
    watcher_id_ = device;
    Settings saved("gesture_servo");
    auto text = saved.GetString("profile");
    uint32_t v[6];
    if (ReadControlNumbers(text.c_str(), "", v, 6)) {
        ServoProfile p;
        bool range = true;
        for (int i = 0; i < 3; ++i) {
            range = range && v[i] <= 65535 && v[i + 3] <= 65535;
            p.neutral[i] = v[i];
            p.run[i] = v[i + 3];
        }
        if (range && p.Valid()) {
            p.MigrateLegacyDefault(saved.GetInt("version", 0));
            profile_ = p;
            requested_.Configure(p);
        }
    }
    {
        Settings migrated("gesture_servo", true);
        char text[96];
        snprintf(text, sizeof(text), "%u %u %u %u %u %u", profile_.neutral[0], profile_.neutral[1],
                 profile_.neutral[2], profile_.run[0], profile_.run[1], profile_.run[2]);
        migrated.SetString("profile", text);
        migrated.SetInt("version", kServoProfileVersion);
        for (int i = 0; i < 2; i++) {
            int sign = migrated.GetInt(i ? "back_right" : "back_left", 0);
            if (sign >= -1 && sign <= 1)
                engine_.Calibrate(i ? onboard::Side::Right : onboard::Side::Left, sign);
        }
    }
    xTaskCreate([](void* p) { static_cast<GestureService*>(p)->RulesLoop(); }, "hand_rules", 6144,
                this, 2, nullptr);
    xTaskCreate(
        [](void* p) {
            ((GestureService*)p)->Serve();
            vTaskDelete(nullptr);
        },
        "control_tcp", 7168, this, 2, nullptr);
    xTaskCreate(
        [](void* p) {
            ((GestureService*)p)->HttpServe();
            vTaskDelete(nullptr);
        },
        "control_http", 7168, this, 2, nullptr);
    xTaskCreate([](void* p) { static_cast<GestureService*>(p)->CameraHttpServe(); }, "camera_http",
                6144, this, 1, nullptr);
    xTaskCreate(
        [](void* p) {
            ((GestureService*)p)->DisplayLoop();
            vTaskDelete(nullptr);
        },
        "control_face", 4096, this, 1, nullptr);
}
void GestureService::Submit(const char*, int) {}
void GestureService::SubmitLandmarks(const onboard::Frame& frame) {
    std::lock_guard<std::mutex> l(mutex_);
    if (!power_.Active()) return;
    // Only one latest observation is retained; no inference backlog can renew a lease.
    latest_ = frame;
    frame_pending_ = true;
}
void GestureService::StopLocked(const char* reason, bool disarm) {
    ++intent_sequence_;
    requested_.Disconnect();
    hold_.Cancel();
    test_active_ = false;
    if (disarm) {
        ++stop_generation_;
        wanted_arm_ = false;
    }
    stop_reason_ = reason;
}
void GestureService::StopDisarm(const char* reason) {
    std::lock_guard<std::mutex> l(mutex_);
    const bool neutral_only = !strcmp(reason, "explicit_stop") || !strcmp(reason, "button_stop");
    StopLocked(reason, !neutral_only);
    if (neutral_only) {
        ++stop_generation_;
        armed_at_ms_ = Now();
        hold_.ArmEpoch(armed_at_ms_);
    } else {
        hold_.Reset();
        camera_observation_version_ = 0;
    }
    if (!strcmp(reason, "shutdown") || !strcmp(reason, "button_long_hold"))
        continuous_output_.SetEnabled(false);
    if (!strcmp(reason, "shutdown"))
        shutting_down_ = true;
    engine_.Reset();
    recognition_ = {};
}
bool GestureService::ArmFromButton() {
    std::lock_guard<std::mutex> l(mutex_);
    bool ready = !shutting_down_ && capable_ && client_hold_protocol_ == 2 &&
                 clock_.Fresh(Now()) && client_connected_ && profile_match_ &&
                 !arm_in_flight_ &&
                 (input_source_ != "onboard" ||
                  (model_ready_ && vision_calibrated_ && local_capture_.Seen() &&
                   uint32_t(Now() - local_capture_.Captured()) < 800)) &&
                 (input_source_ != "camera" ||
                  (camera_frame_ && uint32_t(Now() - camera_frame_->captured) < 800 &&
                   camera_observation_version_ == 2 && hold_.Healthy(Now())));
    StopLocked(ready ? "button_arm" : "button_arm_not_ready", false);
    continuous_output_.SetEnabled(true);
    wanted_arm_ = ready;
    return ready;
}
bool GestureService::SafeToShutdown() {
    std::lock_guard<std::mutex> l(mutex_);
    return ShutdownReady(outputs_enabled_, wanted_arm_, arm_in_flight_, motion_possible_,
                         possible_motion_until_, Now());
}
bool GestureService::BeginPowerStop() {
    std::lock_guard<std::mutex> l(mutex_);
    if (!power_.BeginShutdown()) return false;
    // Preserve the user's continuous-output preference while stopping admission.
    shutting_down_ = true;
    power_released_ = false;
    StopLocked("power_hold", true);
    hold_.Reset(); clock_.Reset(); camera_observation_version_ = 0;
    camera_frame_.reset(); camera_session_ = 0; camera_power_epoch_ = 0;
    camera_ledger_.Begin(0); camera_error_ = "power_standby";
    engine_.Reset(); tracker_.Reset(); recognition_ = {};
    latest_ = {}; observed_ = {}; frame_pending_ = false;
    local_capture_ = {}; armed_at_ms_ = 0;
    return true;
}
void GestureService::MarkPowerReleased() {
    std::lock_guard<std::mutex> l(mutex_);
    power_released_ = true;
}
void GestureService::EnterStandby() {
    std::lock_guard<std::mutex> l(mutex_);
    power_.Standby();
}
bool GestureService::ResumePower() {
    std::lock_guard<std::mutex> l(mutex_);
    if (!power_.Resume()) return false;
    StopLocked("power_resume", true);
    shutting_down_ = false;
    power_released_ = false;
    // The next capture owns a new session. Neither old frames nor receipts may arm.
    hold_.Reset(); clock_.Reset(); camera_observation_version_ = 0;
    camera_frame_.reset(); camera_session_ = 0; camera_power_epoch_ = 0;
    camera_ledger_.Begin(0); camera_error_ = "awaiting_camera_frame";
    engine_.Reset(); tracker_.Reset(); recognition_ = {};
    latest_ = {}; observed_ = {}; frame_pending_ = false;
    local_capture_ = {}; armed_at_ms_ = 0;
    display_page_ = GestureDisplayPage::Expression;
    return true;
}
bool GestureService::CaptureAllowed() {
    std::lock_guard<std::mutex> l(mutex_);
    return power_.Active();
}
uint32_t GestureService::CaptureEpoch() {
    std::lock_guard<std::mutex> l(mutex_);
    return power_.Epoch();
}
GesturePowerState GestureService::PowerState() {
    std::lock_guard<std::mutex> l(mutex_);
    return power_.State();
}
void GestureService::RotatePage(bool clockwise, bool pressed) {
    std::lock_guard<std::mutex> l(mutex_);
    display_page_ = RotatedPage(display_page_, clockwise, pressed, power_.State());
}
DisplaySnapshot GestureService::DisplayState() {
    std::lock_guard<std::mutex> l(mutex_);
    const uint32_t now = Now();
    requested_.Tick(now);
    DisplaySnapshot s;
    s.page = display_page_; s.power = power_.State();
    s.mode = input_source_ == "camera" && camera_observation_version_ == 2 ? hold_.Face(now) : requested_.Mode();
    s.connected = client_connected_;
    s.output_preference = continuous_output_.Enabled();
    s.camera_fresh = power_.Active() && (input_source_ == "camera" ?
        camera_frame_ && uint32_t(now - camera_frame_->captured) < 800 :
        input_source_ == "onboard" && local_capture_.Seen() && uint32_t(now - local_capture_.Captured()) < 800);
    s.recognition_fresh = power_.Active() && (input_source_ == "camera" ?
        camera_observation_version_ == 2 && hold_.Healthy(now) :
        input_source_ == "simulation" || (model_ready_ && vision_calibrated_ && s.camera_fresh));
    s.pulse_fresh = client_connected_ && last_ack_ms_ && uint32_t(now - last_ack_ms_) < 600;
    s.servo_ready = power_.Active() && outputs_enabled_ && wanted_arm_ && profile_match_ &&
        capable_ && client_hold_protocol_ == 2 && clock_.Fresh(now) && s.pulse_fresh;
    uint16_t expected[3] = {requested_.Pulse(0), requested_.Pulse(1), requested_.Pulse(2)};
    s.pending = FaceNeedsReceipt(requested_.Mode(), wanted_arm_, outputs_enabled_) &&
        (!s.servo_ready || !HasCurrentServoReceipt(s.mode, intent_sequence_, applied_intent_,
            applied_mode_, expected, pulse_us_, last_ack_ms_, now));
    s.hold_remaining_ms = input_source_ == "camera" && camera_observation_version_ == 2 ?
        hold_.FaceRemaining(now) : requested_.Remaining(now);
    for (int i = 0; i < 3; ++i) s.pulses_us[i] = pulse_us_[i];
    s.board_ip = client_ip_;
    if (s.power == GesturePowerState::ShuttingDown) s.power_prompt = power_released_ ? "正在关闭" : "松开滚轮后关机";
    return s;
}
bool GestureService::SwitchSource(const std::string& source, uint32_t* accepted_stop_generation,
                                  uint32_t power_epoch) {
    std::lock_guard<std::mutex> l(mutex_);
    const bool previous_camera = input_source_ == "camera";
    if (!power_.Active() || (power_epoch && !power_.Accept(power_epoch)) || !owner_.Switch(source))
        return false;
    StopLocked("source_changed", true);
    engine_.Reset();
    tracker_.Reset();
    recognition_ = {};
    input_source_ = source;
    if (accepted_stop_generation)
        *accepted_stop_generation = stop_generation_;
    ResetCameraCaptureOnSourceSwitch(previous_camera, source == "camera", camera_session_,
                                    camera_ledger_, camera_frame_, camera_error_);
    hold_.Reset(); camera_observation_version_ = 0;
    return true;
}
bool GestureService::CameraActive() {
    std::lock_guard<std::mutex> l(mutex_);
    if (!power_.Active()) return false;
    return input_source_ == "onboard"
               ? local_capture_.Seen() && uint32_t(Now() - local_capture_.Captured()) < 800
               : input_source_ == "camera" && camera_frame_ &&
                     uint32_t(Now() - camera_frame_->captured) < 800;
}
std::string GestureService::InputSource() {
    std::lock_guard<std::mutex> l(mutex_);
    return power_.Active() ? input_source_ : "standby";
}
void GestureService::BeginCamera(uint32_t session) {
    std::lock_guard<std::mutex> l(mutex_);
    if (!power_.Active() || !owner_.Accept("camera"))
        return;
    StopLocked("camera_session_changed",
               CameraSessionNeedsDisarm(camera_session_, wanted_arm_, outputs_enabled_));
    camera_session_ = session;
    camera_power_epoch_ = power_.Epoch();
    camera_ledger_.Begin(session);
    hold_.Reset(); camera_observation_version_ = 0;
    camera_frame_.reset();
    camera_error_ = "awaiting_camera_frame";
}
bool GestureService::SubmitCamera(std::shared_ptr<const wifi_camera::Frame> frame) {
    std::lock_guard<std::mutex> l(mutex_);
    if (!power_.Active() || !power_.Accept(camera_power_epoch_) || !frame || !owner_.Accept("camera") ||
        !camera_ledger_.Record(frame->session, frame->id, frame->captured, Now()))
        return false;
    camera_frame_ = std::move(frame);
    camera_error_.clear();
    ++camera_frames_;
    return true;
}
void GestureService::CameraFault(const char* reason) {
    std::lock_guard<std::mutex> l(mutex_);
    if (!power_.Active() || !owner_.Accept("camera"))
        return;
    camera_error_ = reason;
    camera_frame_.reset();
    camera_ledger_.Begin(0);
    StopLocked(reason, true);
    hold_.Reset(); camera_observation_version_ = 0;
}
void GestureService::RulesLoop() {
#ifdef GESTURE_MDNS_AVAILABLE
    std::string advertised_model;
    bool advertised_ready = false;
#endif
    while (true) {
#ifdef GESTURE_MDNS_AVAILABLE
        std::string next_model;
        bool next_ready = false, advertise = false;
#endif
        {
            std::unique_lock<std::mutex> l(mutex_);
            uint32_t now = Now();
            if (!power_.Active()) {
                frame_pending_ = false;
                l.unlock();
                vTaskDelay(pdMS_TO_TICKS(20));
                continue;
            }
            if (frame_pending_) {
                onboard::Frame frame = std::move(latest_);
                frame_pending_ = false;
                model_name_ = frame.model;
                model_error_ = frame.error;
                model_ready_ = frame.model_ready;
                vision_calibrated_ = frame.calibrated;
                if (local_capture_.Apply(frame.valid, frame.model_ready, frame.id,
                                         frame.captured_ms, now)) {
                    ++frames_;
                    ++fps_window_frames_;
                    if (!fps_window_ms_)
                        fps_window_ms_ = now;
                    if (uint32_t(now - fps_window_ms_) >= 1000) {
                        inference_fps_ = fps_window_frames_ * 1000.f / (now - fps_window_ms_);
                        fps_window_frames_ = 0;
                        fps_window_ms_ = now;
                    }
                    if (owner_.Accept("onboard")) {
                        if (!tracker_.Assign(frame)) {
                            engine_.Reset();
                            model_error_ = "ambiguous_hand_identity";
                        } else
                            engine_.Process(frame, now);
                        observed_ = std::move(frame);
                    }
                } else if (!frame.valid || !frame.model_ready) {
                    if (owner_.Accept("onboard")) {
                        engine_.Reset();
                        StopLocked("vision_not_ready", true);
                    }
                }
            }
#ifdef GESTURE_MDNS_AVAILABLE
            next_model = model_name_;
            next_ready = model_ready_ && vision_calibrated_ && local_capture_.Seen() &&
                         uint32_t(now - local_capture_.Captured()) < 800 &&
                         owner_.Accept("onboard");
            advertise = mdns_ready_;
#endif
            if (owner_.Accept("camera")) {
                const bool capture_ok = camera_frame_ && uint32_t(now - camera_frame_->captured) < 800;
                if (!capture_ok && (wanted_arm_ || requested_.Mode() || hold_.Face(now))) {
                    StopLocked("camera_frame_timeout", true);
                    hold_.Reset();
                } else if (camera_observation_version_ == 2) {
                    if (!hold_.Healthy(now) && (wanted_arm_ || requested_.Mode() || hold_.Face(now))) {
                        StopLocked("camera_result_timeout", true);
                        hold_.Reset();
                    } else {
                        uint8_t mode = hold_.Motion(now);
                        uint32_t rem = camera_frame_ ? hold_.MotionRemaining(now, camera_frame_->captured) : 0;
                        requested_.Tick(now);
                        if (requested_.Mode() != mode) {
                            ++intent_sequence_;
                            stop_reason_ = mode ? "" : hold_.Reason();
                        }
                        requested_.Apply({++input_sequence_, mode,
                            uint16_t(std::max<uint32_t>(100, std::min<uint32_t>(600, rem)))}, now);
                    }
                } else if (wanted_arm_) {
                    StopLocked("observation_protocol_required", true);
                }
            }
            if (owner_.Accept("onboard")) {
                recognition_ = engine_.Snapshot(now);
                if (!vision_calibrated_ && wanted_arm_)
                    StopLocked("vision_calibration_invalid", true);
                requested_.Tick(now);
                uint8_t mode = recognition_.stable;
                uint32_t remaining = recognition_.remaining;
                if (!model_ready_ || !local_capture_.Seen() ||
                    uint32_t(now - local_capture_.Captured()) >= 800) {
                    mode = 0;
                    remaining = 0;
                    if (wanted_arm_)
                        StopLocked("vision_frame_timeout", true);
                }
                if (requested_.Mode() != mode) {
                    ++intent_sequence_;
                    stop_reason_ = mode ? "" : "onboard_stop";
                }
                // The wire lease cannot outlive the original valid gesture (800 ms).
                requested_.Apply(
                    {++input_sequence_, remaining >= 100 ? mode : uint8_t(0),
                     uint16_t(remaining >= 100 ? std::min<uint32_t>(600, remaining) : 100)},
                    now);
            }
        }
#ifdef GESTURE_MDNS_AVAILABLE
        if (advertise && (next_model != advertised_model || next_ready != advertised_ready)) {
            if (mdns_service_txt_item_set("_watcher-servo", "_tcp", "model", next_model.c_str()) ==
                    ESP_OK &&
                mdns_service_txt_item_set("_watcher-servo", "_tcp", "ready",
                                          next_ready ? "1" : "0") == ESP_OK) {
                advertised_model = next_model;
                advertised_ready = next_ready;
            }
        }
#endif
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}
bool GestureService::SetInput(const std::string& label, const std::string& source, uint16_t lease,
                              uint32_t session, uint32_t frame, uint32_t age,
                              uint8_t observation_version, ObservationKind kind,
                              bool confirmed, bool hand, uint32_t confirmation_age, uint32_t power_epoch) {
    uint8_t m = label == "pounding" ? 1 : label == "kneading" ? 2 : label == "pinch" ? 3 : 0;
    if ((!m && label != "stop") || (source != "simulation" && source != "camera") || lease < 100 || lease > 600)
        return false;
    std::lock_guard<std::mutex> l(mutex_);
    if (!power_.Active() || (power_epoch && !power_.Accept(power_epoch)) || !owner_.Accept(source)) return false;
    uint32_t now = Now();
    if (source == "camera" && observation_version == 2) {
        // Validate shape before consuming proof; invalid bodies never renew health.
        GestureHold validator;
        if (!validator.Observe(now, m, kind, confirmed, hand, confirmation_age, now)) return false;
        uint32_t captured;
        if (!camera_ledger_.Observe(session, frame, age, now, captured) ||
            !hold_.Observe(captured, m, kind, confirmed, hand, confirmation_age, now)) return false;
        camera_observation_version_ = 2;
        if (kind == ObservationKind::Error) {
            StopLocked("recognition_error", true); hold_.Reset(); return true;
        }
        uint8_t mode = hold_.Motion(now);
        if (test_active_ || requested_.Mode() != mode) ++intent_sequence_;
        test_active_ = false;
        stop_reason_ = mode ? "" : hold_.Reason();
        return requested_.Apply({++input_sequence_, mode, 600}, now);
    }
    if (source == "camera") {
        // Legacy observations are preview only and cannot coexist with armed v2 state.
        if (wanted_arm_ || outputs_enabled_ || camera_observation_version_ == 2) return false;
        if (!camera_ledger_.Consume(session, frame, age, lease, now, lease)) return false;
        camera_observation_version_ = 0;
    }
    requested_.Tick(now);
    if (test_active_ || requested_.Mode() != m) ++intent_sequence_;
    test_active_ = false;
    stop_reason_ = m ? "" : "input_stop";
    return requested_.Apply({++input_sequence_, m, lease}, now);
}
bool GestureService::Event(const char* line) {
    uint32_t v[13];
    if (!ReadControlNumbers(line, "EVENT ", v, 13) || v[2] < 1 || v[2] > 8 || v[3] > 3 ||
        v[8] > 1 || v[9] > 7 || v[10] != 5 || v[11] != 4 || v[12] != 0)
        return false;
    for (int i = 4; i < 7; ++i)
        if (v[i] < 1000 || v[i] > 2000)
            return false;
    std::lock_guard<std::mutex> l(mutex_);
    if (last_event_ && v[0] <= last_event_)
        return true;
    last_event_ = v[0];
    events_.push_back({v[0],
                       v[1],
                       v[7],
                       connection_,
                       uint8_t(v[2]),
                       uint8_t(v[3]),
                       {uint16_t(v[4]), uint16_t(v[5]), uint16_t(v[6])},
                       bool(v[8]),
                       uint8_t(v[9]),
                       {uint8_t(v[10]), uint8_t(v[11]), uint8_t(v[12])}});
    if (events_.size() > 32)
        events_.pop_front();
    if (!v[8] && !v[3])
        stop_reason_ = Reason(v[2]);
    return true;
}
std::string GestureService::Status() {
    std::lock_guard<std::mutex> l(mutex_);
    uint32_t now = Now();
    requested_.Tick(now);
    auto* o = cJSON_CreateObject();
    auto str = [&](const char* k, const char* v) { cJSON_AddStringToObject(o, k, v); };
    auto num = [&](const char* k, double v) { cJSON_AddNumberToObject(o, k, v); };
    auto boolean = [&](const char* k, bool v) { cJSON_AddBoolToObject(o, k, v); };
    str("firmware", "watcher-servo-controller-v9-wheel");
    str("ui_revision", kGestureUiRevision);
    str("display_page", GesturePageName(display_page_));
    str("power_state", GesturePowerName(power_.State()));
    str("camera_driver_revision", "request-mutex-1");
    str("servo_test_revision", "neutral-tail-1");
    str("output_policy_revision", "continuous-enable-1");
    boolean("default_output_enabled", continuous_output_.Enabled());
    num("stop_generation", stop_generation_);
    num("uptime_ms", now);
    num("reset_reason", esp_reset_reason());
    num("heap_free_bytes", esp_get_free_heap_size());
    num("heap_min_free_bytes", esp_get_minimum_free_heap_size());
    num("internal_largest_free_bytes", heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
    num("psram_largest_free_bytes", heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM));
    num("http_task_stack_watermark", uxTaskGetStackHighWaterMark(nullptr));
    str("watcher_id", watcher_id_.c_str());
    boolean("mdns_ready", mdns_ready_);
    str("model", model_name_.c_str());
    str("model_error", model_error_.c_str());
    num("nodes_per_hand", model_ready_ ? 21 : 0);
    num("inference_fps", inference_fps_);
    str("raw_gesture", Label(recognition_.raw));
    num("confirm_frames", recognition_.confirms);
    boolean("model_ready", model_ready_);
    boolean("camera_external_capture", input_source_ == "camera");
    boolean("vision_calibrated", vision_calibrated_);
    boolean("standalone_ready", model_ready_ && vision_calibrated_ && input_source_ == "onboard" &&
                                    local_capture_.Seen() &&
                                    uint32_t(now - local_capture_.Captured()) < 800);
    str("recognition_location", input_source_ == "onboard"  ? "watcher"
                                : input_source_ == "camera" ? "mac"
                                                            : "simulation");
    str("camera_transport", input_source_ == "onboard"  ? "sscma_spi"
                            : input_source_ == "camera" ? "wifi_jpeg"
                                                        : "none");
    str("camera_error", camera_error_.c_str());
    str("camera_session_id", std::to_string(camera_session_).c_str());
    num("camera_frame_id", camera_frame_ ? camera_frame_->id : 0);
    num("camera_frames", camera_frames_);
    boolean("camera_result_active", camera_ledger_.ResultActive(now));
    num("camera_width", camera_frame_ ? camera_frame_->width : 0);
    num("camera_height", camera_frame_ ? camera_frame_->height : 0);
    boolean("display_preview", (camera_observation_version_ == 2 ? hold_.Face(now) : requested_.Mode()) && !wanted_arm_ && !outputs_enabled_);
    bool camera_active =
        input_source_ == "onboard"
            ? local_capture_.Seen() && uint32_t(now - local_capture_.Captured()) < 800
            : input_source_ == "camera" && camera_frame_ &&
                  uint32_t(now - camera_frame_->captured) < 800;
    boolean("camera_active", camera_active);
    num("camera_age_ms",
        input_source_ == "onboard"
            ? (local_capture_.Seen() ? uint32_t(now - local_capture_.Captured()) : 800)
        : camera_frame_ ? uint32_t(now - camera_frame_->captured)
                        : 800);
    auto state = Application::GetInstance().GetDeviceState();
    bool blue = state == kDeviceStateWifiConfiguring || state == kDeviceStateUpgrading;
    str("led_color", blue ? "blue" : camera_active ? "green" : "off");
    str("display_state", emotion_.c_str());
    boolean("display_animation", true);
    str("input_source", input_source_.c_str());
    const uint8_t presentation = input_source_ == "camera" && camera_observation_version_ == 2 ? hold_.Face(now) : requested_.Mode();
    str("held_gesture", Label(presentation));
    str("expression_gesture", Label(presentation));
    num("hold_remaining_ms", input_source_ == "camera" ? hold_.FaceRemaining(now) : requested_.Remaining(now));
    num("expression_remaining_ms", input_source_ == "camera" ? hold_.FaceRemaining(now) : requested_.Remaining(now));
    num("servo_hold_remaining_ms", input_source_ == "camera" && hold_.Motion(now) ? hold_.FaceRemaining(now) : 0);
    str("observation_state", ObservationLabel(hold_.Kind()));
    num("hold_event_id", hold_.Events());
    num("mac_observation_version", camera_observation_version_);
    num("camera_observation_version", camera_observation_version_);
    num("hold_protocol", client_hold_protocol_);
    num("armed_at_ms", armed_at_ms_);
    boolean("clock_fresh", clock_.Fresh(now));
    uint16_t expected[3] = {profile_.neutral[0], profile_.neutral[1], profile_.neutral[2]};
    if (requested_.Mode()) expected[requested_.Mode() - 1] = profile_.run[requested_.Mode() - 1];
    boolean("execution_pending", FaceNeedsReceipt(requested_.Mode(), wanted_arm_, outputs_enabled_) &&
        !HasCurrentServoReceipt(requested_.Mode(), intent_sequence_, applied_intent_, applied_mode_, expected, pulse_us_, last_ack_ms_, now));
    str("gesture", Label(requested_.Mode()));
    num("requested_mode", requested_.Mode());
    num("applied_mode", applied_mode_);
    str("emotion", emotion_.c_str());
    boolean("client_connected", client_connected_);
    boolean("outputs_enabled", outputs_enabled_);
    boolean("actuator_enabled", outputs_enabled_);
    boolean("output_capable", capable_);
    boolean("profile_match", profile_match_);
    str("output_type", "continuous_servo");
    str("client_ip", client_ip_.c_str());
    str("client_mac", client_mac_.c_str());
    str("client_firmware", client_hold_protocol_ == 2 ? "esp8266-servo-controller-v7" : "legacy-preview-only");
    str("last_peer", observed_peer_.c_str());
    num("last_command_seq", command_sequence_);
    num("last_applied_seq", last_applied_seq_);
    num("ack_successes", ack_count_);
    num("ack_latency_ms", ack_latency_);
    num("client_uptime_ms", client_uptime_);
    num("client_connection_id", connection_);
    str("last_stop_reason", stop_reason_.c_str());
    boolean("test_active", test_active_ && requested_.Remaining(now) >= 100);
    num("test_channel", test_channel_);
    if (last_applied_seq_)
        num("ack_age_ms", uint32_t(now - last_ack_ms_));
    else
        cJSON_AddNullToObject(o, "ack_age_ms");
    auto* pulses = cJSON_AddArrayToObject(o, "client_pulse_us");
    for (int i = 0; i < 3; ++i)
        cJSON_AddItemToArray(pulses, cJSON_CreateNumber(pulse_us_[i]));
    auto* pj = cJSON_AddObjectToObject(o, "servo_profile");
    ProfileJson(pj, profile_);
    auto* es = cJSON_AddArrayToObject(o, "output_events");
    for (const auto& e : events_) {
        auto* x = cJSON_CreateObject();
        cJSON_AddNumberToObject(x, "event_id", e.id);
        cJSON_AddNumberToObject(x, "sequence", e.sequence);
        cJSON_AddNumberToObject(x, "connection_id", e.connection);
        cJSON_AddStringToObject(x, "reason", Reason(e.reason));
        cJSON_AddNumberToObject(x, "mode", e.mode);
        cJSON_AddNumberToObject(x, "uptime_ms", e.uptime);
        cJSON_AddBoolToObject(x, "historical", e.historical);
        cJSON_AddNumberToObject(x, "attached_mask", e.attached_mask);
        auto* gp = cJSON_AddArrayToObject(x, "gpio");
        for (int i = 0; i < 3; i++)
            cJSON_AddItemToArray(gp, cJSON_CreateNumber(e.gpio[i]));
        auto* a = cJSON_AddArrayToObject(x, "pulse_us");
        for (int i = 0; i < 3; ++i)
            cJSON_AddItemToArray(a, cJSON_CreateNumber(e.pulse[i]));
        cJSON_AddItemToArray(es, x);
    }
    esp_netif_ip_info_t ip{};
    auto n = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    if (n && esp_netif_get_ip_info(n, &ip) == ESP_OK) {
        char a[16];
        snprintf(a, sizeof(a), IPSTR, IP2STR(&ip.ip));
        str("wifi_ip", a);
        str("camera_url", (std::string("http://") + a + ":8081/frame").c_str());
    }
    num("frames", input_source_ == "camera" ? camera_frames_ : frames_);
    num("capture_monotonic_ms", input_source_ == "camera" && camera_frame_
                                    ? camera_frame_->captured
                                    : local_capture_.Captured());
    num("frame_id",
        input_source_ == "camera" && camera_frame_ ? camera_frame_->id : local_capture_.Id());
    auto* hands = cJSON_AddArrayToObject(o, "hands");
    if (input_source_ == "onboard" && camera_active)
        for (int i = 0; i < observed_.hand_count; i++) {
            const auto& hand = observed_.hands[i];
            auto* h = cJSON_CreateObject();
            cJSON_AddNumberToObject(h, "id", hand.id);
            cJSON_AddStringToObject(h, "handedness",
                                    hand.side == onboard::Side::Left    ? "Left"
                                    : hand.side == onboard::Side::Right ? "Right"
                                                                        : "Unknown");
            auto* nodes = cJSON_AddArrayToObject(h, "landmarks");
            for (const auto& p : hand.points) {
                auto* xyz = cJSON_CreateArray();
                cJSON_AddItemToArray(xyz, cJSON_CreateNumber(p.x));
                cJSON_AddItemToArray(xyz, cJSON_CreateNumber(p.y));
                cJSON_AddItemToArray(xyz, cJSON_CreateNumber(p.z));
                cJSON_AddItemToArray(nodes, xyz);
            }
            cJSON_AddItemToArray(hands, h);
        }
    char* raw = cJSON_PrintUnformatted(o);
    std::string body = raw ? raw : "{}";
    cJSON_free(raw);
    cJSON_Delete(o);
    return body;
}
void GestureService::Serve() {
    Network();
    esp_wifi_set_ps(WIFI_PS_NONE);
#ifdef GESTURE_MDNS_AVAILABLE
    if (mdns_init() == ESP_OK) {
        mdns_hostname_set(watcher_id_.c_str());
        mdns_txt_item_t txt[] = {
            {"id", watcher_id_.c_str()}, {"protocol", "6"}, {"model", "unknown"}, {"ready", "0"}, {"hold_protocol", "2"}};
        bool ok = mdns_service_add("Watcher servo controller", "_watcher-servo", "_tcp", 8888, txt,
                                   5) == ESP_OK;
        std::lock_guard<std::mutex> l(mutex_);
        mdns_ready_ = ok;
    }
#endif
    int listener = -1;
    while (true) {
        if (listener < 0) {
            listener = Listener(8888);
            if (listener < 0) {
                vTaskDelay(pdMS_TO_TICKS(500));
                continue;
            }
        }
        sockaddr_in address{};
        socklen_t sz = sizeof(address);
        int fd = accept(listener, (sockaddr*)&address, &sz);
        if (fd < 0)
            continue;
        Timeout(fd, 250);
        StopLineParser parser;
        bool valid = false;
        char mac[18] = {}, ip[16] = {};
        unsigned cap = 0, version = 0;
        bool hold_protocol = false;
        unsigned long id = 0;
        uint32_t until = Now() + 1500;
        while ((int32_t)(until - Now()) > 0 && !valid) {
            char ch;
            if (recv(fd, &ch, 1, 0) <= 0)
                break;
            if (parser.Feed(ch)) {
                char capability[32] = {}, extra = 0;
                in_addr parsed{};
                int fields = sscanf(parser.Line(), "HELLO SERVO360 %17s %15s %u %lu %u %31s %c", mac, ip,
                               &cap, &id, &version, capability, &extra);
                hold_protocol = fields == 6 && !strcmp(capability, "hold_protocol=2");
                valid = (fields == 5 || hold_protocol) && cap <= 1 && version == 6 && strlen(mac) == 17 &&
                        inet_pton(AF_INET, ip, &parsed) == 1;
                break;
            }
        }
        if (!valid || !Send(fd, "WELCOME SERVO360 " + watcher_id_ + (hold_protocol ? " 6 hold_protocol=2\n" : " 6\n"))) {
            close(fd);
            continue;
        }
        if (hold_protocol) {
            bool ready = false;
            parser = StopLineParser();
            until = Now() + 1500;
            while (int32_t(until - Now()) > 0 && !ready) {
                char ch;
                if (recv(fd, &ch, 1, 0) <= 0) break;
                if (parser.Feed(ch)) ready = std::string(parser.Line()) == "READY SERVO360 " + watcher_id_ + " hold_protocol=2";
            }
            if (!ready) { close(fd); continue; }
        }
        {
            std::lock_guard<std::mutex> l(mutex_);
            client_connected_ = true;
            client_hold_protocol_ = hold_protocol ? 2 : 0;
            clock_.Reset(); hold_.Cancel(); armed_at_ms_ = 0;
            capable_ = cap;
            wanted_arm_ = outputs_enabled_ = false;
            profile_match_ = false;
            requested_.Disconnect();
            test_active_ = false;
            client_mac_ = mac;
            client_ip_ = ip;
            char peer[16];
            inet_ntop(AF_INET, &address.sin_addr, peer, sizeof(peer));
            observed_peer_ = peer;
            last_applied_seq_ = last_event_ = 0;
            ++connection_;
            applied_mode_ = 0;
        }
        parser = StopLineParser();
        uint32_t sent_profile = 0;
        bool armed = false;
        while (true) {
            char line[128];
            uint32_t seq, intent, command_epoch, started = Now();
            enum { CONFIG, ARM, MODE, TEST } kind = MODE;
            ModeCommand command;
            ServoProfile profile;
            TestCommand test;
            bool desired;
            {
                std::lock_guard<std::mutex> l(mutex_);
                command_epoch = power_.Epoch();
                seq = ++command_sequence_;
                profile = profile_;
                const bool input_ready = input_source_ == "simulation" ||
                    (input_source_ == "camera" && camera_frame_ &&
                     uint32_t(started - camera_frame_->captured) < 800 &&
                     camera_observation_version_ == 2 && hold_.Healthy(started)) ||
                    (input_source_ == "onboard" && model_ready_ && vision_calibrated_ &&
                     local_capture_.Seen() && uint32_t(started - local_capture_.Captured()) < 800);
                const bool ready = !shutting_down_ && client_connected_ && capable_ &&
                    client_hold_protocol_ == 2 && profile_match_ && applied_mode_ == 0 &&
                    clock_.Fresh(started) && input_ready;
                if (continuous_output_.ShouldArm(ready, wanted_arm_, outputs_enabled_, arm_in_flight_)) {
                    StopLocked("auto_arm", false);
                    wanted_arm_ = true;
                }
                intent = intent_sequence_;
                desired = power_.Active() && wanted_arm_ && client_hold_protocol_ == 2;
                // An ARM can only follow a matching neutral receipt on this connection.
                if (desired && !clock_.Fresh(started)) {
                    desired = false;
                    if (armed) StopLocked("clock_anchor_timeout", true);
                }
                requested_.Tick(started);
                uint32_t rem = requested_.Remaining(started);
                if (armed && !desired) {
                    kind = ARM;
                    arm_in_flight_ = true;
                    snprintf(line, sizeof(line), "ARM %lu 0\n", (unsigned long)seq);
                } else if (sent_profile != profile.Id()) {
                    kind = CONFIG;
                    snprintf(line, sizeof(line), "PROFILE %lu %u %u %u %u %u %u\n",
                             (unsigned long)seq, profile.neutral[0], profile.neutral[1],
                             profile.neutral[2], profile.run[0], profile.run[1], profile.run[2]);
                } else if (armed != desired) {
                    kind = ARM;
                    arm_in_flight_ = true;
                    snprintf(line, sizeof(line), "ARM %lu %u\n", (unsigned long)seq,
                             desired ? 1 : 0);
                } else if (test_active_ && rem >= 100) {
                    kind = TEST;
                    test = {seq, test_channel_, test_pulse_,
                            uint16_t(std::min<uint32_t>(rem, 500))};
                    snprintf(line, sizeof(line), "TEST %lu %u %u %u\n", (unsigned long)seq,
                             test.channel, test.pulse, test.lease_ms);
                } else {
                    FinishServoTestTail(test_active_, requested_, rem);
                    uint8_t mode = requested_.Mode();
                    if (input_source_ == "camera" && camera_observation_version_ == 2) {
                        mode = hold_.Motion(started);
                        rem = camera_frame_ ? hold_.MotionRemaining(started, camera_frame_->captured) : 0;
                    }
                    rem = std::min<uint32_t>(rem, 600);
                    mode = ModeForRemainingLease(mode, rem, armed, desired);
                    uint32_t cutoff = 0;
                    const bool deadline_ok = clock_.Map(started + (mode && rem ? rem : 600), started, cutoff);
                    mode = deadline_ok ? mode : 0;
                    command = {seq, mode, uint16_t(std::max<uint32_t>(100, rem))};
                    if (client_hold_protocol_ == 2 && deadline_ok) {
                        snprintf(line, sizeof(line), "SET2 %lu %u %u %lu\n", (unsigned long)seq,
                                 command.mode, command.lease_ms, (unsigned long)cutoff);
                    } else {
                        // Legacy SET is permitted solely as a neutral baseline.
                        command.mode = 0;
                        snprintf(line, sizeof(line), "SET %lu 0 100\n", (unsigned long)seq);
                    }
                }
                if (armed && ((kind == MODE && command.mode) || (kind == TEST))) {
                    motion_possible_ = true;
                    possible_motion_until_ =
                        started + (kind == TEST ? test.lease_ms : command.lease_ms) + 250;
                }
            }
            bool transmitted;
            {
                std::lock_guard<std::mutex> l(mutex_);
                if (!power_.Accept(command_epoch)) {
                    // A prepared motion/ARM is replaced with neutral on a power edge.
                    desired = false;
                    intent = intent_sequence_;
                    test_active_ = false;
                    if (armed) {
                        kind = ARM;
                        arm_in_flight_ = true;
                        snprintf(line, sizeof(line), "ARM %lu 0\n", (unsigned long)seq);
                    } else {
                        kind = MODE;
                        command = {seq, 0, 100};
                        snprintf(line, sizeof(line), "SET %lu 0 100\n", (unsigned long)seq);
                    }
                }
                // Linearize transmission with BeginPowerStop: either this
                // record was submitted before the guard, or it is neutral.
                transmitted = SendControlNow(fd, line);
            }
            if (!transmitted)
                break;
            bool acknowledged = false;
            until = Now() + 250;
            while ((int32_t)(until - Now()) > 0 && !acknowledged) {
                char bytes[128];
                int count = recv(fd, bytes, sizeof(bytes), 0);
                if (count <= 0)
                    break;
                for (int i = 0; i < count; ++i) {
                    if (!parser.Feed(bytes[i]))
                        continue;
                    if (Event(parser.Line()))
                        continue;
                    uint32_t v[2];
                    Applied a;
                    if (kind == CONFIG && ReadControlNumbers(parser.Line(), "PROFILED ", v, 2) &&
                        v[0] == seq && v[1] == profile.Id()) {
                        sent_profile = v[1];
                        std::lock_guard<std::mutex> l(mutex_);
                        profile_match_ = profile_.Id() == sent_profile;
                        acknowledged = true;
                    } else if (kind == ARM && ReadControlNumbers(parser.Line(), "ARMED ", v, 2) &&
                               v[0] == seq && v[1] == unsigned(desired)) {
                        armed = desired;
                        std::lock_guard<std::mutex> l(mutex_);
                        outputs_enabled_ = armed;
                        if (armed && power_.Accept(command_epoch) && wanted_arm_) {
                            armed_at_ms_ = Now(); hold_.ArmEpoch(armed_at_ms_);
                            requested_.Disconnect(); test_active_ = false;
                            ++intent_sequence_;
                        }
                        if (!armed)
                            motion_possible_ = false;
                        arm_in_flight_ = false;
                        acknowledged = true;
                    } else if ((kind == MODE && ParseApplied(parser.Line(), a, profile)) ||
                               (kind == TEST && ReadApplied(parser.Line(), "TEST_APPLIED ", a))) {
                        bool correct =
                            a.sequence == seq &&
                            a.mode == (armed ? (kind == TEST ? test.channel : command.mode) : 0);
                        for (int c = 0; c < 3 && correct; ++c)
                            correct = a.pulse_us[c] ==
                                      (armed && kind == TEST && c == test.channel - 1 ? test.pulse
                                       : a.mode == c + 1 ? profile.run[c]
                                                         : profile.neutral[c]);
                        if (correct) {
                            std::lock_guard<std::mutex> l(mutex_);
                            last_applied_seq_ = seq;
                            applied_intent_ = intent;
                            last_ack_ms_ = Now();
                            ack_latency_ = Now() - started;
                            applied_mode_ = a.mode;
                            for (int c = 0; c < 3; ++c)
                                pulse_us_[c] = a.pulse_us[c];
                            client_uptime_ = a.uptime_ms;
                            if (kind == MODE && power_.Accept(command_epoch)) clock_.Acknowledge(a.uptime_ms, last_ack_ms_);
                            ++ack_count_;
                            acknowledged = true;
                        }
                    }
                }
            }
            if (!acknowledged)
                break;
            vTaskDelay(pdMS_TO_TICKS(100));
        }
        close(fd);
        {
            std::lock_guard<std::mutex> l(mutex_);
            client_connected_ = false;
            outputs_enabled_ = wanted_arm_ = profile_match_ = false;
            StopLocked("link_lost", true);
            clock_.Reset(); client_hold_protocol_ = 0; armed_at_ms_ = 0;
            arm_in_flight_ = false;
        }
    }
}
// Dedicated listener: large camera replies never occupy the control listener/task.
void GestureService::CameraHttpServe() {
    Network();
    int listener = -1;
    while (true) {
        if (listener < 0) {
            listener = Listener(8081);
            if (listener < 0) {
                vTaskDelay(pdMS_TO_TICKS(500));
                continue;
            }
        }
        int fd = accept(listener, nullptr, nullptr);
        if (fd < 0)
            continue;
        Timeout(fd, 100);
        std::string request;
        char bytes[256];
        uint32_t start = Now();
        while (request.size() < 1024 && uint32_t(Now() - start) < 300) {
            int count = recv(fd, bytes, std::min(sizeof(bytes), 1024 - request.size()), 0);
            if (count <= 0)
                break;
            request.append(bytes, count);
            if (request.find("\r\n\r\n") != std::string::npos)
                break;
        }
        char method[8] = {}, path[40] = {};
        if (request.find("\r\n\r\n") == std::string::npos ||
            sscanf(request.c_str(), "%7s %39s", method, path) != 2) {
            Reply(fd, 400, "{}");
            close(fd);
            continue;
        }
        if (strcmp(method, "GET") || strcmp(path, "/frame")) {
            Reply(fd, 404, "{}");
            close(fd);
            continue;
        }
        std::shared_ptr<const wifi_camera::Frame> frame;
        std::string id;
        uint32_t frame_epoch;
        {
            std::lock_guard<std::mutex> l(mutex_);
            if (power_.Active() && owner_.Accept("camera"))
                frame = camera_frame_;
            id = watcher_id_;
            frame_epoch = power_.Epoch();
        }
        uint32_t now = Now();
        if (!frame || uint32_t(now - frame->captured) >= 800) {
            Reply(fd, 503, "{\"error\":\"camera_frame_unavailable\"}");
            close(fd);
            continue;
        }
        std::string header =
            "HTTP/1.1 200 OK\r\nContent-Type: image/jpeg\r\nConnection: close\r\nCache-Control: "
            "no-store\r\nContent-Length: " +
            std::to_string(frame->jpeg.size()) + "\r\nX-Watcher-Id: " + id +
            "\r\nX-Capture-Session: " + std::to_string(frame->session) +
            "\r\nX-Frame-Id: " + std::to_string(frame->id) +
            "\r\nX-Frame-Age-Ms: " + std::to_string(uint32_t(now - frame->captured)) +
            "\r\nX-Frame-Width: " + std::to_string(frame->width) +
            "\r\nX-Frame-Height: " + std::to_string(frame->height) + "\r\n\r\n";
        uint32_t sending = Now();
        bool active;
        { std::lock_guard<std::mutex> l(mutex_); active = power_.Accept(frame_epoch); }
        if (active && Send(fd, header)) {
            size_t offset = 0;
            while (offset < frame->jpeg.size() && uint32_t(Now() - sending) < 500) {
                { std::lock_guard<std::mutex> l(mutex_); active = power_.Accept(frame_epoch); }
                if (!active) break;
                int count = send(fd, frame->jpeg.data() + offset,
                                 std::min<size_t>(4096, frame->jpeg.size() - offset), 0);
                if (count <= 0)
                    break;
                offset += count;
            }
        }
        close(fd);
    }
}
void GestureService::HttpServe() {
    Network();
    int listener = -1;
    while (true) {
        if (listener < 0) {
            listener = Listener(8080);
            if (listener < 0) {
                vTaskDelay(pdMS_TO_TICKS(500));
                continue;
            }
        }
        int fd = accept(listener, nullptr, nullptr);
        if (fd < 0)
            continue;
        uint32_t request_epoch;
        { std::lock_guard<std::mutex> l(mutex_); request_epoch = power_.Epoch(); }
        Timeout(fd, 250);
        std::string request;
        char bytes[256];
        size_t boundary = std::string::npos;
        uint32_t until = Now() + 800;
        while (request.size() < 2048 && (int32_t)(until - Now()) > 0) {
            int n = recv(fd, bytes, sizeof(bytes), 0);
            if (n <= 0)
                break;
            request.append(bytes, n);
            boundary = request.find("\r\n\r\n");
            if (boundary != std::string::npos)
                break;
        }
        if (boundary == std::string::npos) {
            Reply(fd, 400, "{}");
            close(fd);
            continue;
        }
        char method[8] = {}, path[40] = {};
        if (sscanf(request.c_str(), "%7s %39s", method, path) != 2) {
            close(fd);
            continue;
        }
        if (!strcmp(method, "GET") && !strcmp(path, "/screen")) {
            Reply(fd, 503,
                  "{\"error\":\"screen_snapshot_diagnostic_disabled\","
                  "\"reason\":\"isolating_snapshot_stall\"}");
            close(fd);
            continue;
        }
        if (!strcmp(method, "GET") && (!strcmp(path, "/status") || !strcmp(path, "/"))) {
            Reply(fd, 200, Status());
            close(fd);
            continue;
        }
        if (strcmp(method, "POST")) {
            Reply(fd, 404, "{}");
            close(fd);
            continue;
        }
        size_t length = 0;
        std::string headers = request.substr(0, boundary);
        for (auto& c : headers)
            if (c >= 'A' && c <= 'Z')
                c += 'a' - 'A';
        auto pos = headers.find("\r\ncontent-length:");
        if (pos != std::string::npos) {
            const char* start = headers.c_str() + pos + 17;
            while (*start == ' ')
                ++start;
            char* end = nullptr;
            unsigned long value = strtoul(start, &end, 10);
            if (end == start || (*end != '\r' && *end) || value > 512) {
                Reply(fd, 400, "{}");
                close(fd);
                continue;
            }
            length = value;
        }
        std::string body = request.substr(boundary + 4);
        while (body.size() < length && (int32_t)(until - Now()) > 0) {
            int n = recv(fd, bytes, std::min(sizeof(bytes), length - body.size()), 0);
            if (n <= 0)
                break;
            body.append(bytes, n);
        }
        if (body.size() != length) {
            Reply(fd, 400, "{}");
            close(fd);
            continue;
        }
        bool power_allowed;
        {
            std::lock_guard<std::mutex> l(mutex_);
            power_allowed = PowerRequestAllowed(power_.State(), path) &&
                ((!strcmp(path, "/stop") || !strcmp(path, "/suspend")) || power_.Accept(request_epoch));
        }
        if (!power_allowed) {
            Reply(fd, 409, "{\"error\":\"power_not_active\"}");
            close(fd);
            continue;
        }
        auto* o = cJSON_ParseWithLength(body.data(), body.size());
        bool ok = false;
        std::string source_reply;
        if (!strcmp(path, "/stop")) {
            StopDisarm("explicit_stop");
            ok = true;
        } else if (!strcmp(path, "/suspend")) {
            StopDisarm("recognition_unavailable");
            ok = true;
        } else if (o && !strcmp(path, "/source")) {
            auto* source = cJSON_GetObjectItemCaseSensitive(o, "source");
            if (cJSON_IsString(source)) {
                uint32_t generation = 0;
                ok = SwitchSource(source->valuestring, &generation, request_epoch);
                if (ok)
                    source_reply = "{\"ok\":true,\"armed\":false,\"disarm_requested\":true,\"source\":\"" +
                                   std::string(source->valuestring) + "\",\"stop_generation\":" +
                                   std::to_string(generation) + "}";
            }
        } else if (o && !strcmp(path, "/gesture")) {
            auto* g = cJSON_GetObjectItemCaseSensitive(o, "gesture");
            auto* s = cJSON_GetObjectItemCaseSensitive(o, "source");
            int lease;
            if (cJSON_IsString(g) && cJSON_IsString(s) && Number(o, "lease_ms", 100, 600, lease)) {
                uint32_t session = 0, frame = 0, age = 800;
                auto* id = cJSON_GetObjectItemCaseSensitive(o, "camera_session_id");
                if (cJSON_IsString(id))
                    ParseSequence(id->valuestring, "", session);
                else
                    wifi_camera::UInt(o, "camera_session_id", session);
                wifi_camera::UInt(o, "camera_frame_id", frame);
                wifi_camera::UInt(o, "frame_age_ms", age);
                auto* version = cJSON_GetObjectItemCaseSensitive(o, "observation_version");
                if (version) {
                    int v, confirm_age;
                    auto* state = cJSON_GetObjectItemCaseSensitive(o, "observation_state");
                    auto* confirm = cJSON_GetObjectItemCaseSensitive(o, "confirmed_this_frame");
                    auto* hand = cJSON_GetObjectItemCaseSensitive(o, "hand_present");
                    ObservationKind kind;
                    if (!strcmp(s->valuestring, "camera") && Number(o, "observation_version", 2, 2, v) &&
                        cJSON_IsString(state) && ParseObservation(state->valuestring, kind) &&
                        cJSON_IsBool(confirm) && cJSON_IsBool(hand) &&
                        Number(o, "confirmation_age_ms", 0, 2500, confirm_age))
                        ok = SetInput(g->valuestring, s->valuestring, lease, session, frame, age, 2,
                                      kind, cJSON_IsTrue(confirm), cJSON_IsTrue(hand), confirm_age, request_epoch);
                } else ok = SetInput(g->valuestring, s->valuestring, lease, session, frame, age, 0, ObservationKind::Unrecognized, false, false, 0, request_epoch);
            }
        } else if (o && !strcmp(path, "/camera/activity")) {
            auto* s = cJSON_GetObjectItemCaseSensitive(o, "session_id");
            int frame, age;
            if (cJSON_IsString(s) && Number(o, "frame_id", 1, INT32_MAX, frame) &&
                Number(o, "frame_age_ms", 0, INT32_MAX, age)) {
                std::lock_guard<std::mutex> l(mutex_);
                // Mac heartbeats cannot create/renew actual camera activity.
                ok = false;
            }
        } else if (o && !strcmp(path, "/onboard/calibrate")) {
            std::lock_guard<std::mutex> l(mutex_);
            if (power_.Accept(request_epoch) && owner_.Accept("onboard") && model_ready_ && observed_.hand_count == 1 &&
                uint32_t(Now() - observed_.captured_ms) < 800) {
                auto& hand = observed_.hands[0];
                onboard::Features f;
                if (hand.side != onboard::Side::Unknown &&
                    onboard::Extract(hand, observed_.width, observed_.height, f) &&
                    std::fabs(f.normal_z) >= .45f &&
                    std::all_of(f.folded.begin(), f.folded.end(), [](bool v) { return v; })) {
                    StopLocked("back_calibrated", true);
                    int sign = f.normal_z > 0 ? 1 : -1;
                    engine_.Calibrate(hand.side, sign);
                    Settings saved("gesture_servo", true);
                    saved.SetInt(hand.side == onboard::Side::Left ? "back_left" : "back_right",
                                 sign);
                    ok = true;
                }
            }
        } else if (o && !strcmp(path, "/servo/arm")) {
            auto* enabled = cJSON_GetObjectItemCaseSensitive(o, "enabled");
            auto* expected_generation = cJSON_GetObjectItemCaseSensitive(o, "expected_stop_generation");
            auto* expected_source = cJSON_GetObjectItemCaseSensitive(o, "expected_source");
            if (cJSON_IsBool(enabled)) {
                std::lock_guard<std::mutex> l(mutex_);
                bool e = cJSON_IsTrue(enabled);
                ArmStopExpectation expected;
                expected.guarded = expected_generation || expected_source;
                expected.valid = wifi_camera::UInt(o, "expected_stop_generation", expected.generation) &&
                                 cJSON_IsString(expected_source);
                const bool barrier_ok = ArmStopBarrierAllows(e, expected, stop_generation_,
                    cJSON_IsString(expected_source) && owner_.Accept(expected_source->valuestring));
                const uint32_t now = Now();
                bool camera_ready = owner_.Accept("camera") && camera_observation_version_ == 2 &&
                    camera_frame_ && uint32_t(now - camera_frame_->captured) < 800 && hold_.Healthy(now);
                ok = power_.Accept(request_epoch) && (!e || (barrier_ok && !shutting_down_ && (owner_.AllowsServoConfiguration() || camera_ready) &&
                           profile_match_ && capable_ && client_hold_protocol_ == 2 &&
                           clock_.Fresh(now) && client_connected_ && !arm_in_flight_));
                if (ok) {
                    continuous_output_.SetEnabled(e);
                    if (!e) ++stop_generation_;
                    ++intent_sequence_;
                    wanted_arm_ = e;
                    requested_.Disconnect(); hold_.Cancel();
                    test_active_ = false;
                    stop_reason_ = e ? "arming" : "disarm";
                }
            }
        } else if (o && !strcmp(path, "/servo/test")) {
            int channel, pulse, duration;
            if (Number(o, "channel", 1, 3, channel) && Number(o, "pulse_us", 1000, 2000, pulse) &&
                Number(o, "duration_ms", 100, 500, duration)) {
                std::lock_guard<std::mutex> l(mutex_);
                if (power_.Accept(request_epoch) && !shutting_down_ && outputs_enabled_ && wanted_arm_ && profile_match_ &&
                    owner_.AllowsServoConfiguration()) {
                    ++intent_sequence_;
                    test_channel_ = channel;
                    test_pulse_ = pulse;
                    test_active_ = requested_.ApplyTest(
                        {++input_sequence_, uint8_t(channel), uint16_t(pulse), uint16_t(duration)},
                        Now());
                    ok = test_active_;
                }
            }
        } else if (o && !strcmp(path, "/servo/profile")) {
            auto* n = cJSON_GetObjectItemCaseSensitive(o, "neutral_us");
            auto* r = cJSON_GetObjectItemCaseSensitive(o, "run_us");
            ServoProfile p;
            bool valid = cJSON_IsArray(n) && cJSON_IsArray(r) && cJSON_GetArraySize(n) == 3 &&
                         cJSON_GetArraySize(r) == 3;
            for (int i = 0; i < 3 && valid; ++i) {
                auto* a = cJSON_GetArrayItem(n, i);
                auto* b = cJSON_GetArrayItem(r, i);
                valid = cJSON_IsNumber(a) && cJSON_IsNumber(b) && a->valuedouble == a->valueint &&
                        b->valuedouble == b->valueint && a->valueint >= 0 && a->valueint <= 65535 &&
                        b->valueint >= 0 && b->valueint <= 65535;
                if (valid) {
                    p.neutral[i] = a->valueint;
                    p.run[i] = b->valueint;
                }
            }
            if (valid && p.Valid()) {
                std::lock_guard<std::mutex> l(mutex_);
                requested_.Tick(Now());
                if (power_.Accept(request_epoch) && owner_.AllowsServoConfiguration() && !wanted_arm_ && !outputs_enabled_ &&
                    !arm_in_flight_ && !requested_.Mode()) {
                    profile_ = p;
                    requested_.Configure(p);
                    profile_match_ = false;
                    Settings saved("gesture_servo", true);
                    char text[96];
                    snprintf(text, sizeof(text), "%u %u %u %u %u %u", p.neutral[0], p.neutral[1],
                             p.neutral[2], p.run[0], p.run[1], p.run[2]);
                    saved.SetString("profile", text);
                    saved.SetInt("version", kServoProfileVersion);
                    ok = true;
                }
            }
        }
        if (o)
            cJSON_Delete(o);
        Reply(fd, ok ? 200 : 400,
              ok ? (source_reply.empty() ? "{\"ok\":true}" : source_reply)
                 : "{\"error\":\"invalid input or outputs not ready\"}");
        close(fd);
    }
}
void GestureService::DisplayLoop() {
    vTaskDelay(pdMS_TO_TICKS(2500));
    while (true) {
        DisplaySnapshot snapshot = DisplayState();
        // Network and battery reads never run under the control mutex.
        esp_netif_ip_info_t ip{};
        auto* netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
        if (netif && esp_netif_get_ip_info(netif, &ip) == ESP_OK && ip.ip.addr) {
            char text[32];
            snprintf(text, sizeof(text), IPSTR, IP2STR(&ip.ip));
            snapshot.wifi_ip = text;
            snapshot.wifi_connected = true;
        }
        if (WatcherShowGesturePresentation(snapshot)) {
            std::lock_guard<std::mutex> l(mutex_);
            emotion_ = snapshot.mode == 1 ? "angry" : snapshot.mode == 2 ? "relaxed" :
                       snapshot.mode == 3 ? "happy" : snapshot.connected ? "neutral" : "thinking";
        }
        vTaskDelay(pdMS_TO_TICKS(250));
    }
}
