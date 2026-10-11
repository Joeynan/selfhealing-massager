// Watcher 专用板型入口：初始化硬件、整屏表情、滚轮两页、长按电源和摄像头。
// 显示读取状态快照；页面切换不会改变手势来源、动作期限或舵机映射。
#include <esp_timer.h>
#include <ssid_manager.h>
#include <atomic>
#include <cmath>
#include <cstdio>
#include "application.h"
#include "button_policy.h"
#include "camera_indicator_led.h"
#include "config.h"
#include "display/lcd_display.h"
#include "gesture_face.h"
#include "gesture_face_geometry.h"
#include "gesture_ui.h"
#include "gesture_ui_text.h"
#include "gesture_status_text.h"
#include "gesture_service.h"
#include "knob.h"
#include "lvgl_theme.h"
LV_FONT_DECLARE(watcher_ui_font_20);
#include "misc/lv_event.h"
#include "onboard_camera.h"
#include "power_save_timer.h"
#include "sensecap_audio_codec.h"
#include "sscma_camera.h"
#include "source_wifi_config.h"
#include "wifi_board.h"

#include <driver/i2c_master.h>
#include <driver/spi_common.h>
#include <driver/spi_master.h>
#include <esp_adc/adc_oneshot.h>
#include <esp_app_desc.h>
#include <esp_check.h>
#include <esp_console.h>
#include <esp_io_expander_tca95xx_16bit.h>
#include <esp_lcd_panel_io.h>
#include <esp_lcd_panel_ops.h>
#include <esp_lcd_spd2010.h>
#include <esp_log.h>
#include <esp_mac.h>
#include <esp_sleep.h>
#include <iot_button.h>
#include <iot_knob.h>
#include <nvs_flash.h>

#include "assets/lang_config.h"

#define TAG "sensecap_watcher"

class CustomLcdDisplay : public SpiLcdDisplay {
    DisplaySnapshot presentation_;
    GestureFaceFrame face_from_;
    GestureFaceFrame face_drawn_;
    uint32_t face_changed_ = 0;
    uint32_t data_updated_ = 0;
    bool have_presentation_ = false;
    bool animation_running_ = false;
    lv_timer_t* face_timer_ = nullptr;
    lv_obj_t* gesture_root_ = nullptr;
    lv_obj_t* gesture_face_ = nullptr;
    lv_obj_t* gesture_data_ = nullptr;
    lv_obj_t* gesture_bars_[2][5] = {};
    lv_obj_t* gesture_mouth_ = nullptr;
    lv_obj_t* gesture_flat_ = nullptr;
    lv_obj_t* gesture_brows_[2] = {};
    lv_obj_t* data_labels_[9] = {};
    lv_obj_t* power_prompt_ = nullptr;
    lv_point_precise_t brow_points_[2][2] = {};
    lv_point_precise_t flat_points_[2] = {{0, 0}, {56, 0}};

