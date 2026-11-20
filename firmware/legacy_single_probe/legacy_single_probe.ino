/*
  GARDEKALINGA - original 1-probe sketch (sketch_nov20a.ino), version 1.1
  ======================================================================
  Same heart as the group's sketch: one probe on GPIO32, the IDLE ->
  VALVE_OPENING -> RUNNING -> PUMP_STOPPING state machine, 30 s max run,
  60 s cooldown, 3 timeouts lock auto mode, serial commands 1 / 0 / a.

  What changed for the web system (Vercel or Docker):
    * HTTPS with the pinned Let's Encrypt roots (certs.h); http:// still works on a LAN
    * reports to /api/sensors/readings (enable GK_LEGACY_DEVICE_API=true on the server)
      with the raw ADC value, the irrigation state and the time left
    * polls /api/sensors/commands every 3 s, so "Water now" and "Stop watering"
      on the dashboard work with this hardware too, and acknowledges each command

  This is a bridge while Box B is wired for three probes. The full firmware is
  firmware/gardekalinga_node (paper pin map, HMAC signing, offline fail-safe...).

  PIN NOTE: this sketch keeps the ORIGINAL wiring (pump on GPIO26, valve on GPIO27).
  The paper's map is valve K1 = GPIO26, pump K2 = GPIO27. Rewire before moving to
  the full firmware.

  Register the device and get its key on the server:  make register-device
  then paste the 64-character secret below as DEVICE_KEY.
*/
#include <Arduino.h>

#define ENABLE_WIFI true

#if ENABLE_WIFI
  #include <WiFi.h>
  #include <WiFiClientSecure.h>
  #include <HTTPClient.h>
  #include "certs.h"
  const char* WIFI_SSID   = "YOUR_WIFI_NAME";
  const char* WIFI_PASS   = "YOUR_WIFI_PASSWORD";
  // Your deployment, no trailing slash: https://your-app.vercel.app or http://192.168.1.10
  const char* SERVER_BASE = "https://your-app.vercel.app";
  const char* DEVICE_ID   = "gk-node-01";
  const char* DEVICE_KEY  = "PASTE_THE_64_CHARACTER_DEVICE_SECRET";
  const unsigned long REPORT_INTERVAL_MS = 15000;
  const unsigned long POLL_INTERVAL_MS   = 3000;
#endif

const int PROBE_PIN = 32;
const int PUMP_PIN  = 26;   // original wiring (see PIN NOTE above)
const int VALVE_PIN = 27;

const int DRY_VALUE = 3000;
const int WET_VALUE = 1300;

const int RAW_MIN = 205;    // paper: below 5 % of 0-4095 is a sensor fault
const int RAW_MAX = 3890;   // paper: above 95 %

const int START_BELOW = 40;
const int STOP_ABOVE  = 60;
const unsigned long MAX_RUN_MS       = 30000;
const unsigned long COOLDOWN_MS      = 60000;
const unsigned long VALVE_LEAD_MS    = 500;
const unsigned long READ_INTERVAL_MS = 1000;
const int SAMPLES = 64;     // paper: 64 samples per reading
const int MAX_TIMEOUT_RUNS = 3;

enum State { IDLE, VALVE_OPENING, RUNNING, PUMP_STOPPING };
State state = IDLE;

unsigned long stateStart = 0;
unsigned long runStart   = 0;
unsigned long lastStop   = 0;
unsigned long lastRead   = 0;
unsigned long manualRunMs = MAX_RUN_MS;  // length asked for by the dashboard
long  activeCommandId = -1;
bool hasRun         = false;
bool autoMode       = true;
bool manualRequest  = false;
bool sensorFault    = false;
int  rawValue       = 0;
int  moisture       = 0;
int  timeoutRuns    = 0;

void pumpOn(bool on)  { digitalWrite(PUMP_PIN,  on ? LOW : HIGH); }
void valveOn(bool on) { digitalWrite(VALVE_PIN, on ? LOW : HIGH); }

const char* stateName() {
  switch (state) {
    case IDLE:          return "IDLE";
    case VALVE_OPENING: return "VALVE_OPENING";
    case RUNNING:       return "RUNNING";
    default:            return "STOPPING";
  }
}

const char* modeName() {
  if (manualRequest) return "MANUAL_ON";
  return autoMode ? "AUTO" : "OFF";
}

bool autoLocked() {
  return timeoutRuns >= MAX_TIMEOUT_RUNS;
}

int readAverage() {
  long total = 0;
  for (int i = 0; i < SAMPLES; i++) {
    total += analogRead(PROBE_PIN);
  }
  return total / SAMPLES;
}

