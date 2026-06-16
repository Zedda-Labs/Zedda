#pragma once
#include <vector>
#include <string>
#include <cmath>
#include <cstdint>
#include <limits>
#include <algorithm>

namespace zedda {

// ─────────────────────────────────────────────────────────────
//  ColumnPairAccumulator
//  Tracks running sums for Pearson correlation between 2 columns
//  Single pass, O(1) memory — no data stored
// ─────────────────────────────────────────────────────────────
struct ColumnPairAccumulator {
    int     col_i    = 0;
    int     col_j    = 0;
    int64_t n        = 0;      // count of valid (non-null) row pairs
    double  sum_x    = 0.0;    // ΣX
    double  sum_y    = 0.0;    // ΣY
    double  sum_xy   = 0.0;    // ΣXY
    double  sum_x2   = 0.0;    // ΣX²
    double  sum_y2   = 0.0;    // ΣY²

    void update(double x, double y) {
        ++n;
        sum_x  += x;
        sum_y  += y;
        sum_xy += x * y;
        sum_x2 += x * x;
        sum_y2 += y * y;
    }

    // Pearson r — returns value in [-1, +1]
    // Returns NaN if not computable
    double pearson_r() const {
        if (n < 2) return std::numeric_limits<double>::quiet_NaN();

        double dn      = static_cast<double>(n);
        double num     = dn * sum_xy - sum_x * sum_y;
        double den_x   = dn * sum_x2 - sum_x * sum_x;
        double den_y   = dn * sum_y2 - sum_y * sum_y;

        // SEC-C06: Guard against negative values from floating-point
        // catastrophic cancellation (e.g., values near 1e15).
        // sqrt() of a negative number produces NaN, which would
        // silently corrupt correlation results.
        if (den_x <= 0.0 || den_y <= 0.0) return 0.0;

        double den     = std::sqrt(den_x * den_y);
        if (den < 1e-10) return 0.0;  // constant column — no correlation
        return num / den;
    }
};

// ─────────────────────────────────────────────────────────────
//  CorrelationResult — one correlated pair
// ─────────────────────────────────────────────────────────────
struct CorrelationResult {
    std::string col_a;
    std::string col_b;
    double      r = 0.0;          // Pearson r in [-1, +1]
    std::string direction;  // "positive" or "negative"
    std::string strength;   // "weak", "moderate", "strong", "very_strong"

    static std::string get_strength(double r) {
        double abs_r = std::abs(r);
        if (abs_r >= 0.9) return "very_strong";
        if (abs_r >= 0.7) return "strong";
        if (abs_r >= 0.5) return "moderate";
        return "weak";
    }
};

} // namespace zedda
