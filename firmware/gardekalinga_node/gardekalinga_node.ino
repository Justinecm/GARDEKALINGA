/*
  GARDEKALINGA field controller (Box B) - ESP32 DevKit V1, Arduino-ESP32 core 3.x.

  Grew out of the group's sketch_nov20a.ino (one probe, IDLE -> VALVE_OPENING ->
  RUNNING -> PUMP_STOPPING, serial commands 1 / 0 / a). Same heart, now built to
  the paper (draft v2):

    * three probes S1/S2/S3, 64 samples at 11 dB, Equation 1 calibration, 5 % / 95 %
      fault filter, Equation 2 spatial mean, reading every 30 min at :00 / :30
    * HTTPS + HMAC-signed requests; POST each reading (2 retries), poll every 3 s
    * four-tier control: (1) max watering time on the node, (2) manual commands,
      (3) server decisions, (4) offline fail-safe from the node's own readings
    * valve 500 ms before pump, pump off before valve, ms timestamps (TC6)
    * offline buffer in RAM mirrored to LittleFS, synced on reconnection
    * 06:00 / 16:00 schedule when every probe is faulty
    * supply-voltage watch every second, 11.6 V / 12.8 V hysteresis (TC12)
    * task watchdog; relays held OFF before the pins become outputs (TC13)
    * setup page (hold BOOT at power-up): Wi-Fi, server, device ID and secret in NVS

  Networking runs on core 0 (netTask); control runs in loop() on core 1, so a slow
  HTTPS call can never delay a relay stop.

  Libraries: ArduinoJson 7 (Library Manager). Everything else ships with the core.
  Serial log lines are CSV-like: <millis>,<EVENT>,key=value,...  (115200 baud)
*/
#include <Arduino.h>
#include <ArduinoJson.h>
#include <DNSServer.h>
#include <HTTPClient.h>
#include <LittleFS.h>
#include <Preferences.h>
#include <WebServer.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <esp_random.h>
#include <esp_system.h>
#include <esp_task_wdt.h>
#include <mbedtls/md.h>
#include <time.h>

#include "certs.h"
#include "config.h"
#include "gk_logic.h"

using namespace gk;

// =============================================================== configuration
struct NodeConfig {
  char ssid[33];
  char pass[65];
  char server[128];  // e.g. https://gardekalinga.vercel.app  (no trailing slash)
  char deviceId[41];
  char secretHex[65];
  uint8_t caMode;  // 0 = pinned ISRG roots, 1 = custom PEM (Caddy internal CA), 2 = plain HTTP (bench only)
};

// Settings pushed by the server (and kept in NVS for the offline fail-safe).
struct NodeSettings {
  uint32_t version;
  float threshold;
  float probeMin;
  uint32_t maxS;
  uint32_t soakS;
  uint32_t gapMs;
  float flowLpm;
  float dailyL;
  uint16_t amMinute;
  uint16_t pmMinute;
  float amShare;
  Calib cal[NUM_PROBES];
};

static const NodeSettings DEFAULT_SETTINGS = {
    0, 30.0f, 22.0f, 180, 1800, 100, 1.5f, 9.0f, 6 * 60, 16 * 60, 0.6f,
    {{3000, 1300, 5.0f, 45.0f}, {3000, 1300, 5.0f, 45.0f}, {3000, 1300, 5.0f, 45.0f}}};

static NodeConfig cfg;
static NodeSettings settings = DEFAULT_SETTINGS;     // owned by the control loop (core 1)
static NodeSettings netSettings = DEFAULT_SETTINGS;  // owned by the net task (core 0)
static volatile bool settingsDirty = false;
static String customCaPem;
static Preferences prefs;
static SemaphoreHandle_t stateMutex;

// =============================================================== shared state
struct ReadingRec {
  char uuid[37];
  uint32_t epoch;  // 0 when the clock is not set yet
  int16_t raw[NUM_PROBES];
  float vwc[NUM_PROBES];
  uint8_t faultBits;
  float mean;
  uint8_t active;
  float supplyV;
  uint8_t source;
  uint8_t mode;  // 0 online, 1 offline_failsafe, 2 sensor_fault
  uint32_t settingsVersion;
};

struct EventRec {
  uint8_t kind;   // 0 = device event, 1 = command acknowledgement
  int32_t ackId;  // command id for kind 1
  char json[EVENT_JSON_MAX];
};

enum CmdOp : uint8_t { CMD_START = 1, CMD_STOP = 2, CMD_READ_NOW = 3, CMD_TEST_HANG = 9 };
struct Command {
  CmdOp op;
  int32_t id;          // dashboard command id, -1 for server decisions
  int32_t decisionId;  // control_decisions id, -1 for commands
  uint32_t durationS;
};

static QueueHandle_t qReadings, qEvents, qCommands, qFailsafe;
static Ring<ReadingRec, BUF_READINGS> bufReadings;
static Ring<EventRec, BUF_EVENTS> bufEvents;
static SemaphoreHandle_t bufMutex;

static volatile bool online = false;
static volatile bool timeSynced = false;
static volatile uint32_t netHeartbeatMs = 0;
static volatile bool localOff = false;  // serial '0' (operator OFF) until 'a'

// Status shared with the 3-second poll.
struct LiveState {
  bool pump, valve;
  Source source;
  float supplyV;
  uint8_t mode;
  uint8_t water;  // 0 none, 1 auto, 2 manual, 3 offline_failsafe, 4 fault schedule
  uint32_t remainingS;
} live = {false, false, Source::UNKNOWN, 0.0f, 0, 0, 0};

