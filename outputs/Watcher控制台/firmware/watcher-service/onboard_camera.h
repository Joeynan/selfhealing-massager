#pragma once
#include <esp_io_expander.h>
#include <sscma_client.h>
#include <atomic>
#include <mutex>
#include "landmark_decoder.h"
// Dedicated SPI landmark consumer. It does not invoke chat, capture USB frames,
// or reinterpret legacy class labels as hand landmarks.
class OnboardCamera {
    esp_io_expander_handle_t expander_;
    sscma_client_handle_t client_ = nullptr;
    sscma_client_io_handle_t io_ = nullptr;
    onboard::Decoder decoder_;
    std::mutex decoder_mutex_;
    std::atomic<bool> restarted_{false};
    std::atomic<uint32_t> last_frame_{0};
    uint32_t session_ = 0;
    std::string model_ = "unknown";
    void Run();
    void Receive(const sscma_client_reply_t* reply);
    void Error(const char* error);
    bool StartSession();
    bool CaptureFrame();
    void StopStream();

public:
    explicit OnboardCamera(esp_io_expander_handle_t expander) : expander_(expander) {}
    void Start();
};
