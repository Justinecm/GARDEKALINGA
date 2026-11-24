/*
  GARDEKALINGA - 1-probe sketch, connected to the Vercel website
  ===============================================================
  Same logic as the group's sketch: one probe on GPIO32, the IDLE ->
  VALVE_OPENING -> RUNNING -> PUMP_STOPPING state machine, serial commands
  1 / 0 / a, auto mode locks after MAX_TIMEOUT_RUNS runs hit the max runtime.

  What is new:
    * HTTPS to Vercel (WiFiClientSecure + the Let's Encrypt root certificates below)
    * sends readings to  POST /api/sensors/readings   every 15 s
    * asks for commands  GET  /api/sensors/commands   every 3 s, so the
      dashboard's "Water now" and "Stop watering" buttons work, and
      acknowledges each one with POST /api/sensors/commands/<id>/ack

  Before flashing:
    1. Vercel -> Settings -> Environment Variables: GK_LEGACY_DEVICE_API = true, then redeploy.
    2. Register the device (docs/DEPLOY.md step 4) and copy the 64-character secret.
    3. Fill in WIFI_SSID, WIFI_PASS, SERVER_BASE, DEVICE_ID and DEVICE_KEY below.

  Wiring (unchanged from the group's sketch): pump relay GPIO26, valve relay GPIO27,
  relays are active LOW.
*/
#include <Arduino.h>

#define ENABLE_WIFI true

#if ENABLE_WIFI
  #include <WiFi.h>
  #include <WiFiClientSecure.h>
  #include <HTTPClient.h>
  #include <time.h>
  const char* WIFI_SSID   = "YOUR_WIFI_NAME";              // 2.4 GHz network only
  const char* WIFI_PASS   = "YOUR_WIFI_PASSWORD";
  // Your Vercel address, https, no trailing slash
  const char* SERVER_BASE = "https://your-app.vercel.app";
  const char* DEVICE_ID   = "gk-node-01";                  // the id you registered
  const char* DEVICE_KEY  = "PASTE_THE_64_CHARACTER_DEVICE_SECRET";
  const unsigned long REPORT_INTERVAL_MS = 15000;
  const unsigned long POLL_INTERVAL_MS   = 3000;
  const unsigned long HTTP_TIMEOUT_MS    = 5000;   // Vercel can take a few seconds to wake up
  // TEST ONLY: true skips the certificate check, to find out whether the certificate
  // is the problem. Set it back to false once the website answers 200.
  #define TLS_SKIP_CERT_CHECK false

  // Let's Encrypt root certificates: ISRG Root X1, X2 and the 2026 roots YR, YE. Vercel's HTTPS uses them.
  static const char GK_ISRG_ROOTS_PEM[] PROGMEM = R"PEM(