void readSensor() {
  rawValue    = readAverage();
  sensorFault = (rawValue < RAW_MIN || rawValue > RAW_MAX);
  moisture    = constrain(map(rawValue, DRY_VALUE, WET_VALUE, 0, 100), 0, 100);
}

void beginIrrigation() {
  valveOn(true);
  state = VALVE_OPENING;
  stateStart = millis();
  Serial.println(">> Valve opening");
}

void endIrrigation(const char* reason) {
  pumpOn(false);
  state = PUMP_STOPPING;
  stateStart = millis();
  Serial.print(">> Stopping: ");
  Serial.println(reason);
}

unsigned long remainingMs() {
  if (state != RUNNING) return 0;
  unsigned long limit = manualRequest ? min(manualRunMs, MAX_RUN_MS) : MAX_RUN_MS;
  unsigned long ran = millis() - runStart;
  return ran >= limit ? 0 : limit - ran;
}

void runStateMachine() {
  unsigned long now = millis();

  switch (state) {
    case IDLE: {
      bool cooldownOk = !hasRun || (now - lastStop >= COOLDOWN_MS);
      bool autoWants  = autoMode && !sensorFault && moisture < START_BELOW && cooldownOk;
      if (manualRequest || autoWants) beginIrrigation();
      break;
    }

    case VALVE_OPENING:
      if (now - stateStart >= VALVE_LEAD_MS) {
        pumpOn(true);
        runStart = now;
        state = RUNNING;
        Serial.println(">> Pump running");
      }
      break;

    case RUNNING: {
      bool wantOn = manualRequest ||
                    (autoMode && !sensorFault && moisture < STOP_ABOVE);
      if (manualRequest && now - runStart >= min(manualRunMs, MAX_RUN_MS)) {
        // A dashboard run of N seconds is over (never longer than MAX_RUN_MS).
        manualRequest = false;
        endIrrigation(manualRunMs >= MAX_RUN_MS ? "max runtime reached" : "dashboard run finished");
      } else if (now - runStart >= MAX_RUN_MS) {
        if (!manualRequest) timeoutRuns++;
        manualRequest = false;
        endIrrigation("max runtime reached");
        if (autoLocked()) {
          autoMode = false;
          Serial.print("!! WARNING: ");
          Serial.print(timeoutRuns);
          Serial.println(" runs in a row hit the max runtime. Auto mode switched OFF.");
          Serial.println("!! Check that the probe is in the soil and wired, then send 'a' to resume.");
        } else {
          autoMode = true;
        }
      } else if (!wantOn) {
        if (sensorFault) {
          endIrrigation("sensor fault");
        } else if (!autoMode) {
          endIrrigation("switched off");
        } else {
          timeoutRuns = 0;
          endIrrigation("target moisture reached");
        }
      }
      break;
    }

    case PUMP_STOPPING:
      if (now - stateStart >= VALVE_LEAD_MS) {
        valveOn(false);
        lastStop = now;
        hasRun = true;
        state = IDLE;
        Serial.println(">> Valve closed. Idle.");
      }
      break;
  }
}

void handleSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '1') {
      manualRequest = true;  autoMode = false;  manualRunMs = MAX_RUN_MS;
      Serial.println("[CMD] manual ON");
    } else if (c == '0') {
      manualRequest = false; autoMode = false;
      Serial.println("[CMD] OFF (auto disabled)");
      if (state == RUNNING || state == VALVE_OPENING) endIrrigation("operator stop");
    } else if (c == 'a') {
      manualRequest = false; autoMode = true;
      timeoutRuns = 0;
      Serial.println("[CMD] automatic mode");
    }
  }
}

#if ENABLE_WIFI
WiFiClientSecure tls;
WiFiClient plain;

bool beginRequest(HTTPClient& http, const String& path) {
  String url = String(SERVER_BASE) + path;
  http.setTimeout(2500);         // keep the loop responsive: the state machine waits for us
  http.setConnectTimeout(2500);
  bool ok = url.startsWith("https") ? http.begin(tls, url) : http.begin(plain, url);
  if (ok) http.addHeader("X-Device-Key", DEVICE_KEY);
  return ok;
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Connecting to Wi-Fi");
  unsigned long t = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t < 10000) {
    delay(500);
    Serial.print(".");
  }
  Serial.println(WiFi.status() == WL_CONNECTED ? " connected" : " failed (will retry)");
  tls.setCACert(GK_ISRG_ROOTS_PEM);
}