// =============================================================== control state
static Actuator act;
static PowerMonitor power;
static FaultScheduler faultSched;
static FaultPlan pendingFault;
static uint8_t pendingFaultIdx = 0;
static uint32_t pendingFaultNextMs = 0;
static uint32_t nextReadingEpoch = 0, nextReadingMs = 0;
static uint32_t lastPowerMs = 0;
static bool hasLastEnd = false;
static uint32_t lastEndUptimeS = 0;
static Evaluated lastEval{};
static bool haveEval = false;
static uint32_t cycleCount = 0;

// =============================================================== small helpers
static void logLine(const char* event, const String& fields = "") {
  Serial.printf("%lu,%s%s%s\n", (unsigned long)millis(), event, fields.length() ? "," : "", fields.c_str());
}

static uint32_t nowEpoch() {
  if (!timeSynced) return 0;
  time_t t = time(nullptr);
  return t > 1600000000 ? (uint32_t)t : 0;
}

// Epoch milliseconds for a millis() timestamp taken earlier.
static uint64_t epochMsAt(uint32_t ms) {
  const uint32_t e = nowEpoch();
  if (!e) return 0;
  struct timeval tv;
  gettimeofday(&tv, nullptr);
  const uint64_t nowMs = (uint64_t)tv.tv_sec * 1000ULL + tv.tv_usec / 1000;
  return nowMs - (uint64_t)(millis() - ms);
}

static String isoFromEpochMs(uint64_t ms) {
  if (!ms) return String();
  time_t s = (time_t)(ms / 1000ULL);
  struct tm t;
  gmtime_r(&s, &t);
  char buf[32];
  snprintf(buf, sizeof buf, "%04d-%02d-%02dT%02d:%02d:%02d.%03uZ", t.tm_year + 1900, t.tm_mon + 1, t.tm_mday, t.tm_hour, t.tm_min,
           t.tm_sec, (unsigned)(ms % 1000ULL));
  return String(buf);
}

static void newUuid(char out[37]) {
  uint8_t b[16];
  esp_fill_random(b, sizeof b);
  b[6] = (b[6] & 0x0F) | 0x40;
  b[8] = (b[8] & 0x3F) | 0x80;
  snprintf(out, 37, "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x", b[0], b[1], b[2], b[3], b[4], b[5], b[6],
           b[7], b[8], b[9], b[10], b[11], b[12], b[13], b[14], b[15]);
}

static const char* modeName(uint8_t m) { return m == 1 ? "offline_failsafe" : m == 2 ? "sensor_fault" : "online"; }

static void setRelays(bool valve, bool pump) {
  // The order matters only at the transitions, which the Actuator enforces.
  digitalWrite(PIN_VALVE, valve ? RELAY_ON : RELAY_OFF);
  digitalWrite(PIN_PUMP, pump ? RELAY_ON : RELAY_OFF);
}

// =============================================================== NVS storage
static void loadConfig() {
  prefs.begin("gk", true);
  memset(&cfg, 0, sizeof cfg);
  if (prefs.getBytesLength("cfg") == sizeof cfg) prefs.getBytes("cfg", &cfg, sizeof cfg);
  if (prefs.getBytesLength("set") == sizeof settings) prefs.getBytes("set", &settings, sizeof settings);
  netSettings = settings;
  customCaPem = prefs.getString("ca", "");
  prefs.end();
}

static void saveConfig() {
  prefs.begin("gk", false);
  prefs.putBytes("cfg", &cfg, sizeof cfg);
  prefs.putString("ca", customCaPem);
  prefs.end();
}

static void saveSettings() {  // net task: its own Preferences handle (NVS itself is thread-safe)
  Preferences p;
  p.begin("gk", false);
  p.putBytes("set", &netSettings, sizeof netSettings);
  p.end();
}

// Remember an open cycle so a power loss or watchdog restart can be reported.
static void markCycleOpen(bool open) {  // control loop
  Preferences p;
  p.begin("gk", false);
  p.putBool("cyc", open);
  p.end();
}

// =============================================================== LittleFS mirror
static void persistBuffers() {
  xSemaphoreTake(bufMutex, portMAX_DELAY);
  File f = LittleFS.open("/buf_r.bin", "w");
  if (f) {
    f.write((const uint8_t*)&bufReadings, sizeof bufReadings);
    f.close();
  }
  File g = LittleFS.open("/buf_e.bin", "w");
  if (g) {
    g.write((const uint8_t*)&bufEvents, sizeof bufEvents);
    g.close();
  }
  xSemaphoreGive(bufMutex);
}

static void restoreBuffers() {
  File f = LittleFS.open("/buf_r.bin", "r");
  if (f && f.size() == sizeof bufReadings) f.read((uint8_t*)&bufReadings, sizeof bufReadings);
  if (f) f.close();
  File g = LittleFS.open("/buf_e.bin", "r");
  if (g && g.size() == sizeof bufEvents) g.read((uint8_t*)&bufEvents, sizeof bufEvents);
  if (g) g.close();
}

// =============================================================== sensing
static int readAverage(int pin) {
  long total = 0;
  for (int i = 0; i < SAMPLES; i++) total += analogRead(pin);  // ~64 x 10 us, no delay()
  return (int)(total / SAMPLES);
}

static float readSupplyVolts() {
  long mv = 0;
  for (int i = 0; i < 16; i++) mv += analogReadMilliVolts(PIN_SUPPLY);
  return supplyFromPin((float)mv / 16.0f / 1000.0f);
}