-----BEGIN CERTIFICATE-----
MIIFazCCA1OgAwIBAgIRAIIQz7DSQONZRGPgu2OCiwAwDQYJKoZIhvcNAQELBQAw
TzELMAkGA1UEBhMCVVMxKTAnBgNVBAoTIEludGVybmV0IFNlY3VyaXR5IFJlc2Vh
cmNoIEdyb3VwMRUwEwYDVQQDEwxJU1JHIFJvb3QgWDEwHhcNMTUwNjA0MTEwNDM4
WhcNMzUwNjA0MTEwNDM4WjBPMQswCQYDVQQGEwJVUzEpMCcGA1UEChMgSW50ZXJu
ZXQgU2VjdXJpdHkgUmVzZWFyY2ggR3JvdXAxFTATBgNVBAMTDElTUkcgUm9vdCBY
MTCCAiIwDQYJKoZIhvcNAQEBBQADggIPADCCAgoCggIBAK3oJHP0FDfzm54rVygc
h77ct984kIxuPOZXoHj3dcKi/vVqbvYATyjb3miGbESTtrFj/RQSa78f0uoxmyF+
0TM8ukj13Xnfs7j/EvEhmkvBioZxaUpmZmyPfjxwv60pIgbz5MDmgK7iS4+3mX6U
A5/TR5d8mUgjU+g4rk8Kb4Mu0UlXjIB0ttov0DiNewNwIRt18jA8+o+u3dpjq+sW
T8KOEUt+zwvo/7V3LvSye0rgTBIlDHCNAymg4VMk7BPZ7hm/ELNKjD+Jo2FR3qyH
B5T0Y3HsLuJvW5iB4YlcNHlsdu87kGJ55tukmi8mxdAQ4Q7e2RCOFvu396j3x+UC
B5iPNgiV5+I3lg02dZ77DnKxHZu8A/lJBdiB3QW0KtZB6awBdpUKD9jf1b0SHzUv
KBds0pjBqAlkd25HN7rOrFleaJ1/ctaJxQZBKT5ZPt0m9STJEadao0xAH0ahmbWn
OlFuhjuefXKnEgV4We0+UXgVCwOPjdAvBbI+e0ocS3MFEvzG6uBQE3xDk3SzynTn
jh8BCNAw1FtxNrQHusEwMFxIt4I7mKZ9YIqioymCzLq9gwQbooMDQaHWBfEbwrbw
qHyGO0aoSCqI3Haadr8faqU9GY/rOPNk3sgrDQoo//fb4hVC1CLQJ13hef4Y53CI
rU7m2Ys6xt0nUW7/vGT1M0NPAgMBAAGjQjBAMA4GA1UdDwEB/wQEAwIBBjAPBgNV
HRMBAf8EBTADAQH/MB0GA1UdDgQWBBR5tFnme7bl5AFzgAiIyBpY9umbbjANBgkq
hkiG9w0BAQsFAAOCAgEAVR9YqbyyqFDQDLHYGmkgJykIrGF1XIpu+ILlaS/V9lZL
ubhzEFnTIZd+50xx+7LSYK05qAvqFyFWhfFQDlnrzuBZ6brJFe+GnY+EgPbk6ZGQ
3BebYhtF8GaV0nxvwuo77x/Py9auJ/GpsMiu/X1+mvoiBOv/2X/qkSsisRcOj/KK
NFtY2PwByVS5uCbMiogziUwthDyC3+6WVwW6LLv3xLfHTjuCvjHIInNzktHCgKQ5
ORAzI4JMPJ+GslWYHb4phowim57iaztXOoJwTdwJx4nLCgdNbOhdjsnvzqvHu7Ur
TkXWStAmzOVyyghqpZXjFaH3pO3JLF+l+/+sKAIuvtd7u+Nxe5AW0wdeRlN8NwdC
jNPElpzVmbUq4JUagEiuTDkHzsxHpFKVK7q4+63SM1N95R1NbdWhscdCb+ZAJzVc
oyi3B43njTOQ5yOf+1CceWxG1bQVs5ZufpsMljq4Ui0/1lvh+wjChP4kqKOJ2qxq
4RgqsahDYVvTH9w7jXbyLeiNdd8XM2w9U/t7y0Ff/9yi0GE44Za4rF2LN9d11TPA
mRGunUHBcnWEvgJBQl9nJEiU0Zsnvgc/ubhPgXRR4Xq37Z0j4r7g1SgEEzwxA57d
emyPxgcYxn/eR44/KJ4EBs+lVDR3veyJm+kXQ99b21/+jh5Xos1AnX5iItreGCc=
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
MIICGzCCAaGgAwIBAgIQQdKd0XLq7qeAwSxs6S+HUjAKBggqhkjOPQQDAzBPMQsw
CQYDVQQGEwJVUzEpMCcGA1UEChMgSW50ZXJuZXQgU2VjdXJpdHkgUmVzZWFyY2gg
R3JvdXAxFTATBgNVBAMTDElTUkcgUm9vdCBYMjAeFw0yMDA5MDQwMDAwMDBaFw00
MDA5MTcxNjAwMDBaME8xCzAJBgNVBAYTAlVTMSkwJwYDVQQKEyBJbnRlcm5ldCBT
ZWN1cml0eSBSZXNlYXJjaCBHcm91cDEVMBMGA1UEAxMMSVNSRyBSb290IFgyMHYw
EAYHKoZIzj0CAQYFK4EEACIDYgAEzZvVn4CDCuwJSvMWSj5cz3es3mcFDR0HttwW
+1qLFNvicWDEukWVEYmO6gbf9yoWHKS5xcUy4APgHoIYOIvXRdgKam7mAHf7AlF9
ItgKbppbd9/w+kHsOdx1ymgHDB/qo0IwQDAOBgNVHQ8BAf8EBAMCAQYwDwYDVR0T
AQH/BAUwAwEB/zAdBgNVHQ4EFgQUfEKWrt5LSDv6kviejM9ti6lyN5UwCgYIKoZI
zj0EAwMDaAAwZQIwe3lORlCEwkSHRhtFcP9Ymd70/aTSVaYgLXTWNLxBo1BfASdW
tL4ndQavEi51mI38AjEAi/V3bNTIZargCyzuFJ0nN6T5U6VR5CmD1/iQMVtCnwr1
/q4AaOeMSQ+2b1tbFfLn
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
MIIFKTCCAxGgAwIBAgIRAOxGNJNgz0sP+KmC2Tqpyj0wDQYJKoZIhvcNAQELBQAw
LjELMAkGA1UEBhMCVVMxDTALBgNVBAoTBElTUkcxEDAOBgNVBAMTB1Jvb3QgWVIw
HhcNMjUwOTAzMDAwMDAwWhcNNDUwOTAyMjM1OTU5WjAuMQswCQYDVQQGEwJVUzEN
MAsGA1UEChMESVNSRzEQMA4GA1UEAxMHUm9vdCBZUjCCAiIwDQYJKoZIhvcNAQEB
BQADggIPADCCAgoCggIBANvGJnN78CTJdWL3+eGfsLN5TrNBJs+VH9hRXqRbwxu9
sGNiB0BD1fcOxbSUQCJIM1xE13Db+5Cw1w0s0EBYsvuIP/6joF0w8cuImbgR1OGg
YbSQ4OpzI+DG8SGuTlcE873OCS+kh3srlo6vl43M5OJg4Aeo1sfHp6kTJDoIiFBN
JAY+OKfX/FUvYKuhjT+no49lmqmupSBI5PkBQiqrEGtWU5uxU/cQWHGu8jSjFBzn
ZqvbNPLMXMLFxCb3WTfrJBXXjqvWG+v4bjzxjjeAtOlU7qarRDvNOyAuQYLln904
M+faKx8hnLCpJ15ZqaEgcNlY+9MMWcC5yvL2A2j3l9+2buggZX+dOE91zYmIdawT
vSZuVvlbRrAlLxIB6pwMBjneXCjYQ8+3BCCjssbSNpZU3hTcBDdhfAlEDlYr6pEa
tnMdmDT5BqnKC92bd0EhM1fbLHioLccLCuievT8ZkPhZrq7Mii7gNXAcUEAR8+lz
Yal+9zTg7C5DALyVOeG/CqfRAMn1KSHCR0NSA6P8tn/mGRlnCct5rtVCLnVySVpU
6H1qGg3DgTOuskf8eahTMiYbI5ezPJmO5ertalskQ1utp74+eDy92PI4ftHKTbq9
IWhH4YZKh3WnJEIt+oQvlYZbY8tpEroKrFB6PFGzrJIDRyts4HqvuH52RFj2zv/B
AgMBAAGjQjBAMA4GA1UdDwEB/wQEAwIBBjAPBgNVHRMBAf8EBTADAQH/MB0GA1Ud
DgQWBBTe51tg0CJtQCh9Pw0B/qS1UrRRlDANBgkqhkiG9w0BAQsFAAOCAgEAWHnf
713Bdkq7t5yN2dNIgQakUb94X9WuyhMEHHkgx4oDpSUlnG0w4g94MoqaEUE31ZjR
LU7L5LD1g9ujFHTQu8AD215AHMVQFbm6j8hQxdXHAzDajFNQnOlDJrLjzIx176oy
AjvUtejZx2NNmdb5fd0WGVGsCdoAJ3N8ozo7ajE8t6vfxStZb4BQ9WYJGHUDrv2N
i5tJF6CNiPnlzs3BUfECRbE4JSk+jvy8+VoGiFE8qsH/j78x2fjgQhAQFV7P7Zxy
dBTZ1wEkNpZNW2qnaK1SKBLa+xf6E06YRIq5uaI+HWH8SY1y5VbRgzq40EKg3yxP
06fz+uYAUIFJoLNfhwRCc3Q6pQVuMX3yAjHAes4gk4moGcLQ5p7HAh39yeylZc1J
41sx/jKwLIkPE6Rr1Nf4pxdsxf9SA4yOEiAkDgq04DVxn8hgYFdUtBCuiuVC2heA
EiqVEa+8QZjuw8Gj0EbHXcRd1nInvGqRS1o9Is7YBdQN57X1AYveGBNNqjICSb7c
awuw1EawTDrs13VUlJVEsbQ0/O/1aaV73mCdOQ8azqL2KTv1Ewu1xbquE2S+kdQU
To9TUwat3wUA6cwXh1EfpS/3fJ0aGah5hdpRyoCLDlsSn8tkrjMfFFX0viC+GxHc
sI1ANRYvqSFC2X1VRZfDg+wD6E21BccmifG4yWc=
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
MIIB2TCCAWCgAwIBAgIRAKQCa6LvbHwg1AR+XmWmk4AwCgYIKoZIzj0EAwMwLjEL
MAkGA1UEBhMCVVMxDTALBgNVBAoTBElTUkcxEDAOBgNVBAMTB1Jvb3QgWUUwHhcN
MjUwOTAzMDAwMDAwWhcNNDUwOTAyMjM1OTU5WjAuMQswCQYDVQQGEwJVUzENMAsG
A1UEChMESVNSRzEQMA4GA1UEAxMHUm9vdCBZRTB2MBAGByqGSM49AgEGBSuBBAAi
A2IABDwS/6vhrcVqcbBo+wgdI3fwn9x7DNJJOY/lTOti0vkwuRN87RhEhTH17E7X
yFjWsPYhIPt/wzOqxTd2b+4ZJNy9ID04YywF9U5zasDVyGSNErVNtz8uSGh5izW8
7j77GaNCMEAwDgYDVR0PAQH/BAQDAgEGMA8GA1UdEwEB/wQFMAMBAf8wHQYDVR0O
BBYEFKPIJlqOoUzQNWP8myPIOq5W809WMAoGCCqGSM49BAMDA2cAMGQCMHhMr8N9
LdL1VQKs9BdV81r76eXRB6mtjuNjzk6/lBsPNToWLTDzGYgtQKO1jl63uAIwGV7m
onyF377c+MM1oqVNs17sgu7F9YKZwgLmVbeOMDbKAXHtKMDLbiGllCcs8f47
-----END CERTIFICATE-----
)PEM";
#endif

