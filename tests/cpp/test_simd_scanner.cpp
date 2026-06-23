// ─────────────────────────────────────────────────────────────────────────────
//  test_simd_scanner.cpp — SIMD correctness parity tests
//
//  CRITICAL PURPOSE:
//  A single off-by-one error in SIMD code causes silent data corruption —
//  the wrong field boundary is found, and downstream stats are silently wrong.
//  These tests verify that scalar and AVX2/AVX-512 return IDENTICAL results
//  on 50+ varied inputs, including adversarial edge cases.
//
//  TEST STRATEGY:
//  For every test string, we call BOTH scalar and AVX2 (if available) and
//  assert the return values are identical.  AVX-512 is also tested if available.
//  The scalar implementation is the ground truth.
// ─────────────────────────────────────────────────────────────────────────────

#include <iostream>
#include <string>
#include <vector>
#include <cassert>
#include <cstring>
#include <random>
#include <sstream>
#include <iomanip>

#include "zedda/simd_scanner.hpp"

// ── Test helpers ─────────────────────────────────────────────────────────────

static int tests_run    = 0;
static int tests_passed = 0;
static int tests_failed = 0;

#define ASSERT_EQ(a, b, msg)  do {                                      \
    ++tests_run;                                                         \
    if ((a) == (b)) {                                                    \
        ++tests_passed;                                                  \
    } else {                                                             \
        ++tests_failed;                                                  \
        std::cerr << "FAIL [" << __FILE__ << ":" << __LINE__ << "] "    \
                  << (msg) << "\n"                                       \
                  << "     expected: " << (b) << "\n"                   \
                  << "     got:      " << (a) << "\n";                  \
    }                                                                    \
} while(0)