static ReadingRec takeReading() {
  ReadingRec r{};
  newUuid(r.uuid);
  r.epoch = nowEpoch();
  const int pins[NUM_PROBES] = {PIN_S1, PIN_S2, PIN_S3};
  int raw[NUM_PROBES];
  for (int i = 0; i < NUM_PROBES; i++) raw[i] = readAverage(pins[i]);
  lastEval = evaluate(raw, settings.cal);
  haveEval = true;
  r.faultBits = 0;
  for (int i = 0; i < NUM_PROBES; i++) {
    r.raw[i] = (int16_t)raw[i];
    r.vwc[i] = lastEval.probe[i].vwc;
    if (lastEval.probe[i].fault) r.faultBits |= (1 << i);
  }
  r.mean = lastEval.mean;
  r.active = (uint8_t)lastEval.active;
  r.supplyV = live.supplyV;
  r.source = (uint8_t)power.state;
  r.mode = lastEval.active == 0 ? 2 : (online ? 0 : 1);
  r.settingsVersion = settings.version;
  logLine("READING", String("raw=") + raw[0] + "/" + raw[1] + "/" + raw[2] + ",mean=" + String(r.mean, 1) + ",active=" + r.active +
                         ",mode=" + modeName(r.mode) + ",v=" + String(r.supplyV, 2));
  return r;
}

static void scheduleNextReading() {
  const uint32_t e = nowEpoch();
  if (e) {
    nextReadingEpoch = nextReadingSlot(e);  // align to :00 / :30
    nextReadingMs = millis() + (nextReadingEpoch - e) * 1000UL;
  } else {
    nextReadingEpoch = 0;
    nextReadingMs = millis() + READING_PERIOD_S * 1000UL;
  }
}

// =============================================================== events
static void queueEvent(const JsonDocument& doc) {
  EventRec ev{};
  serializeJson(doc, ev.json, sizeof ev.json);
  if (xQueueSend(qEvents, &ev, 0) != pdTRUE) {  // queue full: straight to the buffer
    xSemaphoreTake(bufMutex, portMAX_DELAY);
    bufEvents.push(ev);
    xSemaphoreGive(bufMutex);
  }
}

static void eventActuation(const Cycle& c) {
  JsonDocument d;
  char u[37];
  newUuid(u);
  d["uuid"] = u;
  d["type"] = "actuation";
  d["trigger_source"] = triggerName(c.trigger);
  if (c.decisionId >= 0) d["decision_id"] = c.decisionId;
  if (c.commandId >= 0) d["command_id"] = c.commandId;
  const String vo = isoFromEpochMs(epochMsAt(c.valveOpenMs));
  if (vo.length()) {
    d["valve_open_at"] = vo;
    d["pump_on_at"] = isoFromEpochMs(epochMsAt(c.pumpOnMs));
    d["pump_off_at"] = isoFromEpochMs(epochMsAt(c.pumpOffMs));
    d["valve_closed_at"] = isoFromEpochMs(epochMsAt(c.valveCloseMs));
  }
  d["interlock_ms"] = c.interlockMs();
  d["close_gap_ms"] = c.closeGapMs();
  d["duration_s"] = c.durationS();
  d["ended_reason"] = endName(c.reason);
  queueEvent(d);
  logLine("CYCLE", String("n=") + cycleCount + ",trigger=" + triggerName(c.trigger) + ",valve_open=" + c.valveOpenMs + ",pump_on=" +
                       c.pumpOnMs + ",pump_off=" + c.pumpOffMs + ",valve_close=" + c.valveCloseMs + ",interlock_ms=" + c.interlockMs() +
                       ",close_gap_ms=" + c.closeGapMs() + ",ended=" + endName(c.reason));
}

static void eventPower(Source from, Source to, float v) {
  JsonDocument d;
  char u[37];
  newUuid(u);
  d["uuid"] = u;
  d["type"] = "power_transition";
  const String at = isoFromEpochMs(epochMsAt(millis()));
  if (at.length()) d["occurred_at"] = at;
  d["from"] = sourceName(from);
  d["to"] = sourceName(to);
  d["supply_v"] = v;
  queueEvent(d);
  logLine("POWER", String("from=") + sourceName(from) + ",to=" + sourceName(to) + ",v=" + String(v, 2));
}

static const char* resetReasonName(esp_reset_reason_t r) {
  switch (r) {
    case ESP_RST_POWERON: return "POWERON";
    case ESP_RST_EXT: return "EXT";
    case ESP_RST_SW: return "SW";
    case ESP_RST_PANIC: return "PANIC";
    case ESP_RST_INT_WDT: return "INT_WDT";
    case ESP_RST_TASK_WDT: return "TASK_WDT";
    case ESP_RST_WDT: return "WDT";
    case ESP_RST_DEEPSLEEP: return "DEEPSLEEP";
    case ESP_RST_BROWNOUT: return "BROWNOUT";
    case ESP_RST_SDIO: return "SDIO";
    default: return "UNKNOWN";
  }
}

// =============================================================== control (core 1)
static void startCycle(uint32_t seconds, Trigger t, int32_t decisionId, int32_t commandId) {
  if (act.start(millis(), seconds, settings.maxS, t, decisionId, commandId)) {
    cycleCount++;
    markCycleOpen(true);
    logLine("VALVE_OPEN", String("trigger=") + triggerName(t) + ",run_s=" + act.cycle().runS);
  }
}