const int PROBE_PIN = 32;
const int PUMP_PIN  = 26;
const int VALVE_PIN = 27;

const int DRY_VALUE = 3000;
const int WET_VALUE = 1500;
const int MIN_SPAN  = 300;

const int RAW_MIN = 200;
const int RAW_MAX = 4000;

const int START_BELOW = 40;
const int STOP_ABOVE  = 60;
const unsigned long MAX_RUN_MS       = 10000;
const unsigned long COOLDOWN_MS      = 60000;
const unsigned long VALVE_LEAD_MS    = 500;
const unsigned long READ_INTERVAL_MS = 1000;
const int SAMPLES = 10;
const int MAX_TIMEOUT_RUNS = 2;

enum State { IDLE, VALVE_OPENING, RUNNING, PUMP_STOPPING };
State state = IDLE;

unsigned long stateStart  = 0;
unsigned long runStart    = 0;
unsigned long lastStop    = 0;
unsigned long lastRead    = 0;
unsigned long manualRunMs = MAX_RUN_MS;   // length asked for by the dashboard
long lastCommandId  = -1;                 // so a re-delivered command is not run twice
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

bool calibrationTooNarrow() {
  return (DRY_VALUE - WET_VALUE) < MIN_SPAN;
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

// Limit for the current run: a dashboard run may be shorter than MAX_RUN_MS, never longer.
unsigned long runLimitMs() {
  return manualRequest ? min(manualRunMs, MAX_RUN_MS) : MAX_RUN_MS;
}

unsigned long remainingMs() {
  if (state != RUNNING) return 0;
  unsigned long ran = millis() - runStart;
  unsigned long limit = runLimitMs();
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
      if (manualRequest && now - runStart >= runLimitMs()) {
        // Manual / dashboard run is over. It does not count toward the auto lock,
        // and auto mode comes back on afterwards, as in the original sketch.
        manualRequest = false;
        if (!autoLocked()) autoMode = true;
        endIrrigation(manualRunMs < MAX_RUN_MS ? "dashboard run finished" : "max runtime reached");
      } else if (now - runStart >= MAX_RUN_MS) {
        timeoutRuns++;
        endIrrigation("max runtime reached");
        if (autoLocked()) {
          autoMode = false;
          Serial.print("!! WARNING: ");
          Serial.print(timeoutRuns);
          Serial.println(" runs in a row hit the max runtime. Auto mode switched OFF.");
          Serial.println("!! Check that the probe is in the soil and wired, then send 'a' to resume.");
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

// HTTPS needs the real date: before this, the ESP32 thinks it is 1970 and every
// certificate looks "not valid yet" (TLS error -9984). Gets the time from the internet.
bool clockIsSet() { return time(nullptr) > 1700000000; }   // after Nov 2023

bool syncClock() {
  if (clockIsSet()) return true;
  static unsigned long lastTry = 0;
  static bool started = false;
  if (started && millis() - lastTry < 30000) return false;   // don't block the loop every call
  lastTry = millis();
  started = true;
  configTime(0, 0, "pool.ntp.org", "time.google.com", "time.cloudflare.com");
  Serial.print("[TIME] Getting the date from the internet");
  for (int i = 0; i < 20 && !clockIsSet(); i++) {           // up to 5 s
    delay(250);
    Serial.print(".");
  }
  if (!clockIsSet()) {
    Serial.println(" FAILED (will retry). The network may block NTP (UDP port 123).");
    return false;
  }
  time_t now = time(nullptr);
  struct tm t;
  gmtime_r(&now, &t);
  char buf[32];
  strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S UTC", &t);
  Serial.print(" OK: ");
  Serial.println(buf);
  return true;
}

bool beginRequest(HTTPClient& http, const String& path) {
#if !TLS_SKIP_CERT_CHECK
  if (!syncClock()) return false;           // no date yet: HTTPS would fail anyway
#endif
  String url = String(SERVER_BASE) + path;
  http.setTimeout(HTTP_TIMEOUT_MS);         // keep the loop responsive: the pump logic waits for us
  http.setConnectTimeout(HTTP_TIMEOUT_MS);
  if (!http.begin(tls, url)) {
    Serial.print("[WiFi] cannot open ");
    Serial.println(url);
    return false;
  }
  http.addHeader("X-Device-Key", DEVICE_KEY);
  return true;
}

const char* wifiProblem() {
  switch (WiFi.status()) {
    case WL_NO_SSID_AVAIL:  return "network name not found: check WIFI_SSID (exact spelling, 2.4 GHz only)";
    case WL_CONNECT_FAILED: return "connection refused: check WIFI_PASS";
    case WL_CONNECTION_LOST:return "connection lost";
    case WL_DISCONNECTED:   return "not connected yet (wrong password also shows like this)";
    default:                return "still trying";
  }
}

// Lists the Wi-Fi networks the ESP32 can see, so a wrong WIFI_SSID is easy to spot.
void listNetworks() {
  Serial.println("[WiFi] Networks the ESP32 can see (copy the name exactly into WIFI_SSID):");
  WiFi.disconnect();                        // a scan fails while a connection attempt is running
  delay(200);
  int n = WiFi.scanNetworks();
  if (n < 0) {
    Serial.print("   scan failed (code ");
    Serial.print(n);
    Serial.println(")");
  } else if (n == 0) {
    Serial.println("   none found: the antenna sees no 2.4 GHz network at all.");
    Serial.println("   Move closer to the router, try a phone hotspot (2.4 GHz), or try another USB cable/port.");
  }
  for (int i = 0; i < n; i++) {
    Serial.print("   \"");
    Serial.print(WiFi.SSID(i));
    Serial.print("\"  signal ");
    Serial.print(WiFi.RSSI(i));
    Serial.println(" dBm");
  }
  WiFi.scanDelete();
}

// Can the ESP32 find the website's address? Prints the answer once after connecting.
void checkInternet() {
  String host = String(SERVER_BASE);
  host.replace("https://", "");
  host.replace("http://", "");
  int slash = host.indexOf('/');
  if (slash >= 0) host = host.substring(0, slash);
  IPAddress ip;
  Serial.print("[WiFi] Looking up ");
  Serial.print(host);
  if (WiFi.hostByName(host.c_str(), ip)) {
    Serial.print(" -> ");
    Serial.println(ip);
  } else {
    Serial.println(" FAILED: the router gives no internet / DNS. Try a phone hotspot.");
  }
}

void startWiFi() {
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASS);
}

void connectWiFi() {
#if TLS_SKIP_CERT_CHECK
  tls.setInsecure();
  Serial.println("!! TLS_SKIP_CERT_CHECK is on: certificate NOT checked (testing only)");
#else
  tls.setCACert(GK_ISRG_ROOTS_PEM);         // Vercel uses Let's Encrypt certificates
#endif
  tls.setHandshakeTimeout(5);               // seconds; a bad network must not freeze the pump logic
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  Serial.print("Connecting to Wi-Fi \"");
  Serial.print(WIFI_SSID);
  Serial.print("\"");
  startWiFi();
  unsigned long t = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t < 15000) {
    delay(500);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print(" connected, IP ");
    Serial.println(WiFi.localIP());
    checkInternet();
    syncClock();
  } else {
    Serial.print(" FAILED: ");
    Serial.println(wifiProblem());
    listNetworks();
    startWiFi();
  }
}

void printStatus(const char* what, int code) {
  Serial.print("[WiFi] ");
  Serial.print(what);
  Serial.print(" status: ");
  Serial.print(code);
  if (code == 404)      Serial.print("  (set GK_LEGACY_DEVICE_API=true on Vercel and redeploy)");
  else if (code == 401) Serial.print("  (DEVICE_ID or DEVICE_KEY is wrong)");
  else if (code == -11) Serial.print("  (timed out waiting for the website)");
  Serial.println();
  if (code < 0) {
    char err[120] = "";
    int e = tls.lastError(err, sizeof(err));
    Serial.print("        reason: ");
    Serial.print(HTTPClient::errorToString(code));
    if (e) {
      Serial.print(" / TLS error ");
      Serial.print(e);
      Serial.print(": ");
      Serial.print(err);
    }
    Serial.println();
  }
}

void reportWiFi() {
  static unsigned long last = 0;
  if (millis() - last < REPORT_INTERVAL_MS) return;
  last = millis();

  if (WiFi.status() != WL_CONNECTED) {
    Serial.print("[WiFi] not connected: ");
    Serial.println(wifiProblem());
    static unsigned long lastRetry = 0;
    if (millis() - lastRetry >= 30000) {   // retry every 30 s; retrying sooner interrupts the attempt
      lastRetry = millis();
      startWiFi();
    }
    return;
  }

  String body = "{\"device_id\":\"" + String(DEVICE_ID) + "\","
                "\"readings\":{"
                "\"soil_moisture\":" + (sensorFault ? String("null") : String(moisture)) + ","
                "\"raw_adc\":" + String(constrain(rawValue, 0, 4095)) + "},"
                "\"irrigation\":{\"state\":\"" + String(stateName()) + "\","
                "\"mode\":\"" + String(modeName()) + "\","
                "\"remaining_s\":" + String(remainingMs() / 1000) + "}}";

  HTTPClient http;
  if (!beginRequest(http, "/api/sensors/readings")) return;
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(body);
  printStatus("POST readings", code);
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

// Number after "key": in s, searching from position 'from'. -1 if not found.
long jsonNumberAfter(const String& s, const String& key, int from) {
  int k = s.indexOf("\"" + key + "\":", from);
  if (k < 0) return -1;
  return s.substring(k + key.length() + 3).toInt();
}

// The server answers {"t":"...","cmd":[{"id":12,"op":"start","d":120},{"id":13,"op":"stop"}]}
void pollCommands() {
  static unsigned long last = 0;
  if (millis() - last < POLL_INTERVAL_MS || WiFi.status() != WL_CONNECTED) return;
  last = millis();

  HTTPClient http;
  if (!beginRequest(http, String("/api/sensors/commands?device_id=") + DEVICE_ID)) return;
  int code = http.GET();
  String resp = code == 200 ? http.getString() : String();
  http.end();
  if (code != 200) {
    printStatus("GET commands", code);
    return;
  }

  int pos = resp.indexOf("\"cmd\"");
  if (pos < 0) return;
  pos = resp.indexOf("{", pos);
  while (pos >= 0) {
    int end = resp.indexOf("}", pos);
    if (end < 0) break;
    String item = resp.substring(pos, end + 1);   // one command object

    long id = jsonNumberAfter(item, "id", 0);
    long d  = jsonNumberAfter(item, "d", 0);
    int opPos = item.indexOf("\"op\":\"");
    String op = opPos >= 0 ? item.substring(opPos + 6, item.indexOf('"', opPos + 6)) : String();

    if (id > 0 && id != lastCommandId) {
      lastCommandId = id;
      if (op == "start") {
        if (state != IDLE) {
          ackCommand(id, false, "already_watering");
        } else {
          manualRequest = true;
          manualRunMs = d > 0 ? (unsigned long)d * 1000UL : MAX_RUN_MS;
          Serial.print("[DASHBOARD] water for ");
          Serial.print(min(manualRunMs, MAX_RUN_MS) / 1000);
          Serial.println(" s");
          ackCommand(id, true, nullptr);
        }
      } else if (op == "stop") {
        manualRequest = false;
        if (state == RUNNING || state == VALVE_OPENING) endIrrigation("dashboard stop");
        Serial.println("[DASHBOARD] stop");
        ackCommand(id, true, nullptr);
      } else {
        ackCommand(id, false, "unsupported");
      }
    }
    pos = resp.indexOf("{", end);
  }
}
#endif

void setup() {
  digitalWrite(PUMP_PIN, HIGH);   // relays off before the pins become outputs
  digitalWrite(VALVE_PIN, HIGH);
  pinMode(PUMP_PIN, OUTPUT);
  pinMode(VALVE_PIN, OUTPUT);

  Serial.begin(115200);
  delay(300);
  analogSetPinAttenuation(PROBE_PIN, ADC_11db);

  Serial.println();
  Serial.println("GARDEKALINGA firmware - 1 probe (Vercel)");
  Serial.println("Commands: 1 = manual ON, 0 = OFF/stop, a = auto");
  if (calibrationTooNarrow()) {
    Serial.println("!! WARNING: DRY_VALUE and WET_VALUE are too close together.");
    Serial.println("!! Measure the probe in dry and in soaked soil and update both values.");
  }

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
    if (calibrationTooNarrow()) Serial.print("  [CHECK CALIBRATION]");
    Serial.println();
  }

  runStateMachine();

#if ENABLE_WIFI
  reportWiFi();
  pollCommands();
#endif
}
