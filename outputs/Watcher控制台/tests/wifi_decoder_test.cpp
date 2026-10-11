#include <cassert>
#include <string>
#include "../firmware/watcher-service/wifi_frame_decoder.h"
int main() {
    const std::string prefix =
        "{\"type\":0,\"code\":0,\"name\":\"FRAME\",\"data\":{\"version\":1,\"session\":42,\"frame_"
        "id\":1,\"capture_ms\":500,\"send_ms\":520,\"width\":416,\"height\":416,\"image\":\"";
    wifi_camera::Frame frame;
    auto decode = [&](std::string image, uint32_t now = 1050) {
        auto* j = cJSON_Parse((prefix + image + "\"}}").c_str());
        bool ok = wifi_camera::Decode(j, 42, 1000, now, frame);
        cJSON_Delete(j);
        return ok;
    };
    assert(decode("/9j/2Q=="));
    assert(frame.jpeg.size() == 4 && frame.captured == 980);
    assert(!decode("/9j/2Q==", 1780));  // exact800 budget
    assert(!decode("/9j/2Q==AAAA"));
    assert(!decode("/9j/2R=="));  // noncanonical pad
    assert(!decode("/9j/2Q=A"));
    assert(!decode("/9j/AA=="));
    assert(!decode("!!!!"));
    assert(!decode(std::string(131076, 'A')));
    auto wrong = prefix;
    wrong.replace(wrong.find("42"), 2, "43");
    auto* j = cJSON_Parse((wrong + "/9j/2Q==\"}}").c_str());
    assert(!wifi_camera::Decode(j, 42, 1000, 1050, frame));
    cJSON_Delete(j);
}
