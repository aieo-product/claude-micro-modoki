#include <M5Unified.h>
// FastLED by FastLED
#include <FastLED.h>
#include <WiFi.h>
// WebSockets by Markus Sattler
#include <WebSocketsClient.h>
// ArduinoJson by bblanchon
#include <ArduinoJson.h>

// ---- User configuration: replace before flashing ----
static const char* WIFI_SSID = "YOUR_WIFI_SSID";
static const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
static const char* BRIDGE_HOST_IP = "192.168.0.100";  // IP of the PC running bridge.py
static const uint16_t BRIDGE_WS_PORT = 35704;          // bridge.py's bridge_port + 1
// -------------------------------------------------------

static const int NUM_LEDS = 10;
static const int LED_PIN = 25;
static const unsigned long REQUEST_TIMEOUT_MS = 240000UL;  // 4 minutes
static const unsigned long RESULT_FLASH_MS = 1500UL;
static const unsigned long BLINK_INTERVAL_MS = 400UL;
static const unsigned long AUTO_SCREEN_DURATION_MS = 15000UL;  // auto mode: hide after 15s

CRGB leds[NUM_LEDS];
WebSocketsClient webSocket;

enum LedState {
  LED_BOOT,
  LED_IDLE,
  LED_PENDING,
  LED_RESULT_ACCEPT,
  LED_RESULT_HOLD,
  LED_RESULT_DENY,
  LED_RESULT_TIMEOUT,
  LED_DISCONNECTED
};

LedState ledState = LED_BOOT;
bool ledBlinkOn = false;
unsigned long lastBlinkToggle = 0;
unsigned long resultFlashUntil = 0;

bool wsConnected = false;
bool requestPending = false;
unsigned long requestStartMillis = 0;
String pendingDescription;
String pendingCommand;
int lastBarWidth = -1;

bool autoMode = false;
bool autoScreenActive = false;
unsigned long autoClearAt = 0;

// ---------- Forward declarations ----------
void drawIdleScreen();
void drawDisconnectedScreen();
void drawPendingScreen();

// ---------- LED ----------

void setLedState(LedState state) {
  ledState = state;
  if (state == LED_RESULT_ACCEPT || state == LED_RESULT_HOLD ||
      state == LED_RESULT_DENY || state == LED_RESULT_TIMEOUT) {
    resultFlashUntil = millis() + RESULT_FLASH_MS;
  }
}

CRGB colorForState(LedState state) {
  switch (state) {
    case LED_BOOT:           return CRGB(80, 40, 0);   // orange
    case LED_IDLE:            return CRGB(0, 0, 40);    // dim blue
    case LED_PENDING:         return CRGB(80, 60, 0);   // yellow
    case LED_RESULT_ACCEPT:   return CRGB(0, 80, 0);    // green
    case LED_RESULT_HOLD:     return CRGB(60, 0, 80);   // purple
    case LED_RESULT_DENY:     return CRGB(80, 0, 0);    // red
    case LED_RESULT_TIMEOUT:  return CRGB(80, 80, 80);  // white
    case LED_DISCONNECTED:    return CRGB(80, 40, 0);   // orange
  }
  return CRGB::Black;
}

bool stateBlinks(LedState state) {
  return state == LED_BOOT || state == LED_PENDING || state == LED_DISCONNECTED;
}

void updateLeds() {
  // Result flashes auto-expire back to idle/pending/disconnected.
  if (resultFlashUntil != 0 && millis() > resultFlashUntil) {
    resultFlashUntil = 0;
    if (requestPending) {
      ledState = LED_PENDING;
      drawPendingScreen();
    } else if (wsConnected) {
      ledState = LED_IDLE;
      drawIdleScreen();
    } else {
      ledState = LED_DISCONNECTED;
      drawDisconnectedScreen();
    }
  }

  if (millis() - lastBlinkToggle > BLINK_INTERVAL_MS) {
    lastBlinkToggle = millis();
    ledBlinkOn = !ledBlinkOn;
  }

  CRGB color = colorForState(ledState);
  bool on = !stateBlinks(ledState) || ledBlinkOn;
  for (int i = 0; i < NUM_LEDS; i++) {
    leds[i] = on ? color : CRGB::Black;
  }
  FastLED.show();
}

