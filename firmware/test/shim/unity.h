// Minimal Unity-compatible shim so the native tests also build with plain g++
// (`make firmware-test`). PlatformIO uses the real Unity framework instead.
#pragma once
#include <math.h>
#include <stdio.h>
#include <string.h>

static int unity_failures = 0, unity_tests = 0, unity_cur_failed = 0;
#define UNITY_BEGIN() (unity_failures = 0, unity_tests = 0, 0)
#define UNITY_END() (printf("\n%d Tests %d Failures\n%s\n", unity_tests, unity_failures, unity_failures ? "FAIL" : "OK"), unity_failures)
#define RUN_TEST(fn) do { unity_cur_failed = 0; unity_tests++; setUp(); fn(); tearDown(); printf("%s:%s\n", #fn, unity_cur_failed ? "FAIL" : "PASS"); } while (0)
#define UNITY_FAIL_AT(msg) do { printf("  %s:%d: %s\n", __FILE__, __LINE__, msg); if (!unity_cur_failed) unity_failures++; unity_cur_failed = 1; return; } while (0)
#define TEST_ASSERT_TRUE(c) do { if (!(c)) UNITY_FAIL_AT("expected true: " #c); } while (0)
#define TEST_ASSERT_FALSE(c) do { if (c) UNITY_FAIL_AT("expected false: " #c); } while (0)
#define TEST_ASSERT_EQUAL(e, a) do { if ((long long)(e) != (long long)(a)) { char unity_msg_[160]; snprintf(unity_msg_, sizeof unity_msg_, "expected %lld got %lld (" #a ")", (long long)(e), (long long)(a)); UNITY_FAIL_AT(unity_msg_); } } while (0)
#define TEST_ASSERT_EQUAL_INT(e, a) TEST_ASSERT_EQUAL(e, a)
#define TEST_ASSERT_EQUAL_UINT32(e, a) TEST_ASSERT_EQUAL(e, a)
#define TEST_ASSERT_FLOAT_WITHIN(d, e, a) do { if (fabs((double)(e) - (double)(a)) > (double)(d)) { char unity_msg_[160]; snprintf(unity_msg_, sizeof unity_msg_, "expected %f got %f (" #a ")", (double)(e), (double)(a)); UNITY_FAIL_AT(unity_msg_); } } while (0)
#define TEST_ASSERT_EQUAL_STRING(e, a) do { if (strcmp((e), (a)) != 0) UNITY_FAIL_AT("strings differ: " #a); } while (0)
