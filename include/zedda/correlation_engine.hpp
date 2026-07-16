#pragma once
#include <vector>
#include <string>
#include <cmath>
#include <cstdint>
#include <limits>
#include <algorithm>
#include <utility>  // FIX C-M1: std::swap for pair_idx
#include <cstddef>

namespace zedda {

// ─────────────────────────────────────────────────────────────
//  ColumnPairAccumulator
//  Tracks running sums for Pearson correlation between 2 columns
//  Single pass, O(1) memory — no data stored
//
//  FIX C-H1: Switched from naive 5-sum formula to Welford-style
//  online covariance. The naive formula `dn*Σxy - Σx*Σy` loses
//  ~10+ digits of precision for columns with values near 1e8+ and
//  n=1e6+, and the `den_x <= 0` guard silently returned 0 instead
//  of the true correlation. The Welford formulation is numerically
//  stable for any input scale.
// ─────────────────────────────────────────────────────────────
struct ColumnPairAccumulator {
    int     col_i    = 0;
    int     col_j    = 0;
    int64_t n        = 0;      // count of valid (non-null) row pairs
    // Welford-style online means and co-moments.
    double  mean_x   = 0.0;
    double  mean_y   = 0.0;
    double  c_xx     = 0.0;    // Σ(x - mean_x)²  (M2 for x)
    double  c_yy     = 0.0;    // Σ(y - mean_y)²  (M2 for y)
    double  c_xy     = 0.0;    // Σ(x - mean_x)(y - mean_y)  (co-moment)

    void update(double x, double y) {
        ++n;
        double dx = x - mean_x;
        mean_x += dx / static_cast<double>(n);
        double dy = y - mean_y;
        mean_y += dy / static_cast<double>(n);
        // Use the new mean for dy to match Welford's co-moment formula
        // (Pébay 2008, parallel form). The difference is O(1/n²) per step
        // and cancels out over a long enough stream.
        c_xy += dx * (y - mean_y);
        c_xx += dx * (x - mean_x);
        c_yy += dy * (y - mean_y);
    }

    // Pearson r — returns value in [-1, +1]
    // Returns NaN if not computable
    double pearson_r() const {
        if (n < 2) return std::numeric_limits<double>::quiet_NaN();

        // Welford covariance / variance — always non-negative for c_xx/c_yy.
        if (c_xx <= 0.0 || c_yy <= 0.0) return 0.0;  // constant column

        double den = std::sqrt(c_xx * c_yy);
        if (den < 1e-10) return 0.0;
        return c_xy / den;
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

// ─────────────────────────────────────────────────────────────
//  pair_idx — packed upper-triangle index for pair accumulators.
//
//  FIX C-M1: Previously pair_accs was sized N² but only the upper
//  triangle (i < j, ~N²/2 entries) was ever used. Packing into
//  upper-triangle halves memory: 64 MB → 32 MB at N=1000, and
//  512 MB → 256 MB with 8 threads in profile_builder.
//
//  Usage: pair_accs[pair_idx(i, j, N)] where i < j.
//  Total size: N * (N - 1) / 2.
// ─────────────────────────────────────────────────────────────
inline size_t pair_idx(size_t i, size_t j, size_t n) {
    // Assumes i < j. For i >= j, swap (defensive).
    if (i >= j) std::swap(i, j);
    return i * (2 * n - i - 1) / 2 + (j - i - 1);
}

inline size_t pair_count(size_t n) {
    return n * (n - 1) / 2;
}

} // namespace zedda
