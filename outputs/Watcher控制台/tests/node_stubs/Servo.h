#pragma once
struct Servo {
  bool active = false; int pulse = 0, pin = -1;
  bool attached() const { return active; }
  void attach(int selected, int, int, int neutral) { pin = selected; pulse = neutral; active = true; }
  void detach() { active = false; }
  void writeMicroseconds(int value) { if (active) pulse = value; }
};
