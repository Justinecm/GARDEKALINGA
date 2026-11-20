// GARDEKALINGA node: pure logic with no Arduino dependency, so it runs in the
// native unit tests (firmware/test) exactly as on the ESP32.
//
//   * calibration (Equation 1) and the 5% / 95% fault filter (FR-SEN-04/05)
//   * spatial mean of the active probes (Equation 2, FR-SEN-06)
//   * power-source hysteresis 11.6 V / 12.8 V, 3 samples (FR-PWR-01/02)
//   * actuator state machine: valve 500 ms before pump, pump off before valve,
//     max-duration guard, millisecond timestamps (FR-ACT-02..06)
//   * offline fail-safe decision (FR-FS-01) and the sensor-fault schedule (FR-FS-03/05)
//   * a fixed-size ring buffer (FR-FS-02)
#pragma once

#include <math.h>
#include <stdint.h>
#include <string.h>

namespace gk {

// ----------------------------------------------------------------- FIXED values
constexpr int NUM_PROBES = 3;
constexpr int ADC_MAX = 4095;
constexpr int RAW_FAULT_LOW = 205;    // below 5% of 0-4095 -> faulty
constexpr int RAW_FAULT_HIGH = 3890;  // above 95% -> faulty
constexpr int SAMPLES = 64;           // per sensor per reading
constexpr uint32_t READING_PERIOD_S = 1800;  // every 30 minutes
constexpr uint32_t POLL_PERIOD_MS = 3000;    // command poll, either power source
constexpr uint32_t VALVE_LEAD_MS = 500;      // valve opens 500 ms before the pump
constexpr float V_TO_ADAPTER = 11.6f;        // solar -> wall socket at or below
constexpr float V_TO_SOLAR = 12.8f;          // wall socket -> solar above
constexpr int POWER_CONFIRM_SAMPLES = 3;     // consecutive 1 s samples
constexpr float DIVIDER_RATIO = 122.0f / 22.0f;  // R1 100k / R2 22k
constexpr int POST_RETRIES = 2;              // then offline fail-safe

// ----------------------------------------------------------------- sensing
struct Calib {
  int adcDry;    // raw value in dry soil (the larger one)
  int adcSat;    // raw value in saturated soil
  float vwcDry;  // reference VWC in dry soil
  float vwcSat;  // reference VWC in saturated soil
};

inline bool isFaulty(int raw) { return raw < RAW_FAULT_LOW || raw > RAW_FAULT_HIGH; }

// Equation 1: theta = theta_dry + (ADC_dry - ADC) / (ADC_dry - ADC_sat) * (theta_sat - theta_dry)
inline float vwcFromRaw(int raw, const Calib& c) {
  const float span = (float)(c.adcDry - c.adcSat);
  if (span <= 0.0f) return NAN;
  float v = c.vwcDry + ((float)(c.adcDry - raw) / span) * (c.vwcSat - c.vwcDry);
  if (v < 0.0f) v = 0.0f;
  if (v > 100.0f) v = 100.0f;
  return v;
}

struct ProbeValue {
  int raw;
  float vwc;  // NAN when faulty
  bool fault;
};

struct Evaluated {
  ProbeValue probe[NUM_PROBES];
  float mean;  // NAN when no probe is active
  int active;
};

inline Evaluated evaluate(const int raw[NUM_PROBES], const Calib cal[NUM_PROBES]) {
  Evaluated e{};
  float sum = 0.0f;
  e.active = 0;
  for (int i = 0; i < NUM_PROBES; i++) {
    e.probe[i].raw = raw[i];
    e.probe[i].fault = isFaulty(raw[i]);
    if (e.probe[i].fault) {
      e.probe[i].vwc = NAN;
    } else {
      e.probe[i].vwc = vwcFromRaw(raw[i], cal[i]);
      if (isnan(e.probe[i].vwc)) {
        e.probe[i].fault = true;  // calibration unusable
      } else {
        sum += e.probe[i].vwc;
        e.active++;
      }
    }
  }
  e.mean = e.active ? sum / (float)e.active : NAN;  // Equation 2
  return e;
}

inline float supplyFromPin(float vPin) { return vPin * DIVIDER_RATIO; }

// ----------------------------------------------------------------- power
enum class Source : uint8_t { UNKNOWN = 0, SOLAR = 1, ADAPTER = 2 };

inline const char* sourceName(Source s) {
  return s == Source::SOLAR ? "solar" : s == Source::ADAPTER ? "adapter" : "unknown";
}

struct PowerMonitor {
  Source state = Source::UNKNOWN;
  Source candidate = Source::UNKNOWN;
  int count = 0;

  static Source classifyBoot(float v) {
    if (v > V_TO_SOLAR) return Source::SOLAR;
    if (v <= V_TO_ADAPTER) return Source::ADAPTER;
    return Source::UNKNOWN;
  }

  void boot(float v) {
    state = classifyBoot(v);
    candidate = state;
    count = 0;
  }