// Verify scalar == avx2 == avx512 for one input
static void check_parity(const std::string& data, size_t pos,
                          char delim, char quote,
                          const std::string& label) {
    const char* d  = data.data();
    size_t      len = data.size();

    size_t scalar_result = zedda::find_next_special_scalar(d, len, pos, delim, quote);

    // AVX2 parity
    if (zedda::has_avx2()) {
        size_t avx2_result = zedda::find_next_special_avx2(d, len, pos, delim, quote);
        ASSERT_EQ(avx2_result, scalar_result,
                  "AVX2 vs scalar parity: " + label);
    }

    // AVX-512 parity
    if (zedda::has_avx512f()) {
        size_t avx512_result = zedda::find_next_special_avx512(d, len, pos, delim, quote);
        ASSERT_EQ(avx512_result, scalar_result,
                  "AVX-512 vs scalar parity: " + label);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 1: CPU detection does not crash
// ─────────────────────────────────────────────────────────────────────────────
void test_cpu_detection() {
    std::cout << "\n=== Test 1: CPU detection ===\n";

    // These must not crash on any CI runner, even if the CPU lacks AVX2/AVX-512
    bool avx2    = zedda::has_avx2();
    bool avx512  = zedda::has_avx512f();

    // Results are just informational — not a pass/fail (varies by machine)
    std::cout << "  has_avx2()   = " << (avx2   ? "true" : "false") << "\n";
    std::cout << "  has_avx512() = " << (avx512  ? "true" : "false") << "\n";

    ++tests_run; ++tests_passed;
    std::cout << "  PASS: no crash\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 2: Empty buffer
// ─────────────────────────────────────────────────────────────────────────────
void test_empty_buffer() {
    std::cout << "\n=== Test 2: Empty buffer ===\n";

    std::string empty = "";
    check_parity(empty, 0, ',', '"', "empty buffer");
    // All implementations should return len (0) for empty buffer
    size_t r = zedda::find_next_special_scalar(empty.data(), 0, 0, ',', '"');
    ASSERT_EQ(r, size_t(0), "empty buffer returns 0");
    std::cout << "  PASS\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 3: Delimiter at first byte
// ─────────────────────────────────────────────────────────────────────────────
void test_delimiter_at_start() {
    std::cout << "\n=== Test 3: Delimiter at position 0 ===\n";

    std::string data = ",hello,world";
    check_parity(data, 0, ',', '"', "delim at pos 0");
    size_t r = zedda::find_next_special_scalar(data.data(), data.size(), 0, ',', '"');
    ASSERT_EQ(r, size_t(0), "delimiter at pos 0");
    std::cout << "  PASS\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 4: No special char in buffer (returns len)
// ─────────────────────────────────────────────────────────────────────────────
void test_no_special_char() {
    std::cout << "\n=== Test 4: No special char (return len) ===\n";

    std::string data = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOP";
    check_parity(data, 0, ',', '"', "no special char");
    size_t r = zedda::find_next_special_scalar(data.data(), data.size(), 0, ',', '"');
    ASSERT_EQ(r, data.size(), "no special char returns len");
    std::cout << "  PASS\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 5: Buffer exactly 32 bytes, special char at last position
// ─────────────────────────────────────────────────────────────────────────────
void test_exactly_32_bytes_special_at_end() {
    std::cout << "\n=== Test 5: 32-byte buffer, special at pos 31 ===\n";

    std::string data(31, 'x');
    data += ',';  // special at index 31
    assert(data.size() == 32);
    check_parity(data, 0, ',', '"', "32-byte, delim at end");
    size_t r = zedda::find_next_special_scalar(data.data(), data.size(), 0, ',', '"');
    ASSERT_EQ(r, size_t(31), "special at pos 31 in 32-byte buffer");
    std::cout << "  PASS\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 6: Buffer of 31 bytes (< 32 — AVX2 must use scalar remainder)
// ─────────────────────────────────────────────────────────────────────────────
void test_less_than_32_bytes() {
    std::cout << "\n=== Test 6: Buffer < 32 bytes ===\n";

    for (int sz = 1; sz < 32; ++sz) {
        std::string data(sz, 'x');
        // Place special char at the last byte
        data.back() = ',';
        check_parity(data, 0, ',', '"', "size=" + std::to_string(sz) + " delim at end");
    }
    std::cout << "  PASS (31 sub-cases)\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 7: Buffers NOT a multiple of 32 bytes
// ─────────────────────────────────────────────────────────────────────────────
void test_non_multiple_of_32() {
    std::cout << "\n=== Test 7: Non-multiple of 32 bytes ===\n";

    for (int extra = 1; extra < 32; ++extra) {
        int sz = 64 + extra;  // 65..95 bytes (2 full AVX2 chunks + remainder)
        std::string data(sz, 'a');
        data[sz - 1] = ',';  // special char in remainder
        check_parity(data, 0, ',', '"',
                     "size=" + std::to_string(sz) + " delim at end");
    }
    std::cout << "  PASS (31 sub-cases)\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 8: Newline detection
// ─────────────────────────────────────────────────────────────────────────────
void test_newline_detection() {
    std::cout << "\n=== Test 8: Newline detection ===\n";

    std::string data = "hello world\nfoo bar";
    check_parity(data, 0, ',', '"', "newline in middle");
    size_t r = zedda::find_next_special_scalar(data.data(), data.size(), 0, ',', '"');
    ASSERT_EQ(r, size_t(11), "newline at pos 11");

    // Windows \r\n
    std::string crlf = "hello\r\nworld";
    check_parity(crlf, 0, ',', '"', "CRLF");
    size_t r2 = zedda::find_next_special_scalar(crlf.data(), crlf.size(), 0, ',', '"');
    ASSERT_EQ(r2, size_t(5), "\\r at pos 5");
    std::cout << "  PASS\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 9: Quote detection
// ─────────────────────────────────────────────────────────────────────────────
void test_quote_detection() {
    std::cout << "\n=== Test 9: Quote character detection ===\n";

    std::string data = "hello\"world,foo";
    check_parity(data, 0, ',', '"', "quote before delimiter");
    size_t r = zedda::find_next_special_scalar(data.data(), data.size(), 0, ',', '"');
    ASSERT_EQ(r, size_t(5), "quote at pos 5 detected before delimiter at pos 11");
    std::cout << "  PASS\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 10: pos > 0 (start from middle of buffer)
// ─────────────────────────────────────────────────────────────────────────────
void test_nonzero_start_pos() {
    std::cout << "\n=== Test 10: Non-zero start position ===\n";

    std::string data = "aaa,bbb,ccc";
    // Start after first delimiter
    check_parity(data, 4, ',', '"', "pos=4, next delim at 7");
    size_t r = zedda::find_next_special_scalar(data.data(), data.size(), 4, ',', '"');
    ASSERT_EQ(r, size_t(7), "next delimiter at pos 7 starting from pos 4");
    std::cout << "  PASS\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 11: 50 random strings — exhaustive parity check
// ─────────────────────────────────────────────────────────────────────────────
void test_random_parity() {
    std::cout << "\n=== Test 11: 50 random string parity checks ===\n";

    std::mt19937 rng(42);  // fixed seed for reproducibility

    // Characters that include special chars with some probability
    std::string char_pool = "abcdefghijklmnopqrstuvwxyz0123456789_-./\\|#@!,\"\n\r";

    for (int trial = 0; trial < 50; ++trial) {
        // Random length 1..128
        int len = 1 + (rng() % 128);
        std::string data;
        data.reserve(len);
        for (int j = 0; j < len; ++j) {
            data += char_pool[rng() % char_pool.size()];
        }

        // Random start position
        size_t start_pos = rng() % data.size();

        std::ostringstream label;
        label << "trial " << trial << " len=" << len << " pos=" << start_pos;
        check_parity(data, start_pos, ',', '"', label.str());
    }

    std::cout << "  PASS (50 random trials)\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 12: Large buffer spanning many AVX2 chunks
// ─────────────────────────────────────────────────────────────────────────────
void test_large_buffer() {
    std::cout << "\n=== Test 12: Large buffer (1MB) ===\n";

    size_t sz = 1024 * 1024;
    std::string data(sz, 'x');
    // Place delimiter at known position
    size_t target = 500003;
    data[target] = ',';

    check_parity(data, 0, ',', '"', "1MB buffer, delim at 500003");
    size_t r = zedda::find_next_special_scalar(data.data(), data.size(), 0, ',', '"');
    ASSERT_EQ(r, target, "delimiter at 500003 in 1MB buffer");
    std::cout << "  PASS\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 13: All special chars in sequence
// ─────────────────────────────────────────────────────────────────────────────
void test_all_special_chars_sequential() {
    std::cout << "\n=== Test 13: Sequential special chars ===\n";

    // All four special chars back to back, preceded by 40 bytes of 'x'
    std::string data(40, 'x');
    data += ',';  data += '"';  data += '\n';  data += '\r';
    // First special should be the ',' at position 40

    check_parity(data, 0, ',', '"', "40x then ,\"\\n\\r");
    size_t r = zedda::find_next_special_scalar(data.data(), data.size(), 0, ',', '"');
    ASSERT_EQ(r, size_t(40), "first special at pos 40");
    std::cout << "  PASS\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 14: Custom delimiter (tab)
// ─────────────────────────────────────────────────────────────────────────────
void test_custom_delimiter() {
    std::cout << "\n=== Test 14: Custom delimiter (tab) ===\n";

    std::string data = "hello\tworld\tfoo";
    check_parity(data, 0, '\t', '"', "tab-delimited");
    size_t r = zedda::find_next_special_scalar(data.data(), data.size(), 0, '\t', '"');
    ASSERT_EQ(r, size_t(5), "tab at pos 5");
    std::cout << "  PASS\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 15: 64-byte buffer (one AVX-512 chunk) with special at end
// ─────────────────────────────────────────────────────────────────────────────
void test_64_byte_buffer() {
    std::cout << "\n=== Test 15: 64-byte buffer, special at pos 63 ===\n";

    std::string data(63, 'y');
    data += '\n';
    assert(data.size() == 64);
    check_parity(data, 0, ',', '"', "64-byte buffer, newline at 63");
    size_t r = zedda::find_next_special_scalar(data.data(), data.size(), 0, ',', '"');
    ASSERT_EQ(r, size_t(63), "newline at pos 63 in 64-byte buffer");
    std::cout << "  PASS\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 16: ZEDDA_FORCE_SCALAR env var
// ─────────────────────────────────────────────────────────────────────────────
void test_force_scalar_env() {
    std::cout << "\n=== Test 16: get_active_scanner() — scalar path ===\n";

    // get_active_scanner is cached after first call.
    // We can at least verify it doesn't crash and returns a valid function pointer.
    auto fn = zedda::get_active_scanner();
    ASSERT_EQ(fn != nullptr, true, "get_active_scanner() returns non-null");

    // Verify it produces correct output on a known input
    std::string data = "hello,world";
    size_t r = fn(data.data(), data.size(), 0, ',', '"');
    ASSERT_EQ(r, size_t(5), "active scanner finds comma at pos 5");
    std::cout << "  PASS\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  main
// ─────────────────────────────────────────────────────────────────────────────
int main() {
    std::cout << "zedda — SIMD Scanner Parity Tests\n";
    std::cout << "===================================\n";

    test_cpu_detection();
    test_empty_buffer();
    test_delimiter_at_start();
    test_no_special_char();
    test_exactly_32_bytes_special_at_end();
    test_less_than_32_bytes();
    test_non_multiple_of_32();
    test_newline_detection();
    test_quote_detection();
    test_nonzero_start_pos();
    test_random_parity();
    test_large_buffer();
    test_all_special_chars_sequential();
    test_custom_delimiter();
    test_64_byte_buffer();
    test_force_scalar_env();

    std::cout << "\n===================================\n";
    std::cout << "Results: " << tests_passed << "/" << tests_run << " passed";
    if (tests_failed > 0) {
        std::cout << "  (" << tests_failed << " FAILED)\n";
        return 1;
    }
    std::cout << "  ✓ ALL PASS\n";
    return 0;
}
