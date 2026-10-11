#pragma once
#include "ESP8266WiFi.h"
#include <map>
constexpr int HTTP_GET = 0, HTTP_POST = 1, DIGEST_AUTH = 2;
struct ESP8266WebServer {
  bool authenticated = false; int status = 0; std::string body; std::map<std::string,std::string> args;
  explicit ESP8266WebServer(int) {}
  bool authenticate(const char*, const char*) { return authenticated; }
  void requestAuthentication(int, const char*, const char*) { status = 401; }
  String arg(const char* key) { return args[key]; }
  void sendHeader(const char*, const char*) {}
  void send(int code, const char*, const String& message) { status = code; body = message.c_str(); }
  template<typename T> void on(const char*, int, T) {} template<typename T> void onNotFound(T) {}
  void begin() {} void handleClient() {}
};
