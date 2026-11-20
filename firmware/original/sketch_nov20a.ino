#include <Arduino.h>

#define ENABLE_WIFI false

#if ENABLE_WIFI
  #include <WiFi.h>
  #include <HTTPClient.h>
  const char* WIFI_SSID   = "YOUR_WIFI_NAME";
  const char* WIFI_PASS   = "YOUR_WIFI_PASSWORD";
  const char* SERVER_URL  = "http://192.168.1.10:3000/api/sensors/readings";
  const char* DEVICE_ID   = "ESP32_GARDEN_01";
  const char* DEVICE_KEY  = "YOUR_DEVICE_KEY";
  const unsigned long REPORT_INTERVAL_MS = 15000;
#endif

const int PROBE_PIN = 32;
const int PUMP_PIN  = 26;
const int VALVE_PIN = 27;

const int DRY_VALUE = 3000;
const int WET_VALUE = 1300;

const int RAW_MIN = 200;
const int RAW_MAX = 4000;

const int START_BELOW = 40;
const int STOP_ABOVE  = 60;
const unsigned long MAX_RUN_MS       = 30000;
const unsigned long COOLDOWN_MS      = 60000;
const unsigned long VALVE_LEAD_MS    = 500;
const unsigned long READ_INTERVAL_MS = 1000;
const int SAMPLES = 10;
const int MAX_TIMEOUT_RUNS = 3;

enum State { IDLE, VALVE_OPENING, RUNNING, PUMP_STOPPING };
State state = IDLE;

unsigned long stateStart = 0;
unsigned long runStart   = 0;
unsigned long lastStop   = 0;
unsigned long lastRead   = 0;
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
    delay(2);
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
      if (now - runStart >= MAX_RUN_MS) {
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
      manualRequest = true;  autoMode = false;
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
                "\"temperature\":null,\"humidity\":null,"
                "\"nitrogen\":null,\"phosphorus\":null,\"potassium\":null,"
                "\"rainfall\":null,\"water_level\":null,\"battery_percentage\":null},"
                "\"irrigation\":{\"state\":\"" + String(stateName()) + "\","
                "\"mode\":\"" + String(modeName()) + "\"}}";

  HTTPClient http;
  http.setTimeout(3000);
  http.begin(SERVER_URL);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Key", DEVICE_KEY);
  int code = http.POST(body);
  Serial.print("[WiFi] POST status: ");
  Serial.println(code);
  http.end();
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
  Serial.println("GARDEKALINGA firmware - 1 probe");
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
#endif
}