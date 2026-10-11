#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

// Fixed memory, newline framing; discard an oversized line through its newline.
class StopLineParser {
    char buffer_[128] = {};
    size_t length_ = 0;
    bool dropping_ = false;
    bool ready_ = false;
    bool carriage_ = false;

public:
    bool Feed(char ch) {
        if (ready_) {
            length_ = 0;
            ready_ = false;
            carriage_ = false;
        }
        if (ch == '\n') {
            if (dropping_) {
                dropping_ = false;
                carriage_ = false;
                length_ = 0;
                return false;
            }
            buffer_[length_] = 0;
            ready_ = true;
            return length_ > 0;
        }
        if (dropping_)
            return false;
        if (carriage_ || static_cast<unsigned char>(ch) < 32 ||
            static_cast<unsigned char>(ch) > 126) {
            if (ch == '\r' && !carriage_) {
                carriage_ = true;
                return false;
            }
            dropping_ = true;
            length_ = 0;
            return false;
        }
        if (length_ == sizeof(buffer_) - 1) {
            dropping_ = true;
            length_ = 0;
            return false;
        }
        buffer_[length_++] = ch;
        return false;
    }
    const char* Line() const { return buffer_; }
};
inline bool ParseSequence(const char* line, const char* prefix, uint32_t& value) {
    const size_t count = strlen(prefix);
    if (strncmp(line, prefix, count) != 0 || line[count] == 0)
        return false;
    uint32_t result = 0;
    for (const char* p = line + count; *p; ++p) {
        if (*p < '0' || *p > '9')
            return false;
        uint32_t digit = static_cast<uint32_t>(*p - '0');
        if (result > (UINT32_MAX - digit) / 10)
            return false;
        result = result * 10 + digit;
    }
    value = result;
    return true;
}
inline bool ParseStop(const char* line, uint32_t& value) {
    return ParseSequence(line, "STOP ", value);
}
inline bool ParseAck(const char* line, uint32_t& value) {
    return ParseSequence(line, "ACK ", value);
}