static void handleCommand(const Command& c) {
  JsonDocument ack;
  bool ok = true;
  const char* reason = nullptr;
  if (c.op == CMD_START) {
    if (act.busy()) {
      ok = false;
      reason = "already_watering";
    } else if (c.id < 0 && localOff) {
      ok = false;
      reason = "operator_off";
    } else {
      startCycle(c.durationS, c.id >= 0 ? Trigger::MANUAL : Trigger::AUTO, c.decisionId, c.id);
    }
  } else if (c.op == CMD_STOP) {
    act.stop(millis(), EndReason::MANUAL_STOP);
    pendingFault.runs = 0;  // a person said stop: drop the rest of a split schedule run
  } else if (c.op == CMD_READ_NOW) {
    ReadingRec r = takeReading();  // does not move the 30-minute schedule
    JsonDocument d;
    char u[37];
    newUuid(u);
    d["uuid"] = u;
    d["type"] = "read_now";
    JsonArray probes = d["data"]["probes"].to<JsonArray>();
    const char* ids[3] = {"S1", "S2", "S3"};
    for (int i = 0; i < NUM_PROBES; i++) {
      JsonObject p = probes.add<JsonObject>();
      p["id"] = ids[i];
      p["raw"] = r.raw[i];
      if (r.faultBits & (1 << i)) p["vwc"] = nullptr;
      else p["vwc"] = r.vwc[i];
      p["fault"] = (bool)(r.faultBits & (1 << i));
    }
    queueEvent(d);
#ifdef GK_TEST_HANG
  } else if (c.op == CMD_TEST_HANG) {
    logLine("TEST_HANG", "stop feeding the watchdog");
    act.stop(millis(), EndReason::WATCHDOG);
    setRelays(false, false);
    while (true) { /* TC13: the task watchdog restarts the node; NC valve keeps water off */ }
#endif
  } else {
    ok = false;
    reason = "unsupported";
  }
  if (c.id >= 0) {  // dashboard commands are acknowledged (FR-COM-05)
    ack["status"] = ok ? "executed" : "rejected";
    if (reason) ack["reason"] = reason;
    const String at = isoFromEpochMs(epochMsAt(millis()));
    if (at.length()) ack["at"] = at;
    EventRec ev{};
    ev.kind = 1;
    ev.ackId = c.id;
    serializeJson(ack, ev.json, sizeof ev.json);
    xQueueSend(qEvents, &ev, 0);
  }
}

static void runFailSafe(const ReadingRec& r) {
  if (localOff) return;
  Evaluated e{};
  e.mean = r.mean;
  e.active = r.active;
  for (int i = 0; i < NUM_PROBES; i++) {
    e.probe[i].fault = r.faultBits & (1 << i);
    e.probe[i].vwc = r.vwc[i];
  }
  const FailSafeParams p{settings.threshold, settings.probeMin, settings.soakS};
  const uint32_t up = millis() / 1000UL;
  if (failSafeShouldWater(e, p, act.busy(), hasLastEnd, up, lastEndUptimeS)) {
    logLine("FAILSAFE", String("mean=") + String(r.mean, 1));
    startCycle(settings.maxS, Trigger::OFFLINE_FAILSAFE, -1, -1);
  }
}

static void runFaultSchedule() {
  // A split run continues after the soak interval.
  if (pendingFault.runs && pendingFaultIdx < pendingFault.runs && !act.busy() && (int32_t)(millis() - pendingFaultNextMs) >= 0) {
    startCycle(pendingFault.runS[pendingFaultIdx], Trigger::FAULT_SCHEDULE, -1, -1);
    pendingFaultIdx++;
    pendingFaultNextMs = millis() + (pendingFault.runS[pendingFaultIdx - 1] + settings.soakS) * 1000UL;
    if (pendingFaultIdx >= pendingFault.runs) pendingFault.runs = 0;
    return;
  }
  if (!haveEval || lastEval.active > 0 || localOff) return;
  int due = 0;
  const uint32_t e = nowEpoch();
  if (e) {
    const uint32_t local = e + 8 * 3600;  // Asia/Manila, UTC+8, no DST
    due = faultSched.dueByClock((int32_t)(local / 86400UL), (int)((local % 86400UL) / 60UL), settings.amMinute, settings.pmMinute);
  } else {
    due = faultSched.dueByBoot(millis() / 1000UL);
  }
  if (!due) return;
  const float share = due == 1 ? settings.amShare : 1.0f - settings.amShare;
  pendingFault = planFaultRuns(share, settings.dailyL, settings.flowLpm, settings.maxS);
  pendingFaultIdx = 0;
  pendingFaultNextMs = millis();
  logLine("FAULT_SCHEDULE", String("slot=") + (due == 1 ? "am" : "pm") + ",litres=" + String(pendingFault.litres, 2) + ",runs=" +
                                pendingFault.runs);
}

static void handleSerial() {
  while (Serial.available()) {
    const char c = (char)Serial.read();
    if (c == '1') {  // manual ON (bench), max time still applies
      if (!act.busy()) startCycle(settings.maxS, Trigger::MANUAL, -1, -1);
      logLine("CMD", "serial manual on");
    } else if (c == '0') {
      localOff = true;
      act.stop(millis(), EndReason::MANUAL_STOP);
      logLine("CMD", "serial off: automatic watering disabled until 'a'");
    } else if (c == 'a') {
      localOff = false;
      logLine("CMD", "serial automatic mode");
    } else if (c == 'r') {
      takeReading();
    } else if (c == 's') {
      logLine("STATUS", String("online=") + (int)online + ",time=" + timeSynced + ",src=" + sourceName(power.state) + ",v=" +
                            String(live.supplyV, 2) + ",settings=" + settings.version + ",buffered=" + bufReadings.count + "/" +
                            bufEvents.count);
    }
  }
}

