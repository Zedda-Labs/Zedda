#include <iostream>
#include <string>
#include <vector>
#include <cmath>
#include <cassert>
#include <cctype>

#include "zedda/fast_float/fast_float.h"

// The new fast_atod implementation
static inline bool fast_atod(const char* s, size_t len, double& out) {
    if (len == 0) return false;

    // Strip leading whitespace
    size_t i = 0;
    while (i < len && std::isspace(static_cast<unsigned char>(s[i]))) {
        ++i;
    }
    if (i == len) return false;

    // Strip trailing whitespace
    size_t end_idx = len;
    while (end_idx > i && std::isspace(static_cast<unsigned char>(s[end_idx - 1]))) {
        --end_idx;
    }
    if (i == end_idx) return false;

    // Handle unary '+'
    if (s[i] == '+') {
        ++i;
        if (i == end_idx) return false;
    }

    // Parse with no_infnan
    constexpr auto fmt = fast_float::chars_format::general
                       | fast_float::chars_format::no_infnan;
    fast_float::parse_options opts(fmt);
    auto result = fast_float::from_chars_float_advanced(s + i, s + end_idx, out, opts);
    if (result.ec != std::errc()) {
        return false;
    }

    // Ensure the entire trimmed input was consumed
    if (result.ptr != s + end_idx) {
        return false;
    }

    // Defense-in-depth: reject non-finite results
    if (!std::isfinite(out)) {
        return false;
    }

    return true;
}

void check(const std::string& input, bool expected_success, double expected_val) {
    double val = 0.0;
    bool success = fast_atod(input.data(), input.size(), val);
    if (success != expected_success) {
        std::cerr << "FAIL: '" << input << "' -> expected success: " << expected_success << " got: " << success << "\n";
        exit(1);
    }
    if (success) {
        // Compare with NaN handling
        if (std::isnan(expected_val)) {
            if (!std::isnan(val)) {
                std::cerr << "FAIL: '" << input << "' -> expected NaN, got: " << val << "\n";
                exit(1);
            }
        } else {
            // Need a tiny epsilon for float comparisons
            if (std::abs(val - expected_val) > 1e-10) {
                std::cerr << "FAIL: '" << input << "' -> expected: " << expected_val << " got: " << val << "\n";
                exit(1);
            }
        }
    }
}

int main() {
    std::cout << "Testing fast_float wrapper parity...\n";

    check("123", true, 123.0);
    check("-123", true, -123.0);
    check("+123", true, 123.0);
    check("  123  ", true, 123.0);
    check("123.456", true, 123.456);
    check("-123.456", true, -123.456);
    check("1e3", true, 1000.0);
    check("-1e-3", true, -0.001);
    check("1.5e2", true, 150.0);
    check("-1.5e-2  ", true, -0.015);
    check("0", true, 0.0);
    check("-0", true, -0.0);

    // Fail cases - NaN and Inf are not valid numeric values in CSV context
    check("NaN", false, 0.0);
    check("inf", false, 0.0);
    check("-inf", false, 0.0);
    check("infinity", false, 0.0);
    check("", false, 0.0);
    check("   ", false, 0.0);
    check("abc", false, 0.0);
    check("123abc", false, 0.0); // trailing garbage
    check("abc123", false, 0.0); // leading garbage
    check(" nan ", false, 0.0);  // padded NaN bypass check

    std::cout << "All fast_float parity tests passed.\n";
    return 0;
}