void reportWiFi() {
  static unsigned long last = 0;
  if (millis() - last < REPORT_INTERVAL_MS) return;
  last = millis();

  if (WiFi.status() != WL_CONNECTED) {
    WiFi.reconnect();
    return;
  }

  String body = "{\"device_id\":\"" + String(DEVICE_ID) + "\","
                "\"readings\":{"
                "\"soil_moisture\":" + (sensorFault ? String("null") : String(moisture)) + ","
                "\"raw_adc\":" + String(rawValue) + ","
                "\"temperature\":null,\"humidity\":null},"
                "\"irrigation\":{\"state\":\"" + String(stateName()) + "\","
                "\"mode\":\"" + String(modeName()) + "\","
                "\"remaining_s\":" + String(remainingMs() / 1000) + "}}";

  HTTPClient http;
  if (!beginRequest(http, "/api/sensors/readings")) return;
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(body);
  Serial.print("[WiFi] POST status: ");
  Serial.println(code);
  http.end();
}

void ackCommand(long id, bool executed, const char* reason) {
  HTTPClient http;
  if (!beginRequest(http, "/api/sensors/commands/" + String(id) + "/ack?device_id=" + DEVICE_ID)) return;
  http.addHeader("Content-Type", "application/json");
  String body = String("{\"status\":\"") + (executed ? "executed" : "rejected") + "\"" +
                (reason ? String(",\"reason\":\"") + reason + "\"" : String("")) + "}";
  http.POST(body);
  http.end();
}

// Tiny parser for {"t":"...","cmd":[{"id":12,"op":"start","d":120}]}; enough for this bridge.
long jsonNumberAfter(const String& s, const String& key, int from) {
  int k = s.indexOf("\"" + key + "\":", from);
  if (k < 0) return -1;
  return s.substring(k + key.length() + 3).toInt();
}

void pollCommands() {
  static unsigned long last = 0;
  if (millis() - last < POLL_INTERVAL_MS || WiFi.status() != WL_CONNECTED) return;
  last = millis();
  HTTPClient http;
  if (!beginRequest(http, String("/api/sensors/commands?device_id=") + DEVICE_ID)) return;
  int code = http.GET();
  String resp = code == 200 ? http.getString() : String();
  http.end();
  int pos = resp.indexOf("\"cmd\"");
  while (pos >= 0) {
    int idPos = resp.indexOf("\"id\":", pos);
    if (idPos < 0) break;
    long id = jsonNumberAfter(resp, "id", pos);
    int opPos = resp.indexOf("\"op\":\"", idPos);
    String op = opPos >= 0 ? resp.substring(opPos + 6, resp.indexOf('"', opPos + 6)) : "";
    long d = jsonNumberAfter(resp, "d", idPos);
    int next = resp.indexOf("}", idPos);
    if (id <= 0 || id == activeCommandId) { pos = next > 0 ? resp.indexOf("\"id\":", next) : -1; continue; }
    activeCommandId = id;
    if (op == "start") {
      if (state != IDLE) {
        ackCommand(id, false, "already_watering");
      } else {
        manualRequest = true;
        manualRunMs = d > 0 ? (unsigned long)d * 1000UL : MAX_RUN_MS;
        Serial.print("[DASHBOARD] start for ");
        Serial.print(manualRunMs / 1000);
        Serial.println(" s (max time still applies)");
        ackCommand(id, true, nullptr);
      }
    } else if (op == "stop") {
      manualRequest = false;
      if (state == RUNNING || state == VALVE_OPENING) endIrrigation("dashboard stop");
      ackCommand(id, true, nullptr);
    } else {
      ackCommand(id, false, "unsupported");
    }
    pos = next > 0 ? resp.indexOf("\"id\":", next) : -1;
  }
}
#endif

void setup() {
  digitalWrite(PUMP_PIN, HIGH);
  digitalWrite(VALVE_PIN, HIGH);
  pinMode(PUMP_PIN, OUTPUT);
  pinMode(VALVE_PIN, OUTPUT);

  Serial.begin(115200);
  delay(300);
  analogSetPinAttenuation(PROBE_PIN, ADC_11db);

  Serial.println();
  Serial.println("GARDEKALINGA firmware - 1 probe (bridge v1.1)");
  Serial.println("Commands: 1 = manual ON, 0 = OFF/stop, a = auto");

#if ENABLE_WIFI
  connectWiFi();
#endif

  readSensor();
}

void loop() {
  handleSerial();

  if (millis() - lastRead >= READ_INTERVAL_MS) {
    lastRead = millis();
    readSensor();

    Serial.print("Raw: ");       Serial.print(rawValue);
    Serial.print("  Moisture: "); Serial.print(sensorFault ? -1 : moisture);
    Serial.print("%  State: ");   Serial.print(stateName());
    Serial.print("  Mode: ");     Serial.print(modeName());
    if (sensorFault) Serial.print("  [SENSOR FAULT]");
    if (autoLocked()) Serial.print("  [AUTO LOCKED - check probe]");
    Serial.println();
  }

  runStateMachine();

#if ENABLE_WIFI
  reportWiFi();
  pollCommands();
#endif
}
