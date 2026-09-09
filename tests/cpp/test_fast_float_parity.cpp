#include <iostream>
#include <string>
#include <vector>
#include <cmath>
#include <cassert>
#include <cctype>

#include "zedda/parsing_utils.hpp"

void check(const std::string& input, bool expected_success, double expected_val) {
    double val = 0.0;
    bool success = zedda::fast_atod(input.data(), input.size(), val);
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

    // Basic integers & signs
    check("123", true, 123.0);
    check("-123", true, -123.0);
    check("+123", true, 123.0);
    check("  123  ", true, 123.0);
    check("0", true, 0.0);
    check("-0", true, -0.0);
    check("+0", true, 0.0);
    check("1", true, 1.0);
    check("9", true, 9.0);
    check("007", true, 7.0);
    check("00000", true, 0.0);

    // 15-digit boundary (fits exactly in double without precision loss)
    check("999999999999999", true, 999999999999999.0);
    check("-999999999999999", true, -999999999999999.0);
    check("+999999999999999", true, 999999999999999.0);
    check("100000000000000", true, 100000000000000.0);

    // 16-digit boundary
    check("9007199254740991", true, 9007199254740991.0);
    check("-9007199254740991", true, -9007199254740991.0);

    // Floats and scientific notation
    check("123.456", true, 123.456);
    check("-123.456", true, -123.456);
    check("1e3", true, 1000.0);
    check("-1e-3", true, -0.001);
    check("1.5e2", true, 150.0);
    check("-1.5e-2  ", true, -0.015);
    check("0.0", true, 0.0);
    check("-0.0", true, -0.0);

    // Fail cases - NaN and Inf are not valid numeric values in CSV context
    check("NaN", false, 0.0);
    check("nan", false, 0.0);
    check("inf", false, 0.0);
    check("-inf", false, 0.0);
    check("+inf", false, 0.0);
    check("infinity", false, 0.0);
    check("", false, 0.0);
    check("   ", false, 0.0);
    check("abc", false, 0.0);
    check("123abc", false, 0.0); // trailing garbage
    check("abc123", false, 0.0); // leading garbage
    check(" nan ", false, 0.0);  // padded NaN bypass check
    check("+", false, 0.0);
    check("-", false, 0.0);
    check("++1", false, 0.0);
    check("--1", false, 0.0);

    std::cout << "All fast_float parity tests passed.\n";
    return 0;
}
