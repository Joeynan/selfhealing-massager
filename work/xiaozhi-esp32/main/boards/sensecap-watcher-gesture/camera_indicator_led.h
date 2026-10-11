#pragma once
#include <esp_timer.h>
#include <mutex>
#include "application.h"
#include "gesture_service.h"
#include "led/led.h"
#include "led_strip.h"
class CameraIndicatorLed : public Led {
    led_strip_handle_t strip_ = nullptr;
    esp_timer_handle_t timer_ = nullptr;
    std::mutex mutex_;
    int last_ = -1;
    void Refresh() {
        auto state = Application::GetInstance().GetDeviceState();
        bool priority = state == kDeviceStateWifiConfiguring || state == kDeviceStateUpgrading;
        int color = !GestureService::Instance().CaptureAllowed() ? 0 :
                    priority ? 2 : GestureService::Instance().CameraActive() ? 1 : 0;
        std::lock_guard<std::mutex> lock(mutex_);
        if (color == last_)
            return;
        last_ = color;
        led_strip_set_pixel(strip_, 0, 0, color == 1 ? 32 : 0, color == 2 ? 8 : 0);
        led_strip_refresh(strip_);
    }

public:
    explicit CameraIndicatorLed(gpio_num_t pin) {
        led_strip_config_t config = {};
        config.strip_gpio_num = pin;
        config.max_leds = 1;
        config.color_component_format = LED_STRIP_COLOR_COMPONENT_FMT_GRB;
        config.led_model = LED_MODEL_WS2812;
        led_strip_rmt_config_t rmt = {};
        rmt.resolution_hz = 10000000;
        ESP_ERROR_CHECK(led_strip_new_rmt_device(&config, &rmt, &strip_));
        led_strip_clear(strip_);
        esp_timer_create_args_t args = {};
        args.callback = [](void* p) { static_cast<CameraIndicatorLed*>(p)->Refresh(); };
        args.arg = this;
        args.name = "camera_led";
        args.skip_unhandled_events = true;
        ESP_ERROR_CHECK(esp_timer_create(&args, &timer_));
        esp_timer_start_periodic(timer_, 50000);
    }
    void OnStateChanged() override { Refresh(); }
};
