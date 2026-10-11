#pragma once
#include <stdint.h>
inline uint32_t os_random() { static uint32_t value = 123456; value = value * 1664525u + 1013904223u; return value; }
