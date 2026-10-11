#!/bin/sh
# No hardware access; artifacts stay under work/.
set -eu
CONTROL_TEST_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CONTROL_WORKSPACE=$(CDPATH= cd -- "$CONTROL_TEST_DIR/../../.." && pwd)
CONTROL_BUILD_DIR="$CONTROL_WORKSPACE/work/control-v8/node-tests/official"
mkdir -p "$CONTROL_BUILD_DIR"
for CONTROL_TEST_NAME in node_state node_event node_portal node_controller node_deadline node_handshake_hold node_hold_controller; do
  c++ -std=c++17 -Wall -Wextra -I"$CONTROL_TEST_DIR/node_stubs" "$CONTROL_TEST_DIR/${CONTROL_TEST_NAME}_test.cpp" -o "$CONTROL_BUILD_DIR/$CONTROL_TEST_NAME"
  "$CONTROL_BUILD_DIR/$CONTROL_TEST_NAME"
done