// ---------- Display ----------

void drawIdleScreen() {
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setTextSize(2);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5.Display.setCursor(10, 10);
  M5.Display.println("Claude Code Approval");
  M5.Display.setTextSize(1);
  M5.Display.setCursor(10, 40);
  M5.Display.println("Connected - waiting for requests...");
  lastBarWidth = -1;
}

void drawDisconnectedScreen() {
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setTextSize(2);
  M5.Display.setTextColor(TFT_ORANGE, TFT_BLACK);
  M5.Display.setCursor(10, 10);
  M5.Display.println("Disconnected");
  M5.Display.setTextSize(1);
  M5.Display.setCursor(10, 40);
  M5.Display.println("Connecting to bridge...");
  lastBarWidth = -1;
}

void drawButtonLabels() {
  int w = M5.Display.width();
  M5.Display.setTextSize(2);
  M5.Display.setTextColor(TFT_GREEN, TFT_BLACK);
  M5.Display.drawCenterString("Accept", w / 6, 215);
  M5.Display.setTextColor(TFT_MAGENTA, TFT_BLACK);
  M5.Display.drawCenterString("Hold", w / 2, 215);
  M5.Display.setTextColor(TFT_RED, TFT_BLACK);
  M5.Display.drawCenterString("Deny", w * 5 / 6, 215);
}

void drawAutoScreen() {
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setTextSize(2);
  M5.Display.setTextColor(TFT_YELLOW, TFT_BLACK);
  M5.Display.setTextWrap(true);
  M5.Display.setCursor(10, 100);
  M5.Display.println(pendingDescription);
  lastBarWidth = -1;
}

void clearAutoScreen() {
  M5.Display.fillScreen(TFT_BLACK);
}

void drawPendingScreen() {
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setTextSize(2);
  M5.Display.setTextColor(TFT_YELLOW, TFT_BLACK);
  M5.Display.setCursor(10, 5);
  M5.Display.println("APPROVAL REQUESTED");

  M5.Display.setTextSize(1);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5.Display.setTextWrap(true);
  M5.Display.setCursor(10, 35);
  M5.Display.println(pendingDescription);

  M5.Display.setTextColor(TFT_CYAN, TFT_BLACK);
  M5.Display.setCursor(10, 90);
  M5.Display.println(pendingCommand);

  M5.Display.drawRect(10, 190, M5.Display.width() - 20, 16, TFT_WHITE);
  drawButtonLabels();
  lastBarWidth = -1;
}

void drawResultScreen(const char* text, uint16_t color) {
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setTextSize(3);
  M5.Display.setTextColor(color, TFT_BLACK);
  M5.Display.drawCenterString(text, M5.Display.width() / 2, M5.Display.height() / 2 - 12);
}

void updateCountdownBar() {
  unsigned long elapsed = millis() - requestStartMillis;
  if (elapsed > REQUEST_TIMEOUT_MS) elapsed = REQUEST_TIMEOUT_MS;
  int innerWidth = M5.Display.width() - 24;
  int width = innerWidth - (int)((unsigned long)innerWidth * elapsed / REQUEST_TIMEOUT_MS);
  if (width == lastBarWidth) return;
  M5.Display.fillRect(12, 192, innerWidth, 12, TFT_BLACK);
  if (width > 0) {
    M5.Display.fillRect(12, 192, width, 12, TFT_GREEN);
  }
  lastBarWidth = width;
}

// ---------- WebSocket protocol ----------

void sendHello() {
  StaticJsonDocument<64> doc;
  doc["cmd"] = "hello";
  String out;
  serializeJson(doc, out);
  webSocket.sendTXT(out);
}

void sendDecision(const char* result, LedState resultLed, const char* resultText, uint16_t resultColor) {
  StaticJsonDocument<64> doc;
  doc["result"] = result;
  String out;
  serializeJson(doc, out);
  webSocket.sendTXT(out);

  requestPending = false;
  setLedState(resultLed);
  drawResultScreen(resultText, resultColor);
}

