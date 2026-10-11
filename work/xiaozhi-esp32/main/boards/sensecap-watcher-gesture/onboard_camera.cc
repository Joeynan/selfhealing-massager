// 摄像头采集适配层：通过内部 SPI 请求视觉芯片的预装采集固件，发布 JPEG。
// 当前识别模型仍运行在电脑；此文件不在 Watcher 上提取 21 节点。
#include "onboard_camera.h"
#include <esp_log.h>
#include <esp_random.h>
#include <esp_timer.h>
#include <cstdio>
#include "config.h"
#include "gesture_service.h"
#include "capture_epoch.h"
#include "sscma_client_commands.h"
#include "wifi_frame_decoder.h"
namespace {
uint32_t CaptureNow() { return esp_timer_get_time() / 1000; }
}  // namespace
void OnboardCamera::Error(const char* error) {
    if (GestureService::Instance().InputSource() == "camera") {
        GestureService::Instance().CameraFault(error);
        return;
    }
    onboard::Frame frame;
    {
        std::lock_guard<std::mutex> lock(decoder_mutex_);
        frame.model = model_;
    }
    frame.error = error;
    frame.captured_ms = CaptureNow();
    GestureService::Instance().SubmitLandmarks(frame);
}
void OnboardCamera::Receive(const sscma_client_reply_t* reply) {
    if (GestureService::Instance().InputSource() != "onboard" || !reply || !reply->payload)
        return;
    onboard::Frame frame;
    onboard::DecodeResult result;
    {
        std::lock_guard<std::mutex> lock(decoder_mutex_);
        result = decoder_.Decode(reply->payload, CaptureNow(), frame);
    }
    if (result == onboard::DecodeResult::Ignore)
        return;
    if (result == onboard::DecodeResult::Frame && frame.valid)
        last_frame_ = CaptureNow();
    if (result == onboard::DecodeResult::Invalid) {
        frame.valid = frame.model_ready = false;
        if (frame.model.empty()) {
            std::lock_guard<std::mutex> lock(decoder_mutex_);
            frame.model = model_;
        }
        if (frame.error.empty())
            frame.error = "invalid_landmark_message";
    }
    GestureService::Instance().SubmitLandmarks(frame);
}
// 新采集会话废弃旧帧证明；恢复后必须产生新的有效图像，不能沿用待机前缓存。
bool OnboardCamera::StartSession() {
    session_ = esp_random();
    if (!session_)
        session_ = 1;
    {
        std::lock_guard<std::mutex> lock(decoder_mutex_);
        decoder_.Begin(session_);
    }
    char command[48];
    snprintf(command, sizeof(command), "AT+HANDS=%lu\r\n", (unsigned long)session_);
    sscma_client_reply_t reply{};
    uint32_t request_started = CaptureNow();
    esp_err_t ret = sscma_client_request(client_, command, &reply, true, pdMS_TO_TICKS(2000));
    bool ok = false;
    if (ret == ESP_OK && reply.payload) {
        std::lock_guard<std::mutex> lock(decoder_mutex_);
        ok = decoder_.AnchorFromAck(reply.payload, request_started);
    }
    sscma_client_reply_clear(&reply);
    if (!ok)
        Error("landmark_protocol_unavailable");
    return ok;
}
void OnboardCamera::StopStream() {
    sscma_client_reply_t reply{};
    sscma_client_request(client_, "AT+BREAK\r\n", &reply, true, pdMS_TO_TICKS(500));
    sscma_client_reply_clear(&reply);
}
bool OnboardCamera::CaptureFrame() {
    if (!GestureService::Instance().CaptureAllowed()) return false;
    char command[48];
    snprintf(command, sizeof(command), "AT+FRAME=%lu\r\n", (unsigned long)session_);
    sscma_client_reply_t reply{};
    uint32_t start = CaptureNow();
    auto ret = sscma_client_request(client_, command, &reply, true, pdMS_TO_TICKS(750));
    auto frame = std::make_shared<wifi_camera::Frame>();
    bool ok = ret == ESP_OK && reply.payload &&
              wifi_camera::Decode(reply.payload, session_, start, CaptureNow(), *frame);
    sscma_client_reply_clear(&reply);
    if (ok)
        ok = GestureService::Instance().SubmitCamera(frame);
    if (!ok)
        GestureService::Instance().CameraFault("wifi_camera_capture_failed");
    return ok;
}
void OnboardCamera::Start() {
    xTaskCreate(
        [](void* p) {
            static_cast<OnboardCamera*>(p)->Run();
            vTaskDelete(nullptr);
        },
        "onboard_camera", 6144, this, 2, nullptr);
}
void OnboardCamera::Run() {
    sscma_client_io_spi_config_t spi{};
    spi.sync_gpio_num = BSP_SSCMA_CLIENT_SPI_SYNC;
    spi.cs_gpio_num = BSP_SSCMA_CLIENT_SPI_CS;
    spi.pclk_hz = BSP_SSCMA_CLIENT_SPI_CLK;
    spi.spi_mode = 0;
    spi.wait_delay = 10;
    spi.io_expander = expander_;
    spi.flags.sync_use_expander = BSP_SSCMA_CLIENT_RST_USE_EXPANDER;
    if (sscma_client_new_io_spi_bus((sscma_client_spi_bus_handle_t)BSP_SSCMA_CLIENT_SPI_NUM, &spi,
                                    &io_) != ESP_OK) {
        Error("vision_spi_init_failed");
        return;
    }
    sscma_client_config_t config = SSCMA_CLIENT_CONFIG_DEFAULT();
    config.event_queue_size = 2;
    config.tx_buffer_size = CONFIG_SSCMA_TX_BUFFER_SIZE;
    config.rx_buffer_size = CONFIG_SSCMA_RX_BUFFER_SIZE;
    config.process_task_stack = CONFIG_SSCMA_PROCESS_TASK_STACK_SIZE;
    config.process_task_affinity = CONFIG_SSCMA_PROCESS_TASK_AFFINITY;
    config.process_task_priority = CONFIG_SSCMA_PROCESS_TASK_PRIORITY;
    config.monitor_task_stack = CONFIG_SSCMA_MONITOR_TASK_STACK_SIZE;
    config.monitor_task_affinity = CONFIG_SSCMA_MONITOR_TASK_AFFINITY;
    config.monitor_task_priority = CONFIG_SSCMA_MONITOR_TASK_PRIORITY;
    config.reset_gpio_num = BSP_SSCMA_CLIENT_RST;
    config.io_expander = expander_;
    config.flags.reset_use_expander = BSP_SSCMA_CLIENT_RST_USE_EXPANDER;
    if (sscma_client_new(io_, &config, &client_) != ESP_OK) {
        Error("vision_client_init_failed");
        return;
    }
    sscma_client_callback_t cb{};
    cb.on_event = [](sscma_client_handle_t, const sscma_client_reply_t* reply, void* p) {
        static_cast<OnboardCamera*>(p)->Receive(reply);
    };
    cb.on_connect = [](sscma_client_handle_t, const sscma_client_reply_t*, void* p) {
        static_cast<OnboardCamera*>(p)->restarted_ = true;
    };
    sscma_client_register_callback(client_, &cb, this);
    if (sscma_client_init(client_) != ESP_OK) {
        Error("vision_client_start_failed");
        return;
    }
    std::string source;
    bool running = false;
    uint32_t retry = 0;
    uint32_t capture_epoch = 0;
    while (true) {
        auto next = GestureService::Instance().InputSource();
        const uint32_t next_epoch = GestureService::Instance().CaptureEpoch();
        bool reset = restarted_.exchange(false);
        if (CaptureNeedsSession(source, next, capture_epoch, next_epoch, reset)) {
            StopStream();
            if (reset)
                GestureService::Instance().StopDisarm("vision_restart");
            source = next;
            capture_epoch = next_epoch;
            running = false;
            retry = 0;
            if (source == "camera") {
                session_ = esp_random();
                if (!session_)
                    session_ = 1;
                GestureService::Instance().BeginCamera(session_);
                running = true;
            } else if (source == "onboard") {
                running = StartSession();
                last_frame_ = CaptureNow();
            }
        }
        if (source == "camera") {
            if (!running) {
                session_ = esp_random();
                if (!session_)
                    session_ = 1;
                GestureService::Instance().BeginCamera(session_);
            }
            running = CaptureFrame();
            vTaskDelay(pdMS_TO_TICKS(running ? 10 : 250));
        } else {
            if (source == "onboard" && running &&
                uint32_t(CaptureNow() - last_frame_.load()) >= 2500) {
                GestureService::Instance().StopDisarm("vision_stream_timeout");
                running = StartSession();
                last_frame_ = CaptureNow();
            }
            if (source == "onboard" && !running && uint32_t(CaptureNow() - retry) >= 5000) {
                retry = CaptureNow();
                running = StartSession();
            }
            vTaskDelay(pdMS_TO_TICKS(100));
        }
    }
}