static void controlTick() {
  const uint32_t now = millis();
  if (settingsDirty) {
    xSemaphoreTake(stateMutex, portMAX_DELAY);
    settings = netSettings;
    settingsDirty = false;
    xSemaphoreGive(stateMutex);
  }

  // Tier 1 lives here: the Actuator enforces the max watering time on its own.
  if (act.update(now, settings.gapMs)) {
    const Cycle c = act.cycle();
    setRelays(false, false);
    hasLastEnd = true;
    lastEndUptimeS = now / 1000UL;
    markCycleOpen(false);
    eventActuation(c);
  }
  setRelays(act.valveOn(), act.pumpOn());

  if (now - lastPowerMs >= POWER_SAMPLE_MS) {
    lastPowerMs = now;
    const float v = readSupplyVolts();
    const Source before = power.state;
    if (power.sample(v)) eventPower(before, power.state, v);
    live.supplyV = v;
  }

  Command cmd;
  while (xQueueReceive(qCommands, &cmd, 0) == pdTRUE) handleCommand(cmd);

  ReadingRec failed;
  while (xQueueReceive(qFailsafe, &failed, 0) == pdTRUE) runFailSafe(failed);

  if ((int32_t)(now - nextReadingMs) >= 0) {
    ReadingRec r = takeReading();
    if (xQueueSend(qReadings, &r, 0) != pdTRUE) runFailSafe(r);
    scheduleNextReading();
  }

  runFaultSchedule();

  xSemaphoreTake(stateMutex, portMAX_DELAY);
  live.pump = act.pumpOn();
  live.valve = act.valveOn();
  live.source = power.state;
  live.mode = haveEval && lastEval.active == 0 ? 2 : (online ? 0 : 1);
  live.water = act.busy() ? (uint8_t)act.cycle().trigger : 0;
  live.remainingS = act.remainingS(now);
  xSemaphoreGive(stateMutex);

  // Network task stalled for minutes: restart while no water is running.
  if (!act.busy() && netHeartbeatMs && now - netHeartbeatMs > NET_STALL_RESTART_MS) {
    logLine("RESTART", "network task stalled");
    ESP.restart();
  }
}

// =============================================================== networking (core 0)
static String toHex(const uint8_t* b, size_t n) {
  static const char* h = "0123456789abcdef";
  String s;
  s.reserve(n * 2);
  for (size_t i = 0; i < n; i++) {
    s += h[b[i] >> 4];
    s += h[b[i] & 15];
  }
  return s;
}

static String sha256Hex(const String& body) {
  uint8_t out[32];
  mbedtls_md(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), (const uint8_t*)body.c_str(), body.length(), out);
  return toHex(out, 32);
}

static String hmacHex(const String& msg) {
  uint8_t key[32];
  for (int i = 0; i < 32; i++) {
    char b[3] = {cfg.secretHex[2 * i], cfg.secretHex[2 * i + 1], 0};
    key[i] = (uint8_t)strtoul(b, nullptr, 16);
  }
  uint8_t out[32];
  mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), key, 32, (const uint8_t*)msg.c_str(), msg.length(), out);
  return toHex(out, 32);
}

// One signed request. Returns the HTTP status (or a negative HTTPClient error).
static int signedRequest(const char* method, const String& pathQuery, const String& body, String& response) {
  static WiFiClientSecure tls;
  static WiFiClient plain;
  static bool tlsReady = false;
  if (!tlsReady) {
    if (cfg.caMode == 1 && customCaPem.length()) tls.setCACert(customCaPem.c_str());
    else tls.setCACert(GK_ISRG_ROOTS_PEM);
    tlsReady = true;
  }
  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  http.setConnectTimeout(HTTP_TIMEOUT_MS);
  http.setReuse(true);
  const String url = String(cfg.server) + pathQuery;
  const bool ok = cfg.caMode == 2 ? http.begin(plain, url) : http.begin(tls, url);
  if (!ok) return -100;

  char nonce[33];
  uint8_t rnd[16];
  esp_fill_random(rnd, sizeof rnd);
  for (int i = 0; i < 16; i++) snprintf(nonce + 2 * i, 3, "%02x", rnd[i]);
  const uint32_t e = nowEpoch();
  // Before the first time sync the timestamp is uptime; the server accepts it and
  // answers with server_time (C-3, "time_unsynced").
  const String ts = String(e ? e : millis() / 1000UL);
  const String sig = hmacHex(String(method) + "\n" + pathQuery + "\n" + ts + "\n" + nonce + "\n" + sha256Hex(body));

  http.addHeader("X-GK-Device", cfg.deviceId);
  http.addHeader("X-GK-Timestamp", ts);
  http.addHeader("X-GK-Nonce", nonce);
  http.addHeader("X-GK-Signature", sig);
  int code;
  if (strcmp(method, "POST") == 0) {
    http.addHeader("Content-Type", "application/json");
    code = http.POST(body);
  } else {
    code = http.GET();
  }
  response = code > 0 ? http.getString() : String();
  http.end();
  return code;
}

static void applyServerTime(const char* iso) {
  if (!iso || timeSynced) return;
  struct tm t {};
  if (sscanf(iso, "%d-%d-%dT%d:%d:%d", &t.tm_year, &t.tm_mon, &t.tm_mday, &t.tm_hour, &t.tm_min, &t.tm_sec) == 6) {
    t.tm_year -= 1900;
    t.tm_mon -= 1;
    setenv("TZ", "UTC0", 1);
    tzset();
    const time_t s = mktime(&t);
    struct timeval tv = {s, 0};
    settimeofday(&tv, nullptr);
    timeSynced = true;
    scheduleNextReading();
    logLine("TIME", String("from server ") + iso);
  }
}

static void applySettings(JsonVariantConst s) {
  if (s.isNull()) return;
  NodeSettings n = netSettings;
  n.version = s["v"] | n.version;
  n.threshold = s["thr"] | n.threshold;
  n.probeMin = s["pmin"] | n.probeMin;
  n.maxS = s["max"] | n.maxS;
  n.soakS = s["soak"] | n.soakS;
  n.gapMs = s["gap"] | n.gapMs;
  n.flowLpm = s["flow"] | n.flowLpm;
  n.dailyL = s["daily_l"] | n.dailyL;
  n.amShare = s["am_share"] | n.amShare;
  const char* am = s["am"] | "06:00";
  const char* pm = s["pm"] | "16:00";
  n.amMinute = (uint16_t)(atoi(am) * 60 + atoi(am + 3));
  n.pmMinute = (uint16_t)(atoi(pm) * 60 + atoi(pm + 3));
  const char* ids[3] = {"S1", "S2", "S3"};
  for (int i = 0; i < NUM_PROBES; i++) {
    JsonArrayConst c = s["cal"][ids[i]];
    if (c.size() == 4) n.cal[i] = Calib{c[0].as<int>(), c[1].as<int>(), c[2].as<float>(), c[3].as<float>()};
  }
  if (n.gapMs > 1000) n.gapMs = 1000;
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  netSettings = n;
  settingsDirty = true;  // the control loop copies it at its next tick
  xSemaphoreGive(stateMutex);
  saveSettings();
  logLine("SETTINGS", String("v=") + n.version + ",thr=" + n.threshold + ",max=" + n.maxS);
}