void sendAutoAccept() {
  StaticJsonDocument<64> doc;
  doc["result"] = "accept";
  String out;
  serializeJson(doc, out);
  webSocket.sendTXT(out);

  // No manual decision is needed, so requestPending stays false: buttons
  // have no effect while the auto-mode notice is showing.
  ledState = LED_PENDING;
  drawAutoScreen();
  autoClearAt = millis() + AUTO_SCREEN_DURATION_MS;
  autoScreenActive = true;
}

void beepAlert(int times) {
  for (int i = 0; i < times; i++) {
    M5.Speaker.tone(2500, 120);
    delay(180);
  }
}

void handleIncomingMessage(uint8_t* payload, size_t length) {
  StaticJsonDocument<2048> doc;
  DeserializationError err = deserializeJson(doc, payload, length);
  if (err) return;

  const char* eventName = doc["hook_event_name"] | "";
  if (strcmp(eventName, "PreToolUse") != 0) return;

  const char* description = doc["tool_input"]["description"] | "";
  const char* command = doc["tool_input"]["command"] | "";
  pendingDescription = strlen(description) > 0 ? String(description) : String("(no description)");
  pendingCommand = String(command);

  const char* permissionMode = doc["permission_mode"] | "";
  autoMode = (strcmp(permissionMode, "auto") == 0);

  beepAlert(5);

  if (autoMode) {
    sendAutoAccept();
    return;
  }

  requestPending = true;
  requestStartMillis = millis();
  setLedState(LED_PENDING);
  drawPendingScreen();
}

void webSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      wsConnected = true;
      sendHello();
      setLedState(LED_IDLE);
      drawIdleScreen();
      break;
    case WStype_DISCONNECTED:
      wsConnected = false;
      requestPending = false;
      setLedState(LED_DISCONNECTED);
      drawDisconnectedScreen();
      break;
    case WStype_TEXT:
      handleIncomingMessage(payload, length);
      break;
    default:
      break;
  }
}

// ---------- Setup / loop ----------

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setTextSize(2);
  M5.Display.setTextColor(TFT_ORANGE, TFT_BLACK);
  M5.Display.setCursor(10, 10);
  M5.Display.println("Connecting to WiFi...");
  while (WiFi.status() != WL_CONNECTED) {
    updateLeds();
    delay(50);
  }
}

void setup() {
  auto cfg = M5.config();
  M5.begin(cfg);

  FastLED.addLeds<SK6812, LED_PIN, GRB>(leds, NUM_LEDS);
  FastLED.setBrightness(60);

  connectWiFi();

  webSocket.begin(BRIDGE_HOST_IP, BRIDGE_WS_PORT, "/");
  webSocket.onEvent(webSocketEvent);
  webSocket.setReconnectInterval(3000);

  setLedState(LED_DISCONNECTED);
  drawDisconnectedScreen();
}

void loop() {
  M5.update();
  webSocket.loop();
  updateLeds();

  if (autoScreenActive && millis() >= autoClearAt) {
    clearAutoScreen();
    autoScreenActive = false;
    setLedState(wsConnected ? LED_IDLE : LED_DISCONNECTED);
    if (wsConnected) {
      drawIdleScreen();
    } else {
      drawDisconnectedScreen();
    }
  }

  if (requestPending) {
    updateCountdownBar();

    if (M5.BtnA.wasPressed()) {
      sendDecision("accept", LED_RESULT_ACCEPT, "ACCEPTED", TFT_GREEN);
    } else if (M5.BtnB.wasPressed()) {
      sendDecision("fallback", LED_RESULT_HOLD, "HOLD", TFT_MAGENTA);
    } else if (M5.BtnC.wasPressed()) {
      sendDecision("deny", LED_RESULT_DENY, "DENIED", TFT_RED);
    } else if (millis() - requestStartMillis > REQUEST_TIMEOUT_MS) {
      sendDecision("timeout", LED_RESULT_TIMEOUT, "TIMEOUT", TFT_WHITE);
    }
  }
}
