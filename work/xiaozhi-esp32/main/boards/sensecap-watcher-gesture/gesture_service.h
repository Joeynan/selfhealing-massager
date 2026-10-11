#pragma once
#include <cstdint>
#include <deque>
#include <mutex>
#include <string>
#include "button_policy.h"
#include "camera_activity.h"
#include "control_protocol.h"
#include "local_capture_activity.h"
#include "onboard_rules.h"
#include "wifi_frame.h"
#include "gesture_hold.h"
#include "deadline_anchor.h"
#include "continuous_output.h"
#include "power_gate.h"
struct OutputEvent {
    uint32_t id, sequence, uptime, connection;
    uint8_t reason, mode;
    uint16_t pulse[3];
    bool historical;
    uint8_t attached_mask = 0;
    uint8_t gpio[3] = {5, 4, 0};
};
class GestureService {
public:
    static GestureService& Instance();
    void Start(bool ready);
    void Submit(const char* label, int score);
    std::string Status();
    bool CameraActive();
    void SubmitLandmarks(const onboard::Frame& frame);
    void StopDisarm(const char* reason);
    bool ArmFromButton();
    bool SafeToShutdown();
    std::string InputSource();
    void BeginCamera(uint32_t session);
    bool SubmitCamera(std::shared_ptr<const wifi_camera::Frame> frame);
    void CameraFault(const char* reason);
    bool BeginPowerStop();
    void MarkPowerReleased();
    void EnterStandby();
    bool ResumePower();
    bool CaptureAllowed();
    uint32_t CaptureEpoch();
    GesturePowerState PowerState();
    void RotatePage(bool clockwise, bool pressed);
    DisplaySnapshot DisplayState();

private:
    std::mutex mutex_;
    PowerGate power_;
    GestureDisplayPage display_page_ = GestureDisplayPage::Expression;
    uint32_t camera_power_epoch_ = 0;
    bool power_released_ = false;
    onboard::Engine engine_;
    onboard::Tracker tracker_;
    onboard::Frame latest_, observed_;
    onboard::Result recognition_;
    InputOwner owner_;
    bool motion_possible_ = false, shutting_down_ = false, vision_calibrated_ = false,
         frame_pending_ = false, mdns_ready_ = false;
    LocalCaptureActivity local_capture_;
    uint32_t possible_motion_until_ = 0, fps_window_ms_ = 0, fps_window_frames_ = 0;
    float inference_fps_ = 0;
    std::string model_name_ = "unknown", model_error_ = "awaiting_hand_landmarks", watcher_id_;
    OutputState requested_{true};
    ServoProfile profile_;
    GestureHold hold_;
    DeadlineAnchor clock_;
    uint32_t armed_at_ms_ = 0;
    uint8_t client_hold_protocol_ = 0, camera_observation_version_ = 0;
    CameraActivity camera_;
    wifi_camera::Ledger camera_ledger_;
    std::shared_ptr<const wifi_camera::Frame> camera_frame_;
    uint32_t camera_session_ = 0, camera_frames_ = 0;
    std::string camera_error_ = "awaiting_camera_frame";
    ContinuousOutput continuous_output_;
    bool model_ready_ = false, client_connected_ = false, outputs_enabled_ = false,
         wanted_arm_ = false, capable_ = false, profile_match_ = false, test_active_ = false,
         arm_in_flight_ = false;
    uint64_t frames_ = 0;
    uint32_t intent_sequence_ = 0, applied_intent_ = 0;
    uint32_t stop_generation_ = 0;
    uint32_t input_sequence_ = 0, command_sequence_ = 0, last_applied_seq_ = 0, ack_count_ = 0,
             last_ack_ms_ = 0, client_uptime_ = 0, ack_latency_ = 0, connection_ = 0,
             last_event_ = 0;
    uint8_t applied_mode_ = 0, test_channel_ = 0;
    uint16_t test_pulse_ = 1500, pulse_us_[3] = {1500, 1500, 1500};
    std::string input_source_ = "camera", client_ip_, client_mac_, observed_peer_,
                emotion_ = "thinking", stop_reason_ = "startup";
    std::deque<OutputEvent> events_;
    void Serve();
    void HttpServe();
    void CameraHttpServe();
    void DisplayLoop();
    void RulesLoop();
    bool SwitchSource(const std::string& source, uint32_t* accepted_stop_generation = nullptr,
                      uint32_t power_epoch = 0);
    void StopLocked(const char* reason, bool disarm);
    bool SetInput(const std::string& label, const std::string& source, uint16_t lease,
                  uint32_t session = 0, uint32_t frame = 0, uint32_t age = 800,
                  uint8_t observation_version = 0,
                  ObservationKind kind = ObservationKind::Unrecognized,
                  bool confirmed = false, bool hand = false, uint32_t confirmation_age = 0,
                  uint32_t power_epoch = 0);
    bool Event(const char* line);
};