static String readingJson(const ReadingRec& r) {
  JsonDocument d;
  d["reading_uuid"] = r.uuid;
  if (r.epoch) d["recorded_at"] = isoFromEpochMs((uint64_t)r.epoch * 1000ULL);
  JsonArray probes = d["probes"].to<JsonArray>();
  const char* ids[3] = {"S1", "S2", "S3"};
  for (int i = 0; i < NUM_PROBES; i++) {
    JsonObject p = probes.add<JsonObject>();
    p["id"] = ids[i];
    p["raw"] = r.raw[i];
    const bool f = r.faultBits & (1 << i);
    if (f) p["vwc"] = nullptr;
    else p["vwc"] = roundf(r.vwc[i] * 10.0f) / 10.0f;
    p["fault"] = f;
  }
  if (r.active) d["spatial_mean_vwc"] = roundf(r.mean * 10.0f) / 10.0f;
  else d["spatial_mean_vwc"] = nullptr;
  d["active_probe_count"] = r.active;
  d["supply_v"] = roundf(r.supplyV * 100.0f) / 100.0f;
  d["power_source"] = sourceName((Source)r.source);
  d["control_mode"] = modeName(r.mode);
  d["settings_version"] = r.settingsVersion;
  d["fw"] = GK_FW_VERSION;
  d["uptime_s"] = millis() / 1000UL;
  d["rssi"] = WiFi.RSSI();
  String out;
  serializeJson(d, out);
  return out;
}

static void markOnline(bool up) {
  if (up != online) logLine(up ? "ONLINE" : "OFFLINE");
  online = up;
}

// POST a live reading with 2 retries (FR-COM-03). On failure: buffer + fail-safe.
static void postReading(const ReadingRec& r) {
  const String body = readingJson(r);
  String resp;
  for (int attempt = 0; attempt <= POST_RETRIES; attempt++) {
    const int code = signedRequest("POST", "/api/device/v1/readings", body, resp);
    if (code == 200) {
      markOnline(true);
      JsonDocument d;
      if (deserializeJson(d, resp) == DeserializationError::Ok) {
        applyServerTime(d["server_time"].as<const char*>());
        applySettings(d["settings"]);
        JsonVariantConst dec = d["decision"];
        if (!dec.isNull() && strcmp(dec["action"] | "none", "water") == 0) {
          Command c{CMD_START, -1, (int32_t)(dec["id"] | -1), (uint32_t)(dec["duration_s"] | netSettings.maxS)};
          xQueueSend(qCommands, &c, 0);
        }
        logLine("DECISION", String("action=") + (dec["action"] | "none") + ",reason=" + (dec["reason"] | ""));
      }
      return;
    }
    logLine("POST_FAIL", String("attempt=") + attempt + ",code=" + code);
    vTaskDelay(pdMS_TO_TICKS(1500));
  }
  markOnline(false);
  ReadingRec copy = r;
  copy.mode = r.active ? 1 : 2;
  xSemaphoreTake(bufMutex, portMAX_DELAY);
  bufReadings.push(copy);
  xSemaphoreGive(bufMutex);
  persistBuffers();
  xQueueSend(qFailsafe, &copy, 0);  // Tier 4: the node decides from its own reading
}

static void sendEvent(const EventRec& ev) {
  String resp;
  if (ev.kind == 1) {
    signedRequest("POST", String("/api/device/v1/commands/") + ev.ackId + "/ack", String(ev.json), resp);
    return;
  }
  if (online && signedRequest("POST", "/api/device/v1/events", String(ev.json), resp) == 200) return;
  xSemaphoreTake(bufMutex, portMAX_DELAY);
  bufEvents.push(ev);
  xSemaphoreGive(bufMutex);
  persistBuffers();
}

// Upload what was stored while offline (FR-COM-06). Idempotent by UUID on the server.
static void syncBuffers() {
  if (!online || (bufReadings.empty() && bufEvents.empty())) return;
  JsonDocument d;
  JsonArray rs = d["readings"].to<JsonArray>();
  JsonArray es = d["events"].to<JsonArray>();
  xSemaphoreTake(bufMutex, portMAX_DELAY);
  const uint16_t nr = bufReadings.count < 24 ? bufReadings.count : 24;
  const uint16_t ne = bufEvents.count < 40 ? bufEvents.count : 40;
  for (uint16_t i = 0; i < nr; i++) {
    JsonDocument one;
    deserializeJson(one, readingJson(bufReadings.at(i)));
    rs.add(one);
  }
  for (uint16_t i = 0; i < ne; i++) {
    JsonDocument one;
    if (deserializeJson(one, bufEvents.at(i).json) == DeserializationError::Ok) es.add(one);
  }
  xSemaphoreGive(bufMutex);
  String body, resp;
  serializeJson(d, body);
  if (signedRequest("POST", "/api/device/v1/sync", body, resp) == 200) {
    xSemaphoreTake(bufMutex, portMAX_DELAY);
    bufReadings.dropFront(nr);
    bufEvents.dropFront(ne);
    xSemaphoreGive(bufMutex);
    persistBuffers();
    JsonDocument r;
    if (deserializeJson(r, resp) == DeserializationError::Ok) applySettings(r["settings"]);
    logLine("SYNC", String("readings=") + nr + ",events=" + ne);
  }
}

