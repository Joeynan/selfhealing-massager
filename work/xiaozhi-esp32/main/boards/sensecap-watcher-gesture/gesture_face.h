#pragma once

#include "gesture_ui.h"

// Only renders a caller-owned snapshot; never changes motion or source state.
bool WatcherShowGesturePresentation(DisplaySnapshot snapshot);