  // Feed one 1-second sample. Returns true when the state changed.
  bool sample(float v) {
    Source want = state;
    if (state != Source::ADAPTER && v <= V_TO_ADAPTER) want = Source::ADAPTER;
    else if (state != Source::SOLAR && v > V_TO_SOLAR) want = Source::SOLAR;
    if (want == state) {
      count = 0;
      candidate = state;
      return false;
    }
    if (want != candidate) {
      candidate = want;
      count = 0;
    }
    if (++count >= POWER_CONFIRM_SAMPLES) {
      state = want;
      count = 0;
      return true;
    }
    return false;
  }
};

// ----------------------------------------------------------------- actuator
enum class ActState : uint8_t { IDLE = 0, VALVE_OPENING, WATERING, PUMP_STOPPING };
enum class Trigger : uint8_t { AUTO = 1, MANUAL = 2, OFFLINE_FAILSAFE = 3, FAULT_SCHEDULE = 4 };
enum class EndReason : uint8_t { COMPLETED = 0, MAX_CUTOFF, MANUAL_STOP, POWER_LOSS, WATCHDOG };

inline const char* triggerName(Trigger t) {
  switch (t) {
    case Trigger::AUTO: return "auto";
    case Trigger::MANUAL: return "manual";
    case Trigger::OFFLINE_FAILSAFE: return "offline_failsafe";
    default: return "sensor_fault_schedule";
  }
}

inline const char* endName(EndReason r) {
  switch (r) {
    case EndReason::COMPLETED: return "completed";
    case EndReason::MAX_CUTOFF: return "max_cutoff";
    case EndReason::MANUAL_STOP: return "manual_stop";
    case EndReason::POWER_LOSS: return "power_loss";
    default: return "watchdog";
  }
}

struct Cycle {
  uint32_t valveOpenMs = 0, pumpOnMs = 0, pumpOffMs = 0, valveCloseMs = 0;
  uint32_t runS = 0, maxS = 0;
  bool pumpStarted = false;
  Trigger trigger = Trigger::AUTO;
  EndReason reason = EndReason::COMPLETED;
  int32_t decisionId = -1;
  int32_t commandId = -1;

  uint32_t interlockMs() const { return pumpStarted ? pumpOnMs - valveOpenMs : 0; }
  uint32_t closeGapMs() const { return valveCloseMs - pumpOffMs; }
  float durationS() const { return pumpStarted ? (float)(pumpOffMs - pumpOnMs) / 1000.0f : 0.0f; }
};

class Actuator {
 public:
  ActState state() const { return st_; }
  bool busy() const { return st_ != ActState::IDLE; }
  bool valveOn() const { return st_ != ActState::IDLE; }
  bool pumpOn() const { return st_ == ActState::WATERING; }
  const Cycle& cycle() const { return c_; }

  // Tier 1: the run is always clamped to maxS, whatever asked for it.
  bool start(uint32_t now, uint32_t requestedS, uint32_t maxS, Trigger t, int32_t decisionId, int32_t commandId) {
    if (busy() || requestedS == 0 || maxS == 0) return false;
    c_ = Cycle{};
    c_.maxS = maxS;
    c_.runS = requestedS < maxS ? requestedS : maxS;
    c_.trigger = t;
    c_.decisionId = decisionId;
    c_.commandId = commandId;
    c_.valveOpenMs = now;  // valve opens first
    cutoff_ = requestedS >= maxS;
    st_ = ActState::VALVE_OPENING;
    return true;
  }

  // Stop: pump off first, then the valve after the gap. Never the other order.
  void stop(uint32_t now, EndReason why) {
    if (st_ == ActState::VALVE_OPENING) {
      c_.pumpOnMs = c_.pumpOffMs = now;
      c_.pumpStarted = false;
      c_.reason = why;
      st_ = ActState::PUMP_STOPPING;
    } else if (st_ == ActState::WATERING) {
      c_.pumpOffMs = now;
      c_.reason = why;
      st_ = ActState::PUMP_STOPPING;
    }
  }

  // Advance. Returns true once when a cycle has fully finished (valve closed).
  bool update(uint32_t now, uint32_t closeGapMs) {
    switch (st_) {
      case ActState::VALVE_OPENING:
        if (now - c_.valveOpenMs >= VALVE_LEAD_MS) {
          c_.pumpOnMs = now;
          c_.pumpStarted = true;
          st_ = ActState::WATERING;
        }
        return false;
      case ActState::WATERING: {
        const uint32_t ran = now - c_.pumpOnMs;
        if (ran >= c_.maxS * 1000UL) {  // independent max-duration guard
          stop(now, EndReason::MAX_CUTOFF);
        } else if (ran >= c_.runS * 1000UL) {
          stop(now, cutoff_ ? EndReason::MAX_CUTOFF : EndReason::COMPLETED);
        }
        return false;
      }
      case ActState::PUMP_STOPPING:
        if (now - c_.pumpOffMs >= closeGapMs) {
          c_.valveCloseMs = now;
          st_ = ActState::IDLE;
          return true;
        }
        return false;
      default:
        return false;
    }
  }

