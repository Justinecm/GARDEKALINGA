// Native unit tests of the node's pure logic (PlatformIO `pio test -e native`,
// or `make firmware-test` with plain g++). Covers TC3, TC5, TC6, TC10, TC11, TC12 logic.
#include <unity.h>

#include "../../gardekalinga_node/gk_logic.h"

using namespace gk;

static const Calib CAL{3000, 1300, 5.0f, 45.0f};

void setUp() {}
void tearDown() {}

// ---- TC3: faulty sensor detection at 5% / 95% of the span
void test_fault_filter_boundaries() {
  TEST_ASSERT_TRUE(isFaulty(204));
  TEST_ASSERT_FALSE(isFaulty(205));
  TEST_ASSERT_FALSE(isFaulty(3890));
  TEST_ASSERT_TRUE(isFaulty(3891));
  TEST_ASSERT_TRUE(isFaulty(0));
  TEST_ASSERT_TRUE(isFaulty(4095));
}

// ---- Equation 1 two-point calibration, clamped to 0..100
void test_calibration_equation_1() {
  TEST_ASSERT_FLOAT_WITHIN(0.001f, 5.0f, vwcFromRaw(3000, CAL));
  TEST_ASSERT_FLOAT_WITHIN(0.001f, 45.0f, vwcFromRaw(1300, CAL));
  TEST_ASSERT_FLOAT_WITHIN(0.001f, 25.0f, vwcFromRaw(2150, CAL));
  TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.0f, vwcFromRaw(3800, Calib{3000, 1300, 0.0f, 45.0f}));
  TEST_ASSERT_TRUE(isnan(vwcFromRaw(2000, Calib{1300, 3000, 5.0f, 45.0f})));  // ADCdry must be the larger
}

// ---- Equation 2 mean of active probes; faulty probe excluded
void test_spatial_mean_excludes_faulty() {
  const int raw[3] = {2150, 2150, 40};
  const Calib cal[3] = {CAL, CAL, CAL};
  Evaluated e = evaluate(raw, cal);
  TEST_ASSERT_EQUAL(2, e.active);
  TEST_ASSERT_TRUE(e.probe[2].fault);
  TEST_ASSERT_FLOAT_WITHIN(0.001f, 25.0f, e.mean);
  const int dead[3] = {10, 4095, 100};
  Evaluated z = evaluate(dead, cal);
  TEST_ASSERT_EQUAL(0, z.active);
  TEST_ASSERT_TRUE(isnan(z.mean));
}

// ---- FR-SEN-02 divider: 14.4 V maps to about 2.6 V on the pin
void test_divider() { TEST_ASSERT_FLOAT_WITHIN(0.05f, 14.4f, supplyFromPin(2.597f)); }

// ---- TC12: hysteresis and 3-sample confirmation, no repeated switching
void test_power_hysteresis() {
  PowerMonitor pm;
  pm.boot(13.4f);
  TEST_ASSERT_TRUE(pm.state == Source::SOLAR);
  TEST_ASSERT_FALSE(pm.sample(11.7f));
  TEST_ASSERT_FALSE(pm.sample(11.6f));
  TEST_ASSERT_FALSE(pm.sample(11.6f));
  TEST_ASSERT_TRUE(pm.sample(11.55f));  // third consecutive sample at/below 11.6 V
  TEST_ASSERT_TRUE(pm.state == Source::ADAPTER);
  // The adapter holds about 12.0 V and must never flip back.
  for (int i = 0; i < 50; i++) TEST_ASSERT_FALSE(pm.sample(12.0f + (i % 5) * 0.1f));
  TEST_ASSERT_FALSE(pm.sample(12.9f));
  TEST_ASSERT_FALSE(pm.sample(12.8f));  // not above 12.8: count restarts
  TEST_ASSERT_FALSE(pm.sample(12.9f));
  TEST_ASSERT_FALSE(pm.sample(13.0f));
  TEST_ASSERT_TRUE(pm.sample(13.2f));
  TEST_ASSERT_TRUE(pm.state == Source::SOLAR);
}

void test_power_boot_classification() {
  TEST_ASSERT_TRUE(PowerMonitor::classifyBoot(12.0f) == Source::UNKNOWN);
  TEST_ASSERT_TRUE(PowerMonitor::classifyBoot(11.6f) == Source::ADAPTER);
  TEST_ASSERT_TRUE(PowerMonitor::classifyBoot(12.81f) == Source::SOLAR);
}

