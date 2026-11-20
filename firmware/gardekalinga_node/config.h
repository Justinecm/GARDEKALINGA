// GARDEKALINGA Box B: pins and FIXED constants (paper section 3.10, BUILD_PROMPT A-6).
#pragma once

#define GK_FW_VERSION "1.0.0"

// ---- Pin map (FIXED). ESP32 DevKit V1 (30-pin), ADC1 only (Wi-Fi uses ADC2).
#define PIN_S1 34      // capacitive soil moisture sensor, plot 1
#define PIN_S2 35      // plot 2
#define PIN_S3 32      // plot 3 (the original 1-probe sketch used this pin)
#define PIN_SUPPLY 33  // 12 V supply through R1 100k / R2 22k
#define PIN_VALVE 26   // relay K1 (IN1), normally closed solenoid valve, active LOW
#define PIN_PUMP 27    // relay K2 (IN2), R385 pump, active LOW
#define PIN_SETUP 0    // BOOT button: hold at power-up for the setup page

// NOTE: the original sketch_nov20a.ino drove the PUMP on GPIO26 and the VALVE on
// GPIO27. The paper fixes K1 valve = GPIO26 and K2 pump = GPIO27. Check the
// wiring of Box B before flashing this firmware (see firmware/README.md).

#define RELAY_ON LOW   // JD-VCC jumper removed: LOW energises the relay
#define RELAY_OFF HIGH

// ---- Timing
#define CONTROL_TICK_MS 10
#define POWER_SAMPLE_MS 1000
#define HTTP_TIMEOUT_MS 6000
#define POLL_FAILS_OFFLINE 5      // 5 failed 3-second polls (15 s) also mean offline
#define WDT_TIMEOUT_MS 8000       // control task watchdog (FR-ACT-05)
#define NET_STALL_RESTART_MS 180000UL

// ---- Buffers (FR-FS-02): 48 h of readings and 200 events, mirrored to LittleFS
#define BUF_READINGS 96
#define BUF_EVENTS 200
#define EVENT_JSON_MAX 300

// ---- Optional test-only build flag for TC13 (forced hang -> watchdog restart).
// #define GK_TEST_HANG 1