  uint32_t remainingS(uint32_t now) const {
    if (st_ == ActState::VALVE_OPENING) return c_.runS;
    if (st_ != ActState::WATERING) return 0;
    const uint32_t ran = (now - c_.pumpOnMs) / 1000UL;
    return ran >= c_.runS ? 0 : c_.runS - ran;
  }

 private:
  ActState st_ = ActState::IDLE;
  Cycle c_{};
  bool cutoff_ = false;
};

// ----------------------------------------------------------------- fail-safe
struct FailSafeParams {
  float threshold;  // moisture_threshold (% VWC)
  float probeMin;   // probe_min_vwc
  uint32_t soakS;
};

// Offline: water when the mean is below the threshold or any probe is below its
// minimum, and the soak interval since the last cycle has passed (FR-FS-01).
inline bool failSafeShouldWater(const Evaluated& r, const FailSafeParams& p, bool watering, bool hasLastEnd, uint32_t nowS,
                                uint32_t lastEndS) {
  if (watering || r.active == 0) return false;
  if (hasLastEnd && nowS - lastEndS < p.soakS) return false;
  if (r.mean < p.threshold) return true;
  for (int i = 0; i < NUM_PROBES; i++)
    if (!r.probe[i].fault && r.probe[i].vwc < p.probeMin) return true;
  return false;
}

// ----------------------------------------------------------------- fault schedule
struct FaultPlan {
  uint8_t runs = 0;
  uint16_t runS[8] = {0};
  float litres = 0.0f;
};

// Run length = share of daily water / flow rate, capped by the max watering time;
// longer amounts are split into several runs separated by the soak interval.
inline FaultPlan planFaultRuns(float share, float dailyL, float flowLpm, uint32_t maxS) {
  FaultPlan p;
  if (flowLpm <= 0.0f || dailyL <= 0.0f || maxS == 0) return p;
  p.litres = share * dailyL;
  float total = p.litres / flowLpm * 60.0f;
  while (total >= 1.0f && p.runs < 8) {
    const float run = total > (float)maxS ? (float)maxS : total;
    p.runS[p.runs++] = (uint16_t)(run + 0.5f);
    total -= run;
  }
  return p;
}

// Decides when the 06:00 / 16:00 runs are due (Asia/Manila, within 5 minutes),
// or relative to boot while the time is unknown (boot + 1 h, then 10 h later).
struct FaultScheduler {
  int32_t lastAmDay = -1, lastPmDay = -1;
  uint8_t bootRunsDone = 0;

  // Returns 0 when nothing is due, 1 for the morning share, 2 for the afternoon share.
  int dueByClock(int32_t dayIndex, int minuteOfDay, int amMinute, int pmMinute) {
    if (minuteOfDay >= amMinute && minuteOfDay < amMinute + 5 && lastAmDay != dayIndex) {
      lastAmDay = dayIndex;
      return 1;
    }
    if (minuteOfDay >= pmMinute && minuteOfDay < pmMinute + 5 && lastPmDay != dayIndex) {
      lastPmDay = dayIndex;
      return 2;
    }
    return 0;
  }

  int dueByBoot(uint32_t secondsSinceBoot) {
    const uint32_t cycle = secondsSinceBoot / 86400UL;
    const uint32_t inDay = secondsSinceBoot % 86400UL;
    const uint8_t base = (uint8_t)(cycle * 2);
    if (inDay >= 3600UL && bootRunsDone < base + 1) {
      bootRunsDone = base + 1;
      return 1;
    }
    if (inDay >= 11UL * 3600UL && bootRunsDone < base + 2) {
      bootRunsDone = base + 2;
      return 2;
    }
    return 0;
  }
};

// ----------------------------------------------------------------- ring buffer
template <typename T, int N>
struct Ring {
  T items[N];
  uint16_t head = 0;  // oldest
  uint16_t count = 0;

  bool full() const { return count == N; }
  bool empty() const { return count == 0; }
  // When full, the oldest item is dropped so the newest is always kept.
  void push(const T& v) {
    const uint16_t idx = (uint16_t)((head + count) % N);
    items[idx] = v;
    if (count < N) count++;
    else head = (uint16_t)((head + 1) % N);
  }
  const T& at(uint16_t i) const { return items[(head + i) % N]; }
  void dropFront(uint16_t n) {
    if (n > count) n = count;
    head = (uint16_t)((head + n) % N);
    count = (uint16_t)(count - n);
  }
  static constexpr int capacity() { return N; }
};

// Next :00 or :30 boundary after `epoch` (Manila is UTC+8, so UTC alignment matches).
inline uint32_t nextReadingSlot(uint32_t epoch) { return (epoch / READING_PERIOD_S + 1) * READING_PERIOD_S; }

}  // namespace gk