// ---- TC6: valve opens 500 ms before the pump; pump stops before the valve closes
void test_interlock_sequence() {
  Actuator a;
  TEST_ASSERT_TRUE(a.start(1000, 180, 180, Trigger::AUTO, 12, -1));
  TEST_ASSERT_TRUE(a.valveOn());
  TEST_ASSERT_FALSE(a.pumpOn());
  a.update(1499, 100);
  TEST_ASSERT_FALSE(a.pumpOn());
  a.update(1500, 100);
  TEST_ASSERT_TRUE(a.pumpOn());
  TEST_ASSERT_EQUAL_UINT32(500, a.cycle().interlockMs());
  a.update(1500 + 179999, 100);
  TEST_ASSERT_TRUE(a.pumpOn());
  a.update(1500 + 180000, 100);
  TEST_ASSERT_FALSE(a.pumpOn());
  TEST_ASSERT_TRUE(a.valveOn());  // valve still open right after the pump stops
  TEST_ASSERT_FALSE(a.update(1500 + 180099, 100));
  TEST_ASSERT_TRUE(a.update(1500 + 180100, 100));
  TEST_ASSERT_FALSE(a.valveOn());
  TEST_ASSERT_EQUAL_UINT32(100, a.cycle().closeGapMs());
  TEST_ASSERT_TRUE(a.cycle().reason == EndReason::MAX_CUTOFF);  // ran the bounded duration
  TEST_ASSERT_FLOAT_WITHIN(0.01f, 180.0f, a.cycle().durationS());
}

// ---- TC5 / TC7: max watering time applies to every trigger, manual included
void test_max_duration_clamp_manual() {
  Actuator a;
  TEST_ASSERT_TRUE(a.start(0, 900, 180, Trigger::MANUAL, -1, 88));
  a.update(500, 100);
  a.update(500 + 180000, 100);
  a.update(500 + 180100, 100);
  TEST_ASSERT_TRUE(a.cycle().reason == EndReason::MAX_CUTOFF);
  TEST_ASSERT_FLOAT_WITHIN(0.01f, 180.0f, a.cycle().durationS());
}

void test_short_manual_run_completes() {
  Actuator a;
  a.start(0, 60, 180, Trigger::MANUAL, -1, 5);
  a.update(500, 100);
  TEST_ASSERT_EQUAL_UINT32(60, a.remainingS(500));
  a.update(60500, 100);
  a.update(60600, 100);
  TEST_ASSERT_TRUE(a.cycle().reason == EndReason::COMPLETED);
}

void test_stop_order_and_busy() {
  Actuator a;
  a.start(0, 120, 180, Trigger::MANUAL, -1, 1);
  TEST_ASSERT_FALSE(a.start(10, 120, 180, Trigger::AUTO, 2, -1));  // already running
  a.update(500, 100);
  a.stop(30000, EndReason::MANUAL_STOP);
  TEST_ASSERT_FALSE(a.pumpOn());
  TEST_ASSERT_TRUE(a.valveOn());
  TEST_ASSERT_TRUE(a.update(30100, 100));
  TEST_ASSERT_TRUE(a.cycle().reason == EndReason::MANUAL_STOP);
  // Stop during the valve lead: the pump never starts.
  Actuator b;
  b.start(0, 120, 180, Trigger::MANUAL, -1, 2);
  b.stop(200, EndReason::MANUAL_STOP);
  b.update(250, 100);
  TEST_ASSERT_FALSE(b.pumpOn());
  TEST_ASSERT_TRUE(b.update(300, 100));
  TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.0f, b.cycle().durationS());
}

void test_millis_rollover() {
  Actuator a;
  const uint32_t t0 = 0xFFFFFF00UL;
  a.start(t0, 1, 180, Trigger::AUTO, 1, -1);
  a.update(t0 + 500, 100);  // wraps past 0
  TEST_ASSERT_TRUE(a.pumpOn());
  a.update(t0 + 1500, 100);
  TEST_ASSERT_TRUE(a.update(t0 + 1600, 100));
  TEST_ASSERT_EQUAL_UINT32(500, a.cycle().interlockMs());
}