static void poll() {
  static uint8_t fails = 0;
  LiveState s;
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  s = live;
  xSemaphoreGive(stateMutex);
  char q[160];
  snprintf(q, sizeof q, "/api/device/v1/poll?p=%d&v=%d&src=%s&sv=%.2f&m=%s&w=%u&rem=%lu&s=%lu", s.pump, s.valve, sourceName(s.source),
           s.supplyV, modeName(s.mode), s.water, (unsigned long)s.remainingS, (unsigned long)netSettings.version);
  String resp;
  const int code = signedRequest("GET", q, "", resp);
  if (code != 200) {
    if (++fails >= POLL_FAILS_OFFLINE) markOnline(false);
    return;
  }
  fails = 0;
  markOnline(true);
  JsonDocument d;
  if (deserializeJson(d, resp) != DeserializationError::Ok) return;
  applyServerTime(d["t"].as<const char*>());
  for (JsonObjectConst c : d["cmd"].as<JsonArrayConst>()) {
    const char* op = c["op"] | "";
    Command cmd{CMD_STOP, (int32_t)(c["id"] | -1), -1, (uint32_t)(c["d"] | 0)};
    if (strcmp(op, "start") == 0) cmd.op = CMD_START;
    else if (strcmp(op, "stop") == 0) cmd.op = CMD_STOP;
    else if (strcmp(op, "read_now") == 0) cmd.op = CMD_READ_NOW;
#ifdef GK_TEST_HANG
    else if (strcmp(op, "test_hang") == 0) cmd.op = CMD_TEST_HANG;
#endif
    else continue;
    xQueueSend(qCommands, &cmd, 0);
    logLine("COMMAND", String("id=") + cmd.id + ",op=" + op + ",d=" + cmd.durationS);
  }
  const uint32_t serverVersion = d["s"] | 0;
  if (serverVersion && serverVersion != netSettings.version) {
    String sresp;
    if (signedRequest("GET", "/api/device/v1/settings", "", sresp) == 200) {
      JsonDocument sd;
      if (deserializeJson(sd, sresp) == DeserializationError::Ok) applySettings(sd["settings"]);
    }
  }
}

static void ensureWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  static uint32_t lastTry = 0;
  if (lastTry && millis() - lastTry < 10000) return;
  lastTry = millis();
  WiFi.mode(WIFI_STA);
  WiFi.begin(cfg.ssid, cfg.pass);
  logLine("WIFI", String("connecting ssid=") + cfg.ssid);
}

static void netTask(void*) {
  uint32_t lastPoll = 0;
  bool ntpStarted = false;
  for (;;) {
    netHeartbeatMs = millis();
    ensureWifi();
    if (WiFi.status() == WL_CONNECTED) {
      if (!ntpStarted) {
        configTime(0, 0, "pool.ntp.org", "time.google.com");  // keep UTC; Manila = UTC+8 in code
        ntpStarted = true;
      }
      if (!timeSynced && time(nullptr) > 1600000000) {
        timeSynced = true;
        scheduleNextReading();
        logLine("TIME", "ntp");
      }
      ReadingRec r;
      while (xQueueReceive(qReadings, &r, 0) == pdTRUE) postReading(r);
      EventRec ev;
      while (xQueueReceive(qEvents, &ev, 0) == pdTRUE) sendEvent(ev);
      if (millis() - lastPoll >= POLL_PERIOD_MS) {
        lastPoll = millis();
        poll();
        syncBuffers();
      }
    } else {
      // No Wi-Fi: every reading is buffered and the node decides on its own.
      ReadingRec r;
      while (xQueueReceive(qReadings, &r, 0) == pdTRUE) {
        markOnline(false);
        r.mode = r.active ? 1 : 2;
        xSemaphoreTake(bufMutex, portMAX_DELAY);
        bufReadings.push(r);
        xSemaphoreGive(bufMutex);
        persistBuffers();
        xQueueSend(qFailsafe, &r, 0);
      }
      EventRec ev;
      while (xQueueReceive(qEvents, &ev, 0) == pdTRUE) {
        if (ev.kind == 1) continue;  // an ack is meaningless once the command expired
        xSemaphoreTake(bufMutex, portMAX_DELAY);
        bufEvents.push(ev);
        xSemaphoreGive(bufMutex);
        persistBuffers();
      }
    }
    vTaskDelay(pdMS_TO_TICKS(50));
  }
}