    static void PlainObject(lv_obj_t* object) {
        lv_obj_remove_flag(object, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_set_style_border_width(object, 0, 0);
        lv_obj_set_style_pad_all(object, 0, 0);
        lv_obj_set_style_shadow_width(object, 0, 0);
    }

    void EnsureGestureUI() {
        if (gesture_root_) return;
        auto* screen = lv_screen_active();
        lv_obj_set_style_bg_color(screen, lv_color_black(), 0);
        gesture_root_ = lv_obj_create(screen);
        PlainObject(gesture_root_);
        lv_obj_add_flag(gesture_root_, LV_OBJ_FLAG_IGNORE_LAYOUT);
        lv_obj_set_size(gesture_root_, 412, 412);
        lv_obj_set_pos(gesture_root_, 0, 0);
        lv_obj_set_style_bg_color(gesture_root_, lv_color_black(), 0);
        lv_obj_set_style_bg_opa(gesture_root_, LV_OPA_COVER, 0);
        lv_obj_set_style_radius(gesture_root_, 0, 0);
        gesture_face_ = lv_obj_create(gesture_root_);
        gesture_data_ = lv_obj_create(gesture_root_);
        for (auto* page : {gesture_face_, gesture_data_}) {
            PlainObject(page);
            lv_obj_set_size(page, 412, 412);
            lv_obj_set_pos(page, 0, 0);
            lv_obj_set_style_radius(page, 0, 0);
            lv_obj_set_style_bg_color(page, lv_color_black(), 0);
            lv_obj_set_style_bg_opa(page, LV_OPA_COVER, 0);
        }
        lv_obj_set_style_text_font(gesture_data_, &watcher_ui_font_20, 0);
        const auto color = lv_color_hex(0x29DBB6);
        for (int eye = 0; eye < 2; ++eye) {
            for (int bar = 0; bar < 5; ++bar) {
                auto* object = gesture_bars_[eye][bar] = lv_obj_create(gesture_face_);
                PlainObject(object);
                lv_obj_set_style_bg_color(object, color, 0);
                lv_obj_set_style_bg_opa(object, LV_OPA_COVER, 0);
                lv_obj_set_style_radius(object, LV_RADIUS_CIRCLE, 0);
            }
            gesture_brows_[eye] = lv_line_create(gesture_face_);
            lv_obj_set_style_line_color(gesture_brows_[eye], color, 0);
            lv_obj_set_style_line_width(gesture_brows_[eye], 7, 0);
            lv_obj_set_style_line_rounded(gesture_brows_[eye], true, 0);
        }
        gesture_mouth_ = lv_arc_create(gesture_face_);
        lv_obj_set_size(gesture_mouth_, 116, 92);
        lv_obj_remove_flag(gesture_mouth_, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_set_style_arc_opa(gesture_mouth_, LV_OPA_TRANSP, LV_PART_MAIN);
        lv_obj_set_style_bg_opa(gesture_mouth_, LV_OPA_TRANSP, LV_PART_KNOB);
        lv_obj_set_style_arc_opa(gesture_mouth_, LV_OPA_TRANSP, LV_PART_KNOB);
        lv_obj_set_style_arc_color(gesture_mouth_, color, LV_PART_INDICATOR);
        lv_obj_set_style_arc_width(gesture_mouth_, 7, LV_PART_INDICATOR);
        gesture_flat_ = lv_line_create(gesture_face_);
        lv_line_set_points(gesture_flat_, flat_points_, 2);
        lv_obj_set_style_line_color(gesture_flat_, color, 0);
        lv_obj_set_style_line_width(gesture_flat_, 7, 0);
        lv_obj_set_style_line_rounded(gesture_flat_, true, 0);
        for (int row = 0; row < 9; ++row) {
            auto* label = data_labels_[row] = lv_label_create(gesture_data_);
            lv_obj_set_width(label, 280);
            lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_CENTER, 0);
            lv_obj_set_style_text_color(label, row == 0 ? color : lv_color_hex(0xBFE9DD), 0);
            lv_label_set_long_mode(label, LV_LABEL_LONG_CLIP);
            lv_obj_align(label, LV_ALIGN_TOP_MID, 0, 71 + row * 30);
        }
        power_prompt_ = lv_label_create(gesture_root_);
        lv_obj_set_width(power_prompt_, 280);
        lv_obj_set_style_text_font(power_prompt_, &watcher_ui_font_20, 0);
        lv_obj_set_style_text_align(power_prompt_, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_style_text_color(power_prompt_, color, 0);
        lv_obj_set_style_bg_color(power_prompt_, lv_color_black(), 0);
        lv_obj_set_style_bg_opa(power_prompt_, LV_OPA_COVER, 0);
        lv_obj_set_style_pad_ver(power_prompt_, 14, 0);
        lv_obj_align(power_prompt_, LV_ALIGN_CENTER, 0, 0);
        lv_obj_add_flag(power_prompt_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(top_bar_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(status_bar_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(bottom_bar_, LV_OBJ_FLAG_HIDDEN);
        face_timer_ = lv_timer_create(
            [](lv_timer_t* timer) {
                static_cast<CustomLcdDisplay*>(lv_timer_get_user_data(timer))->AnimateGestureFace();
            }, 50, this);
        lv_timer_pause(face_timer_);
    }

    void UpdateGestureData() {
        const auto lines = GestureDataRows(presentation_);
        for (int row = 0; row < 9; ++row)
            lv_label_set_text(data_labels_[row], lines[row].c_str());
        data_updated_ = lv_tick_get();
    }

public:
    CustomLcdDisplay(esp_lcd_panel_io_handle_t io_handle, esp_lcd_panel_handle_t panel_handle,
                     int width, int height, int offset_x, int offset_y, bool mirror_x,
                     bool mirror_y, bool swap_xy)
        : SpiLcdDisplay(io_handle, panel_handle, width, height, offset_x, offset_y, mirror_x,
                        mirror_y, swap_xy) {}

    void AnimateGestureFace() {
        // LVGL invokes the timer under its own mutex. This path never reads the
        // control service, battery, network, or allocates replacement objects.
        if (!gesture_face_ || presentation_.power != GesturePowerState::Active ||
            presentation_.page != GestureDisplayPage::Expression) return;
        const auto tick = lv_tick_get();
        const auto target = GestureFaceGeometry(presentation_.mode, presentation_.connected, tick);
        const float fraction = std::min(1.0f, (tick - face_changed_) / 250.0f);
        face_drawn_ = BlendGestureFace(face_from_, target, fraction);
        for (int eye = 0; eye < 2; ++eye) {
            for (int bar = 0; bar < 5; ++bar) {
                const auto& value = face_drawn_.eyes[eye][bar];
                lv_obj_set_size(gesture_bars_[eye][bar], value.width, value.height);
                lv_obj_align(gesture_bars_[eye][bar], LV_ALIGN_CENTER, value.x, value.y);
            }
            brow_points_[eye][0] = {0, eye ? 17 : 0};
            brow_points_[eye][1] = {80, eye ? 0 : 17};
            lv_line_set_points(gesture_brows_[eye], brow_points_[eye], 2);
            lv_obj_align(gesture_brows_[eye], LV_ALIGN_CENTER, eye ? 82 : -82,
                         face_drawn_.brow_y);
            if (face_drawn_.show_brows)
                lv_obj_remove_flag(gesture_brows_[eye], LV_OBJ_FLAG_HIDDEN);
            else lv_obj_add_flag(gesture_brows_[eye], LV_OBJ_FLAG_HIDDEN);
        }
        lv_obj_align(gesture_flat_, LV_ALIGN_CENTER, face_drawn_.mouth_x, face_drawn_.mouth_y);
        lv_obj_align(gesture_mouth_, LV_ALIGN_CENTER, face_drawn_.mouth_x, face_drawn_.mouth_y);
        if (face_drawn_.mouth == GestureMouth::Flat) {
            lv_obj_add_flag(gesture_mouth_, LV_OBJ_FLAG_HIDDEN);
            lv_obj_remove_flag(gesture_flat_, LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_remove_flag(gesture_mouth_, LV_OBJ_FLAG_HIDDEN);
            lv_obj_add_flag(gesture_flat_, LV_OBJ_FLAG_HIDDEN);
            const bool frown = face_drawn_.mouth == GestureMouth::Frown;
            const bool puzzled = face_drawn_.mouth == GestureMouth::Puzzled;
            lv_arc_set_angles(gesture_mouth_, frown ? 210 : puzzled ? 220 : 20,
                              frown ? 330 : puzzled ? 320 : 160);
        }
    }

    bool SetGesturePresentation(const DisplaySnapshot& snapshot) {
        if (!IsSetupUICalled()) return false;
        DisplayLockGuard lock(this);
        if (!lock) return false;
        EnsureGestureUI();
        const bool changed = !have_presentation_ || presentation_.mode != snapshot.mode ||
                             presentation_.connected != snapshot.connected;
        const bool page_changed = !have_presentation_ || presentation_.page != snapshot.page;
        if (changed) {
            face_from_ = have_presentation_ ? face_drawn_
                         : GestureFaceGeometry(snapshot.mode, snapshot.connected, lv_tick_get());
            face_changed_ = lv_tick_get();
        }
        presentation_ = snapshot;
        have_presentation_ = true;
        const bool active = snapshot.power == GesturePowerState::Active;
        const bool expression = active && snapshot.page == GestureDisplayPage::Expression;
        const bool data = active && snapshot.page == GestureDisplayPage::Data;
        if (expression) {
            lv_obj_remove_flag(gesture_face_, LV_OBJ_FLAG_HIDDEN);
            const bool starting_animation = !animation_running_;
            if (starting_animation) lv_timer_resume(face_timer_);
            animation_running_ = true;
            // Snapshot delivery is independent of the 20 fps animation clock.
            // Only paint here for an immediate first/page/state transition.
            if (changed || page_changed || starting_animation) AnimateGestureFace();
        } else {
            lv_obj_add_flag(gesture_face_, LV_OBJ_FLAG_HIDDEN);
            if (animation_running_) lv_timer_pause(face_timer_);
            animation_running_ = false;
        }
        if (data) {
            lv_obj_remove_flag(gesture_data_, LV_OBJ_FLAG_HIDDEN);
            if (page_changed || lv_tick_get() - data_updated_ >= 250) UpdateGestureData();
        } else lv_obj_add_flag(gesture_data_, LV_OBJ_FLAG_HIDDEN);
        if (snapshot.power == GesturePowerState::ShuttingDown && !snapshot.power_prompt.empty()) {
            lv_label_set_text(power_prompt_, snapshot.power_prompt.c_str());
            lv_obj_remove_flag(power_prompt_, LV_OBJ_FLAG_HIDDEN);
        } else lv_obj_add_flag(power_prompt_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_move_foreground(gesture_root_);
        if (active) lv_obj_move_foreground(low_battery_popup_);
        return true;
    }

    virtual void SetupUI() override {
        // Call parent SetupUI() first to create all lvgl objects
        SpiLcdDisplay::SetupUI();

        DisplayLockGuard lock(this);
        auto lvgl_theme = static_cast<LvglTheme*>(current_theme_);
        auto text_font = lvgl_theme->text_font()->font();
        auto icon_font = lvgl_theme->icon_font()->font();

        lv_obj_set_size(top_bar_, LV_HOR_RES, text_font->line_height);
        lv_obj_set_style_layout(top_bar_, LV_LAYOUT_NONE, 0);
        lv_obj_set_style_pad_top(top_bar_, 10, 0);
        lv_obj_set_style_pad_bottom(top_bar_, 1, 0);

        lv_obj_set_size(status_bar_, LV_HOR_RES, text_font->line_height);
        lv_obj_set_style_layout(status_bar_, LV_LAYOUT_NONE, 0);
        lv_obj_set_style_pad_top(status_bar_, 10, 0);
        lv_obj_set_style_pad_bottom(status_bar_, 1, 0);
        lv_obj_set_y(status_bar_, text_font->line_height);
        lv_obj_add_flag(status_bar_, LV_OBJ_FLAG_IGNORE_LAYOUT);

        // Reparent mute and battery labels to top_bar_ to allow absolute positioning
        lv_obj_set_parent(mute_label_, top_bar_);
        lv_obj_set_parent(battery_label_, top_bar_);
        lv_obj_set_style_margin_left(battery_label_, 0, 0);

        // 针对圆形屏幕调整位置
        //      network  mute  battery     //
        //               status            //
        lv_obj_align(network_label_, LV_ALIGN_TOP_MID, -1.5 * icon_font->line_height, 0);
        lv_obj_align(mute_label_, LV_ALIGN_TOP_MID, 1.0 * icon_font->line_height, 0);
        lv_obj_align(battery_label_, LV_ALIGN_TOP_MID, 2.5 * icon_font->line_height, 0);

        lv_obj_align(status_label_, LV_ALIGN_BOTTOM_MID, 0, 0);
        lv_obj_set_flex_grow(status_label_, 0);
        lv_obj_set_width(status_label_, LV_HOR_RES * 0.75);
        lv_label_set_long_mode(status_label_, LV_LABEL_LONG_SCROLL_CIRCULAR);

        lv_obj_align(notification_label_, LV_ALIGN_BOTTOM_MID, 0, 0);
        lv_obj_set_width(notification_label_, LV_HOR_RES * 0.75);
        lv_label_set_long_mode(notification_label_, LV_LABEL_LONG_SCROLL_CIRCULAR);

        lv_obj_align(low_battery_popup_, LV_ALIGN_BOTTOM_MID, 0, -20);
        lv_obj_set_style_bg_color(low_battery_popup_, lv_color_hex(0xFF0000), 0);
        lv_obj_set_width(low_battery_label_, LV_HOR_RES * 0.75);
        lv_label_set_long_mode(low_battery_label_, LV_LABEL_LONG_SCROLL_CIRCULAR);

        // 针对圆形屏幕调整底部对话框位置，避免被圆角遮挡
        lv_obj_set_style_pad_bottom(bottom_bar_, 30, 0);
        lv_obj_set_width(chat_message_label_, LV_HOR_RES * 0.75);  // 限制宽度，避免文字贴边
    }
};

class SensecapWatcher : public WifiBoard {
private:
    i2c_master_bus_handle_t i2c_bus_;
    LcdDisplay* display_;
    std::unique_ptr<Knob> knob_;
    esp_io_expander_handle_t io_exp_handle;
    button_handle_t btns;
    PowerSaveTimer* power_save_timer_;
    esp_lcd_panel_io_handle_t panel_io_ = nullptr;
    esp_lcd_panel_handle_t panel_ = nullptr;
    ButtonPolicy button_policy_;
    std::mutex button_mutex_;
    std::atomic<bool> shutdown_pending_{false};
    OnboardCamera* onboard_camera_ = nullptr;
    button_driver_t* btn_driver_ = nullptr;
    static SensecapWatcher* instance_;
    SscmaCamera* camera_ = nullptr;

    void InitializePowerSaveTimer() {
        power_save_timer_ = new PowerSaveTimer(-1, 60, 300);
        power_save_timer_->OnEnterSleepMode([this]() {
            GetDisplay()->SetPowerSaveMode(true);
            GetBacklight()->SetBrightness(10);
        });
        power_save_timer_->OnExitSleepMode([this]() {
            GetDisplay()->SetPowerSaveMode(false);
            GetBacklight()->RestoreBrightness();
        });
        power_save_timer_->OnShutdownRequest([this]() { RequestShutdown(); });
        power_save_timer_->SetEnabled(false);  // Gesture console keeps its screen visible.
    }

    void InitializeI2c() {
        // Initialize I2C peripheral
        i2c_master_bus_config_t i2c_bus_cfg = {
            .i2c_port = (i2c_port_t)0,
            .sda_io_num = BSP_GENERAL_I2C_SDA,
            .scl_io_num = BSP_GENERAL_I2C_SCL,
            .clk_source = I2C_CLK_SRC_DEFAULT,
            .glitch_ignore_cnt = 7,
            .intr_priority = 0,
            .trans_queue_depth = 0,
            .flags =
                {
                    .enable_internal_pullup = 1,
                },
        };
        ESP_ERROR_CHECK(i2c_new_master_bus(&i2c_bus_cfg, &i2c_bus_));

        // pulldown for lcd i2c
        const gpio_config_t io_config = {
            .pin_bit_mask = (1ULL << BSP_TOUCH_I2C_SDA) | (1ULL << BSP_TOUCH_I2C_SCL) |
                            (1ULL << BSP_SPI3_HOST_PCLK) | (1ULL << BSP_SPI3_HOST_DATA0) |
                            (1ULL << BSP_SPI3_HOST_DATA1) | (1ULL << BSP_SPI3_HOST_DATA2) |
                            (1ULL << BSP_SPI3_HOST_DATA3) | (1ULL << BSP_LCD_SPI_CS) |
                            (1UL << DISPLAY_BACKLIGHT_PIN),
            .mode = GPIO_MODE_OUTPUT,
            .pull_up_en = GPIO_PULLUP_DISABLE,
            .pull_down_en = GPIO_PULLDOWN_DISABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        gpio_config(&io_config);

        gpio_set_level(BSP_TOUCH_I2C_SDA, 0);
        gpio_set_level(BSP_TOUCH_I2C_SCL, 0);

        gpio_set_level(BSP_LCD_SPI_CS, 0);
        gpio_set_level(DISPLAY_BACKLIGHT_PIN, 0);
        gpio_set_level(BSP_SPI3_HOST_PCLK, 0);
        gpio_set_level(BSP_SPI3_HOST_DATA0, 0);
        gpio_set_level(BSP_SPI3_HOST_DATA1, 0);
        gpio_set_level(BSP_SPI3_HOST_DATA2, 0);
        gpio_set_level(BSP_SPI3_HOST_DATA3, 0);
    }

    esp_err_t IoExpanderSetLevel(uint16_t pin_mask, uint8_t level) {
        return esp_io_expander_set_level(io_exp_handle, pin_mask, level);
    }

    uint8_t IoExpanderGetLevel(uint16_t pin_mask) {
        uint32_t pin_val = 0;
        esp_io_expander_get_level(io_exp_handle, DRV_IO_EXP_INPUT_MASK, &pin_val);
        pin_mask &= DRV_IO_EXP_INPUT_MASK;
        return (uint8_t)((pin_val & pin_mask) ? 1 : 0);
    }

    void InitializeExpander() {
        esp_err_t ret = ESP_OK;
        esp_io_expander_new_i2c_tca95xx_16bit(i2c_bus_, ESP_IO_EXPANDER_I2C_TCA9555_ADDRESS_001,
                                              &io_exp_handle);

        ret |= esp_io_expander_set_dir(io_exp_handle, DRV_IO_EXP_INPUT_MASK, IO_EXPANDER_INPUT);
        ret |= esp_io_expander_set_dir(io_exp_handle, DRV_IO_EXP_OUTPUT_MASK, IO_EXPANDER_OUTPUT);
        ret |= esp_io_expander_set_level(io_exp_handle, DRV_IO_EXP_OUTPUT_MASK, 0);
        ret |= esp_io_expander_set_level(io_exp_handle, BSP_PWR_SYSTEM, 1);
        vTaskDelay(100 / portTICK_PERIOD_MS);
        ret |= esp_io_expander_set_level(io_exp_handle, BSP_PWR_START_UP, 1);
        vTaskDelay(50 / portTICK_PERIOD_MS);

        uint32_t pin_val = 0;
        ret |= esp_io_expander_get_level(io_exp_handle, DRV_IO_EXP_INPUT_MASK, &pin_val);
        ESP_LOGI(TAG, "IO expander initialized: %x", DRV_IO_EXP_OUTPUT_MASK | (uint16_t)pin_val);

        assert(ret == ESP_OK);
    }

    void OnKnobRotate(bool clockwise) {
        GestureService::Instance().RotatePage(clockwise, IoExpanderGetLevel(BSP_KNOB_BTN) == 0);
    }

    // 一个方向进入数据页，反方向返回表情页；按住电源或待机时忽略滚轮。
    void InitializeKnob() {
        knob_ = std::make_unique<Knob>(BSP_KNOB_A_PIN, BSP_KNOB_B_PIN);
        knob_->OnRotate([this](bool clockwise) {
            ESP_LOGD(TAG, "Knob rotation detected. Clockwise:%s", clockwise ? "true" : "false");
            OnKnobRotate(clockwise);
        });
        ESP_LOGI(TAG, "Knob initialized with pins A:%d B:%d", BSP_KNOB_A_PIN, BSP_KNOB_B_PIN);
    }

    bool UsbPresent() { return IoExpanderGetLevel(BSP_PWR_VBUS_IN_DET) == 0; }

    void RequestShutdown() {
        if (shutdown_pending_.exchange(true)) return;
        GestureService::Instance().BeginPowerStop();
        GestureService::Instance().MarkPowerReleased();
        // No wait in button/LVGL/app callbacks. Keep the USB system rail alive
        // so the button driver can still see a later 3-second wake gesture.
        if (xTaskCreate([](void* context) {
                auto* self = static_cast<SensecapWatcher*>(context);
                uint32_t started = esp_timer_get_time() / 1000;
                while (!GestureService::Instance().SafeToShutdown() &&
                       uint32_t(esp_timer_get_time() / 1000 - started) < 850)
                    vTaskDelay(pdMS_TO_TICKS(20));
                self->GetBacklight()->SetBrightness(0);
                if (self->panel_) esp_lcd_panel_disp_on_off(self->panel_, false);
                if (self->UsbPresent()) {
                    GestureService::Instance().EnterStandby();
                    self->shutdown_pending_ = false;
                } else {
                    self->IoExpanderSetLevel(BSP_PWR_LCD, 0);
                    self->IoExpanderSetLevel(BSP_PWR_SYSTEM, 0);
                }
                vTaskDelete(nullptr);
            }, "gesture_power", 3072, this, 3, nullptr) != pdPASS) {
            // Remain guarded if task creation fails; a second release can retry.
            shutdown_pending_ = false;
        }
    }
    void ResumeFromStandby() {
        if (shutdown_pending_ || !UsbPresent()) return;
        if (panel_) esp_lcd_panel_disp_on_off(panel_, true);
        if (GestureService::Instance().ResumePower()) GetBacklight()->RestoreBrightness();
    }
    void TickPowerButton() {
        ButtonAction action;
        {
            std::lock_guard<std::mutex> l(button_mutex_);
            action = button_policy_.Tick(esp_timer_get_time() / 1000);
        }
        if (action == ButtonAction::Disarm &&
            GestureService::Instance().PowerState() == GesturePowerState::Active)
            GestureService::Instance().BeginPowerStop();
    }
    // 运行中长按满 3 秒先禁止新动作，松手执行关机/待机；短按与开机松手保护见 ButtonPolicy。
    void InitializeButton() {
        instance_ = this;
        button_policy_.Boot(IoExpanderGetLevel(BSP_KNOB_BTN) == 0);
        button_config_t btn_config = {.long_press_time = 3000, .short_press_time = 0};
        btn_driver_ = (button_driver_t*)calloc(1, sizeof(button_driver_t));
        btn_driver_->enable_power_save = false;
        btn_driver_->get_key_level = [](button_driver_t*) -> uint8_t {
            return !instance_->IoExpanderGetLevel(BSP_KNOB_BTN);
        };
        ESP_ERROR_CHECK(iot_button_create(&btn_config, btn_driver_, &btns));
        iot_button_register_cb(btns, BUTTON_PRESS_DOWN, nullptr, [](void*, void* context) {
            auto* self = static_cast<SensecapWatcher*>(context);
            std::lock_guard<std::mutex> l(self->button_mutex_);
            self->button_policy_.Down(esp_timer_get_time() / 1000);
        }, this);
        auto hold = [](void*, void* context) {
            static_cast<SensecapWatcher*>(context)->TickPowerButton();
        };
        iot_button_register_cb(btns, BUTTON_LONG_PRESS_START, nullptr, hold, this);
        iot_button_register_cb(btns, BUTTON_LONG_PRESS_HOLD, nullptr, hold, this);
        iot_button_register_cb(btns, BUTTON_PRESS_UP, nullptr, [](void*, void* context) {
            auto* self = static_cast<SensecapWatcher*>(context);
            ButtonAction action;
            {
                std::lock_guard<std::mutex> l(self->button_mutex_);
                action = self->button_policy_.Up(esp_timer_get_time() / 1000);
            }
            if (action != ButtonAction::Shutdown) return;
            if (GestureService::Instance().PowerState() == GesturePowerState::Standby)
                self->ResumeFromStandby();
            else self->RequestShutdown();
        }, this);
    }
    void StartPowerMonitor() {
        xTaskCreate([](void* context) {
            auto* self = static_cast<SensecapWatcher*>(context);
            for (;;) {
                self->TickPowerButton();
                if (GestureService::Instance().PowerState() == GesturePowerState::Standby &&
                    !self->UsbPresent()) self->RequestShutdown();
                vTaskDelay(pdMS_TO_TICKS(20));
            }
        }, "gesture_vbus", 2048, this, 2, nullptr);
    }

    void InitializeSpi() {
        ESP_LOGI(TAG, "Initialize SSCMA SPI bus");
        spi_bus_config_t spi_cfg = {0};

        spi_cfg.mosi_io_num = BSP_SPI2_HOST_MOSI;
        spi_cfg.miso_io_num = BSP_SPI2_HOST_MISO;
        spi_cfg.sclk_io_num = BSP_SPI2_HOST_SCLK;
        spi_cfg.quadwp_io_num = -1;
        spi_cfg.quadhd_io_num = -1;
        spi_cfg.isr_cpu_id = ESP_INTR_CPU_AFFINITY_1;
        spi_cfg.max_transfer_sz = 4095;

        ESP_ERROR_CHECK(spi_bus_initialize(SPI2_HOST, &spi_cfg, SPI_DMA_CH_AUTO));

        ESP_LOGI(TAG, "Initialize QSPI bus");

        spi_bus_config_t qspi_cfg = {0};
        qspi_cfg.sclk_io_num = BSP_SPI3_HOST_PCLK;
        qspi_cfg.data0_io_num = BSP_SPI3_HOST_DATA0;
        qspi_cfg.data1_io_num = BSP_SPI3_HOST_DATA1;
        qspi_cfg.data2_io_num = BSP_SPI3_HOST_DATA2;
        qspi_cfg.data3_io_num = BSP_SPI3_HOST_DATA3;
        qspi_cfg.max_transfer_sz = DISPLAY_WIDTH * DISPLAY_HEIGHT * DRV_LCD_BITS_PER_PIXEL / 8 /
                                   CONFIG_BSP_LCD_SPI_DMA_SIZE_DIV;

        ESP_ERROR_CHECK(spi_bus_initialize(SPI3_HOST, &qspi_cfg, SPI_DMA_CH_AUTO));
    }

    void Initializespd2010Display() {
        ESP_LOGI(TAG, "Install panel IO");
        const esp_lcd_panel_io_spi_config_t io_config = {
            .cs_gpio_num = BSP_LCD_SPI_CS,
            .dc_gpio_num = GPIO_NUM_NC,
            .spi_mode = 3,
            .pclk_hz = DRV_LCD_PIXEL_CLK_HZ,
            .trans_queue_depth = 2,
            .lcd_cmd_bits = DRV_LCD_CMD_BITS,
            .lcd_param_bits = DRV_LCD_PARAM_BITS,
            .flags =
                {
                    .quad_mode = true,
                },
        };
        spd2010_vendor_config_t vendor_config = {
            .flags =
                {
                    .use_qspi_interface = 1,
                },
        };
        esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)BSP_LCD_SPI_NUM, &io_config, &panel_io_);

        ESP_LOGD(TAG, "Install LCD driver");
        esp_lcd_panel_dev_config_t panel_config = {};
        panel_config.rgb_ele_order = DRV_LCD_RGB_ELEMENT_ORDER;
        panel_config.bits_per_pixel = DRV_LCD_BITS_PER_PIXEL;
        panel_config.reset_gpio_num = BSP_LCD_GPIO_RST;  // Shared with Touch reset
        panel_config.vendor_config = &vendor_config;
        esp_lcd_new_panel_spd2010(panel_io_, &panel_config, &panel_);

        esp_lcd_panel_reset(panel_);
        esp_lcd_panel_init(panel_);
        esp_lcd_panel_mirror(panel_, DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y);
        esp_lcd_panel_disp_on_off(panel_, true);

        display_ = new CustomLcdDisplay(panel_io_, panel_, DISPLAY_WIDTH, DISPLAY_HEIGHT,
                                        DISPLAY_OFFSET_X, DISPLAY_OFFSET_Y, DISPLAY_MIRROR_X,
                                        DISPLAY_MIRROR_Y, DISPLAY_SWAP_XY);

        // 使每次刷新的起始列数索引是4的倍数且列数总数是4的倍数，以满足SPD2010的要求
        lv_display_add_event_cb(
            lv_display_get_default(),
            [](lv_event_t* e) {
                lv_area_t* area = (lv_area_t*)lv_event_get_param(e);
                uint16_t x1 = area->x1;
                uint16_t x2 = area->x2;
                // round the start of area down to the nearest 4N number
                area->x1 = (x1 >> 2) << 2;
                // round the end of area up to the nearest 4M+3 number
                area->x2 = ((x2 >> 2) << 2) + 3;
            },
            LV_EVENT_INVALIDATE_AREA, NULL);
    }

    uint16_t BatterygetVoltage(void) {
        static bool initialized = false;
        static adc_oneshot_unit_handle_t adc_handle;
        static adc_cali_handle_t cali_handle = NULL;
        if (!initialized) {
            adc_oneshot_unit_init_cfg_t init_config = {
                .unit_id = ADC_UNIT_1,
            };
            adc_oneshot_new_unit(&init_config, &adc_handle);

            adc_oneshot_chan_cfg_t ch_config = {
                .atten = BSP_BAT_ADC_ATTEN,
                .bitwidth = ADC_BITWIDTH_DEFAULT,
            };
            adc_oneshot_config_channel(adc_handle, BSP_BAT_ADC_CHAN, &ch_config);

            adc_cali_curve_fitting_config_t cali_config = {
                .unit_id = ADC_UNIT_1,
                .chan = BSP_BAT_ADC_CHAN,
                .atten = BSP_BAT_ADC_ATTEN,
                .bitwidth = ADC_BITWIDTH_DEFAULT,
            };
            if (adc_cali_create_scheme_curve_fitting(&cali_config, &cali_handle) == ESP_OK) {
                initialized = true;
            }
        }
        if (initialized) {
            int raw_value = 0;
            int voltage = 0;  // mV
            adc_oneshot_read(adc_handle, BSP_BAT_ADC_CHAN, &raw_value);
            adc_cali_raw_to_voltage(cali_handle, raw_value, &voltage);
            voltage = voltage * 82 / 20;
            // ESP_LOGI(TAG, "voltage: %dmV", voltage);
            return (uint16_t)voltage;
        }
        return 0;
    }

    uint8_t BatterygetPercent(bool print = false) {
        int voltage = 0;
        for (uint8_t i = 0; i < 10; i++) {
            voltage += BatterygetVoltage();
        }
        voltage /= 10;
        int percent = (-1 * voltage * voltage + 9016 * voltage - 19189000) / 10000;
        percent = (percent > 100) ? 100 : (percent < 0) ? 0 : percent;
        if (print) {
            printf("voltage: %dmV, percentage: %d%%\r\n", voltage, percent);
        }
        return (uint8_t)percent;
    }

    void InitializeCmd() {
        esp_console_repl_t* repl = NULL;
        esp_console_repl_config_t repl_config = ESP_CONSOLE_REPL_CONFIG_DEFAULT();
        repl_config.max_cmdline_length = 1024;
        repl_config.prompt = "SenseCAP>";

        const esp_console_cmd_t cmd1 = {.command = "reboot",
                                        .help = "reboot the device",
                                        .hint = nullptr,
                                        .func = [](int argc, char** argv) -> int {
                                            esp_restart();
                                            return 0;
                                        },
                                        .argtable = nullptr};
        ESP_ERROR_CHECK(esp_console_cmd_register(&cmd1));

        const esp_console_cmd_t cmd2 = {
            .command = "shutdown",
            .help = "shutdown the device",
            .hint = nullptr,
            .func = NULL,
            .argtable = NULL,
            .func_w_context = [](void* context, int argc, char** argv) -> int {
                auto self = static_cast<SensecapWatcher*>(context);
                self->GetBacklight()->SetBrightness(0);
                self->IoExpanderSetLevel(BSP_PWR_SYSTEM, 0);
                return 0;
            },
            .context = this};
        ESP_ERROR_CHECK(esp_console_cmd_register(&cmd2));

        const esp_console_cmd_t cmd3 = {
            .command = "battery",
            .help = "get battery percent",
            .hint = NULL,
            .func = NULL,
            .argtable = NULL,
            .func_w_context = [](void* context, int argc, char** argv) -> int {
                auto self = static_cast<SensecapWatcher*>(context);
                self->BatterygetPercent(true);
                return 0;
            },
            .context = this};
        ESP_ERROR_CHECK(esp_console_cmd_register(&cmd3));

        const esp_console_cmd_t cmd4 = {
            .command = "factory_reset",
            .help = "factory reset and reboot the device",
            .hint = NULL,
            .func = NULL,
            .argtable = NULL,
            .func_w_context = [](void* context, int argc, char** argv) -> int {
                nvs_flash_erase();
                esp_restart();
                return 0;
            },
            .context = this};
        ESP_ERROR_CHECK(esp_console_cmd_register(&cmd4));

        const esp_console_cmd_t cmd5 = {
            .command = "read_mac",
            .help = "Read mac address",
            .hint = NULL,
            .func = NULL,
            .argtable = NULL,
            .func_w_context = [](void* context, int argc, char** argv) -> int {
                uint8_t mac[6];
                esp_read_mac(mac, ESP_MAC_WIFI_STA);
                printf("wifi_sta_mac: " MACSTR "\n", MAC2STR(mac));
                esp_read_mac(mac, ESP_MAC_WIFI_SOFTAP);
                printf("wifi_softap_mac: " MACSTR "\n", MAC2STR(mac));
                esp_read_mac(mac, ESP_MAC_BT);
                printf("bt_mac: " MACSTR "\n", MAC2STR(mac));
                return 0;
            },
            .context = this};
        ESP_ERROR_CHECK(esp_console_cmd_register(&cmd5));

        const esp_console_cmd_t cmd6 = {
            .command = "version",
            .help = "Read version info",
            .hint = NULL,
            .func = NULL,
            .argtable = NULL,
            .func_w_context = [](void* context, int argc, char** argv) -> int {
                auto self = static_cast<SensecapWatcher*>(context);
                auto app_desc = esp_app_get_description();
                const char* region = "UNKNOWN";
#if defined(CONFIG_LANGUAGE_ZH_CN)
                region = "CN";
#elif defined(CONFIG_LANGUAGE_EN_US)
                region = "US";
#elif defined(CONFIG_LANGUAGE_JA_JP)
                region = "JP";
#elif defined(CONFIG_LANGUAGE_ES_ES)
                region = "ES";
#elif defined(CONFIG_LANGUAGE_DE_DE)
                region = "DE";
#elif defined(CONFIG_LANGUAGE_FR_FR)
                region = "FR";
#elif defined(CONFIG_LANGUAGE_IT_IT)
                region = "IT";
#elif defined(CONFIG_LANGUAGE_PT_PT)
                region = "PT";
#elif defined(CONFIG_LANGUAGE_RU_RU)
                region = "RU";
#elif defined(CONFIG_LANGUAGE_KO_KR)
                region = "KR";
#endif
                printf(
                    "{\"type\":0,\"name\":\"VER?\",\"code\":0,\"data\":{\"software\":\"%s\","
                    "\"hardware\":\"watcher xiaozhi agent\",\"camera\":%d,\"region\":\"%s\"}}\n",
                    app_desc->version, self->GetCamera() == nullptr ? 0 : 1, region);
                return 0;
            },
            .context = this};
        ESP_ERROR_CHECK(esp_console_cmd_register(&cmd6));

        const esp_console_cmd_t lan_wifi = {
            .command = "lan_wifi",
            .help = "Save local Wi-Fi credentials: lan_wifi SSID PASSWORD; then reboot",
            .hint = nullptr,
            .func = [](int argc, char** argv) -> int {
                if (argc != 3 || strlen(argv[1]) == 0 || strlen(argv[1]) > 32 ||
                    strlen(argv[2]) < 8 || strlen(argv[2]) > 63)
                    return 1;
                auto& manager = SsidManager::GetInstance();
                manager.AddSsid(argv[1], argv[2]);
                const auto& list = manager.GetSsidList();
                for (int i = 0; i < static_cast<int>(list.size()); ++i) {
                    if (list[i].ssid == argv[1]) {
                        manager.SetDefaultSsid(i);
                        break;
                    }
                }
                printf("LAN_WIFI_SAVED; reboot to connect\n");
                return 0;
            },
            .argtable = nullptr,
        };
        ESP_ERROR_CHECK(esp_console_cmd_register(&lan_wifi));
        const esp_console_cmd_t lan_status = {
            .command = "lan_status",
            .help = "Show local communication status",
            .hint = nullptr,
            .func = [](int, char**) -> int {
                printf("%s\n", GestureService::Instance().Status().c_str());
                return 0;
            },
            .argtable = nullptr,
        };
        ESP_ERROR_CHECK(esp_console_cmd_register(&lan_status));

        esp_console_dev_uart_config_t hw_config = ESP_CONSOLE_DEV_UART_CONFIG_DEFAULT();
        ESP_ERROR_CHECK(esp_console_new_repl_uart(&hw_config, &repl_config, &repl));
        ESP_ERROR_CHECK(esp_console_start_repl(repl));
    }

    void InitializeCamera() {
        ESP_LOGI(TAG, "Initialize Camera");

        // !!!NOTE: SD Card use same SPI bus as sscma client, so we need to disable SD card CS pin
        // first
        const gpio_config_t io_config = {
            .pin_bit_mask = (1ULL << BSP_SD_SPI_CS),
            .mode = GPIO_MODE_OUTPUT,
            .pull_up_en = GPIO_PULLUP_ENABLE,
            .pull_down_en = GPIO_PULLDOWN_DISABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        esp_err_t ret = gpio_config(&io_config);
        if (ret != ESP_OK)
            return;

        gpio_set_level(BSP_SD_SPI_CS, 1);

        GestureService::Instance().Start(false);
        onboard_camera_ = new OnboardCamera(io_exp_handle);
        onboard_camera_->Start();
    }

public:
    SensecapWatcher() {
        // 在网络管理器首次读 NVS 前导入可选源码配置；相同配置不会覆盖串口配网。
        watcher_source_wifi::ApplyCompiled();
        ESP_LOGI(TAG, "Initialize Sensecap Watcher");
        InitializePowerSaveTimer();
        InitializeI2c();
        InitializeSpi();
        InitializeExpander();
        InitializeCmd();  // 工厂生产测试使用
        InitializeButton();
        InitializeKnob();
        Initializespd2010Display();
        GetBacklight()->RestoreBrightness();  // 对于不带摄像头的版本，InitializeCamera需要3s,
                                              // 所以先恢复背光亮度
        InitializeCamera();
        StartPowerMonitor();
    }

    virtual AudioCodec* GetAudioCodec() override {
        static SensecapAudioCodec audio_codec(
            i2c_bus_, AUDIO_INPUT_SAMPLE_RATE, AUDIO_OUTPUT_SAMPLE_RATE, AUDIO_I2S_GPIO_MCLK,
            AUDIO_I2S_GPIO_BCLK, AUDIO_I2S_GPIO_WS, AUDIO_I2S_GPIO_DOUT, AUDIO_I2S_GPIO_DIN,
            AUDIO_CODEC_PA_PIN, AUDIO_CODEC_ES8311_ADDR, AUDIO_CODEC_ES7243E_ADDR,
            AUDIO_INPUT_REFERENCE);
        return &audio_codec;
    }

    virtual Display* GetDisplay() override { return display_; }

    virtual Backlight* GetBacklight() override {
        static PwmBacklight backlight(DISPLAY_BACKLIGHT_PIN, DISPLAY_BACKLIGHT_OUTPUT_INVERT);
        return &backlight;
    }

    // 根据
    // https://github.com/Seeed-Studio/OSHW-SenseCAP-Watcher/blob/main/Hardware/SenseCAP_Watcher_v1.0_SCH.pdf
    // RGB LED型号为 ws2813 mini, 连接在GPIO 40，供电电压 3.3v, 没有连接 BIN 双信号线
    // 可以直接兼容SingleLED采用的ws2812
    virtual Led* GetLed() override {
        static CameraIndicatorLed led(BUILTIN_LED_GPIO);
        return &led;
    }

    virtual void SetPowerSaveLevel(PowerSaveLevel level) override {
        if (level != PowerSaveLevel::LOW_POWER) {
            power_save_timer_->WakeUp();
        }
        // Keep local STOP/ACK latency low during USB-powered communication tests.
        WifiBoard::SetPowerSaveLevel(PowerSaveLevel::PERFORMANCE);
    }

    virtual bool GetBatteryLevel(int& level, bool& charging, bool& discharging) override {
        static bool last_discharging = false;
        charging = (IoExpanderGetLevel(BSP_PWR_VBUS_IN_DET) == 0);
        discharging = !charging;
        level = (int)BatterygetPercent(false);

        if (discharging != last_discharging) {
            power_save_timer_->SetEnabled(
                false);  // Dedicated gesture view; keep automatic low-battery shutdown below.
            last_discharging = discharging;
        }
        if (level <= 1 && discharging) {
            ESP_LOGI(TAG, "Battery level is low, shutting down");
            RequestShutdown();
        }
        return true;
    }

    virtual Camera* GetCamera() override { return camera_; }
};

DECLARE_BOARD(SensecapWatcher);

// 定义静态成员变量
SensecapWatcher* SensecapWatcher::instance_ = nullptr;

bool WatcherShowGesturePresentation(DisplaySnapshot snapshot) {
    auto& board = Board::GetInstance();
    auto* display = static_cast<CustomLcdDisplay*>(board.GetDisplay());
    if (!display) return false;
    int battery; bool charging, discharging;
    if (snapshot.power == GesturePowerState::Active &&
        board.GetBatteryLevel(battery, charging, discharging)) {
        snapshot.battery_percent = battery;
        snapshot.charging = charging;
    }
    // Battery reads can initiate low-battery shutdown. Never resurrect a stale
    // Active snapshot or restore brightness after that guard has been set.
    snapshot.power = GestureService::Instance().PowerState();
    if (!display->SetGesturePresentation(snapshot)) return false;
    return true;
}