// ---- TC10: offline fail-safe uses threshold, probe minimum and soak
void test_failsafe() {
  const Calib cal[3] = {CAL, CAL, CAL};
  const FailSafeParams p{30.0f, 22.0f, 1800};
  const int moist[3] = {2000, 2000, 2000};  // ~29 %? compute: 5 + 1000/1700*40 = 28.5
  Evaluated e = evaluate(moist, cal);
  TEST_ASSERT_TRUE(failSafeShouldWater(e, p, false, false, 0, 0));
  TEST_ASSERT_FALSE(failSafeShouldWater(e, p, true, false, 0, 0));          // already watering
  TEST_ASSERT_FALSE(failSafeShouldWater(e, p, false, true, 1799, 0));       // soak
  TEST_ASSERT_TRUE(failSafeShouldWater(e, p, false, true, 1800, 0));        // soak over
  const int wet[3] = {1500, 1500, 2700};  // two wet, one dry (12 %)
  Evaluated w = evaluate(wet, cal);
  TEST_ASSERT_TRUE(failSafeShouldWater(w, p, false, false, 0, 0));          // probe below minimum
  const int allwet[3] = {1500, 1500, 1500};
  TEST_ASSERT_FALSE(failSafeShouldWater(evaluate(allwet, cal), p, false, false, 0, 0));
}

// ---- TC11: 60 % / 40 % split, capped and split by max watering time
void test_fault_plan() {
  FaultPlan am = planFaultRuns(0.6f, 9.0f, 1.5f, 180);  // 5.4 L -> 216 s -> 180 + 36
  TEST_ASSERT_EQUAL(2, am.runs);
  TEST_ASSERT_EQUAL(180, am.runS[0]);
  TEST_ASSERT_EQUAL(36, am.runS[1]);
  FaultPlan pm = planFaultRuns(0.4f, 9.0f, 1.5f, 180);  // 3.6 L -> 144 s
  TEST_ASSERT_EQUAL(1, pm.runs);
  TEST_ASSERT_EQUAL(144, pm.runS[0]);
  TEST_ASSERT_EQUAL(0, planFaultRuns(0.6f, 9.0f, 0.0f, 180).runs);
}

void test_fault_scheduler_clock() {
  FaultScheduler f;
  TEST_ASSERT_EQUAL(0, f.dueByClock(10, 359, 360, 960));
  TEST_ASSERT_EQUAL(1, f.dueByClock(10, 362, 360, 960));
  TEST_ASSERT_EQUAL(0, f.dueByClock(10, 363, 360, 960));  // once per day
  TEST_ASSERT_EQUAL(0, f.dueByClock(10, 366, 360, 960));  // outside the 5-minute window
  TEST_ASSERT_EQUAL(2, f.dueByClock(10, 960, 360, 960));
  TEST_ASSERT_EQUAL(1, f.dueByClock(11, 360, 360, 960));
}

void test_fault_scheduler_boot_relative() {
  FaultScheduler f;
  TEST_ASSERT_EQUAL(0, f.dueByBoot(3599));
  TEST_ASSERT_EQUAL(1, f.dueByBoot(3600));
  TEST_ASSERT_EQUAL(0, f.dueByBoot(7200));
  TEST_ASSERT_EQUAL(2, f.dueByBoot(11 * 3600));
  TEST_ASSERT_EQUAL(1, f.dueByBoot(86400 + 3600));
}

// ---- FR-FS-02: buffer keeps the newest 96 readings
void test_ring_buffer() {
  Ring<int, 96> r;
  for (int i = 0; i < 100; i++) r.push(i);
  TEST_ASSERT_EQUAL(96, r.count);
  TEST_ASSERT_EQUAL(4, r.at(0));
  TEST_ASSERT_EQUAL(99, r.at(95));
  r.dropFront(10);
  TEST_ASSERT_EQUAL(14, r.at(0));
  TEST_ASSERT_EQUAL(86, r.count);
}

void test_reading_slots() {
  TEST_ASSERT_EQUAL_UINT32(1800, nextReadingSlot(1));
  TEST_ASSERT_EQUAL_UINT32(3600, nextReadingSlot(1800));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_fault_filter_boundaries);
  RUN_TEST(test_calibration_equation_1);
  RUN_TEST(test_spatial_mean_excludes_faulty);
  RUN_TEST(test_divider);
  RUN_TEST(test_power_hysteresis);
  RUN_TEST(test_power_boot_classification);
  RUN_TEST(test_interlock_sequence);
  RUN_TEST(test_max_duration_clamp_manual);
  RUN_TEST(test_short_manual_run_completes);
  RUN_TEST(test_stop_order_and_busy);
  RUN_TEST(test_millis_rollover);
  RUN_TEST(test_failsafe);
  RUN_TEST(test_fault_plan);
  RUN_TEST(test_fault_scheduler_clock);
  RUN_TEST(test_fault_scheduler_boot_relative);
  RUN_TEST(test_ring_buffer);
  RUN_TEST(test_reading_slots);
  return UNITY_END();
}