// =============================================================== setup page
static void runSetupPortal() {
  logLine("SETUP", "starting access point GARDEKALINGA-setup");
  setRelays(false, false);
  WiFi.mode(WIFI_AP);
  WiFi.softAP("GARDEKALINGA-setup");
  DNSServer dns;
  dns.start(53, "*", WiFi.softAPIP());
  WebServer server(80);
  auto page = [&]() {
    String h =
        F("<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'><title>GARDEKALINGA setup</title>"
          "<style>body{font:16px system-ui;margin:24px;max-width:520px}label{display:block;margin:14px 0 4px;font-weight:600}"
          "input,select,textarea{width:100%;padding:10px;font:inherit;box-sizing:border-box}button{margin-top:18px;padding:12px 18px;"
          "font:inherit;background:#1F5FA6;color:#fff;border:0;border-radius:4px}</style><h1>Box B setup</h1><form method=post action=/save>");
    h += "<label>Wi-Fi name</label><input name=ssid value='" + String(cfg.ssid) + "' required>";
    h += F("<label>Wi-Fi password</label><input name=pass type=password>");
    h += "<label>Server URL</label><input name=server placeholder='https://your-app.vercel.app' value='" + String(cfg.server) + "' required>";
    h += "<label>Device ID</label><input name=id value='" + String(cfg.deviceId[0] ? cfg.deviceId : "gk-node-01") + "' required>";
    h += F("<label>Device secret (64 hex characters, from make register-device)</label><input name=secret autocomplete=off>");
    h += F("<label>Server certificate</label><select name=ca><option value=0>Public domain (Let's Encrypt ISRG roots)</option>"
           "<option value=1>On-site server (paste Caddy root CA below)</option><option value=2>Plain HTTP, bench test only</option></select>");
    h += F("<label>Custom root CA (PEM)</label><textarea name=pem rows=6></textarea><button>Save and restart</button></form>");
    server.send(200, "text/html", h);
  };
  server.on("/", page);
  server.onNotFound(page);
  server.on("/save", HTTP_POST, [&]() {
    strlcpy(cfg.ssid, server.arg("ssid").c_str(), sizeof cfg.ssid);
    if (server.arg("pass").length()) strlcpy(cfg.pass, server.arg("pass").c_str(), sizeof cfg.pass);
    String url = server.arg("server");
    while (url.endsWith("/")) url.remove(url.length() - 1);
    strlcpy(cfg.server, url.c_str(), sizeof cfg.server);
    strlcpy(cfg.deviceId, server.arg("id").c_str(), sizeof cfg.deviceId);
    if (server.arg("secret").length() == 64) strlcpy(cfg.secretHex, server.arg("secret").c_str(), sizeof cfg.secretHex);
    cfg.caMode = (uint8_t)server.arg("ca").toInt();
    if (server.arg("pem").length()) customCaPem = server.arg("pem");
    saveConfig();
    server.send(200, "text/html", "<p>Saved. Restarting…</p>");
    delay(800);  // setup mode only: relays are off and the control loop is not running
    ESP.restart();
  });
  server.begin();
  for (;;) {
    dns.processNextRequest();
    server.handleClient();
    delay(5);
  }
}

// =============================================================== setup / loop
void setup() {
  // FR-ACT-05: relays OFF before the pins become outputs (no click at start-up).
  digitalWrite(PIN_VALVE, RELAY_OFF);
  digitalWrite(PIN_PUMP, RELAY_OFF);
  pinMode(PIN_VALVE, OUTPUT);
  pinMode(PIN_PUMP, OUTPUT);
  pinMode(PIN_SETUP, INPUT_PULLUP);

  Serial.begin(115200);
  const esp_reset_reason_t rr = esp_reset_reason();
  logLine("BOOT", String("fw=") + GK_FW_VERSION + ",reset_reason=" + resetReasonName(rr));

  analogReadResolution(12);
  analogSetPinAttenuation(PIN_S1, ADC_11db);  // paper: ADC_ATTEN_DB_11
  analogSetPinAttenuation(PIN_S2, ADC_11db);
  analogSetPinAttenuation(PIN_S3, ADC_11db);
  analogSetPinAttenuation(PIN_SUPPLY, ADC_11db);

  LittleFS.begin(true);
  loadConfig();
  restoreBuffers();

  // Hold the BOOT button for 3 s at power-up, or no Wi-Fi saved yet: setup page.
  uint32_t held = millis();
  while (digitalRead(PIN_SETUP) == LOW && millis() - held < 3000) delay(10);
  if (!cfg.ssid[0] || !cfg.server[0] || strlen(cfg.secretHex) != 64 || (digitalRead(PIN_SETUP) == LOW && millis() - held >= 3000)) {
    runSetupPortal();
  }

  stateMutex = xSemaphoreCreateMutex();
  bufMutex = xSemaphoreCreateMutex();
  qReadings = xQueueCreate(4, sizeof(ReadingRec));
  qEvents = xQueueCreate(16, sizeof(EventRec));
  qCommands = xQueueCreate(8, sizeof(Command));
  qFailsafe = xQueueCreate(4, sizeof(ReadingRec));

  power.boot(readSupplyVolts());
  live.supplyV = readSupplyVolts();

  // Boot event with the reset reason (FR-PWR-05, TC13).
  {
    JsonDocument d;
    char u[37];
    newUuid(u);
    d["uuid"] = u;
    d["type"] = "boot";
    d["reset_reason"] = resetReasonName(rr);
    d["fw"] = GK_FW_VERSION;
    queueEvent(d);
  }
  // A cycle was open when the node went down: report how it ended.
  prefs.begin("gk", true);
  const bool cycleWasOpen = prefs.getBool("cyc", false);
  prefs.end();
  if (cycleWasOpen) {
    Cycle c{};
    c.trigger = Trigger::AUTO;
    c.reason = (rr == ESP_RST_TASK_WDT || rr == ESP_RST_INT_WDT || rr == ESP_RST_WDT) ? EndReason::WATCHDOG : EndReason::POWER_LOSS;
    eventActuation(c);
    markCycleOpen(false);
  }

  // Task watchdog on the control loop (core 1).
  esp_task_wdt_config_t wdt = {WDT_TIMEOUT_MS, 0, true};
  esp_task_wdt_reconfigure(&wdt);
  esp_task_wdt_add(NULL);

  xTaskCreatePinnedToCore(netTask, "net", 16384, nullptr, 1, nullptr, 0);
  scheduleNextReading();
  nextReadingMs = millis() + 5000;  // first reading shortly after boot
  logLine("READY", String("device=") + cfg.deviceId + ",server=" + cfg.server);
}

void loop() {
  esp_task_wdt_reset();
  handleSerial();
  controlTick();
  vTaskDelay(pdMS_TO_TICKS(CONTROL_TICK_MS));  // yields; never blocks the control logic
}
