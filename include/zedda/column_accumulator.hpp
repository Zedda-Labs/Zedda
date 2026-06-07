#pragma once

#include <cstdint>
#include <cmath>
#include <string>
#include <string_view>
#include <limits>
#include <algorithm>

namespace zedda {

// ─────────────────────────────────────────────────────────────────
//  ColumnType — what kind of data is in this column
// ─────────────────────────────────────────────────────────────────
enum class ColumnType {
    UNKNOWN,
    INTEGER,
    FLOAT,
    STRING,
    BOOLEAN,
    DATETIME
};

inline std::string column_type_str(ColumnType t) {
    switch (t) {
        case ColumnType::INTEGER:  return "int";
        case ColumnType::FLOAT:    return "float";
        case ColumnType::STRING:   return "str";
        case ColumnType::BOOLEAN:  return "bool";
        case ColumnType::DATETIME: return "datetime";
        default:                   return "unknown";
    }
}

// ─────────────────────────────────────────────────────────────────
//  ColumnAccumulator
//
//  Single-pass, O(1) memory stats per column.
//  Call update(value) for each row. Call finalize() once at end.
//
//  Algorithm: Welford's online algorithm for mean + variance.
//  Why Welford? Naive sum^2 - (sum)^2/n causes catastrophic
//  cancellation on large datasets. Welford is numerically stable.
// ─────────────────────────────────────────────────────────────────
struct ColumnAccumulator {

    // ── identity ──────────────────────────────────────────────────
    std::string name;
    ColumnType  type = ColumnType::UNKNOWN;

    // ── counters ──────────────────────────────────────────────────
    int64_t  count      = 0;   // total rows seen
    int64_t  null_count = 0;   // null / missing rows
    int64_t  zero_count = 0;   // rows where value == 0

    // ── Welford state (numeric cols only) ─────────────────────────
    // Running mean and M2 (sum of squared deviations from mean).
    // variance = M2 / (count - null_count)
    // stddev   = sqrt(variance)
    double welford_mean = 0.0;
    double welford_M2   = 0.0;

    // ── range ─────────────────────────────────────────────────────
    double val_min = std::numeric_limits<double>::max();
    double val_max = std::numeric_limits<double>::lowest();

    // ── higher moments (for skewness + kurtosis) ──────────────────
    double M3 = 0.0;
    double M4 = 0.0;

    // ── string col stats ──────────────────────────────────────────
    int64_t min_str_len = std::numeric_limits<int64_t>::max();
    int64_t max_str_len = 0;
    double  mean_str_len = 0.0;

    // ── finalized results (populated by finalize()) ───────────────
    double mean     = 0.0;
    double variance = 0.0;
    double stddev   = 0.0;
    double skewness = 0.0;
    double kurtosis = 0.0;   // excess kurtosis (normal = 0)
    double null_pct = 0.0;

    // ─────────────────────────────────────────────────────────────
    //  update(value) — call once per non-null numeric row
    //
    //  Welford's online algorithm:
    //    delta  = x - mean
    //    mean  += delta / n
    //    delta2 = x - mean   (new mean!)
    //    M2    += delta * delta2
    // ─────────────────────────────────────────────────────────────
    void update(double value) {
        ++count;

        if (value < val_min) val_min = value;
        if (value > val_max) val_max = value;
        if (value == 0.0)    ++zero_count;

        // Welford step
        double delta  = value - welford_mean;
        welford_mean += delta / static_cast<double>(count - null_count);
        double delta2 = value - welford_mean;
        welford_M2   += delta * delta2;

        // Higher moments (Welford-style extension)
        double n = static_cast<double>(count - null_count);
        double delta_n  = delta / n;
        double term1    = delta * delta2 * (n - 1.0);
        M3 += term1 * delta_n * (n - 2.0) - 3.0 * delta_n * welford_M2;
        M4 += term1 * delta_n * delta_n * (n * n - 3.0 * n + 3.0)
            + 6.0 * delta_n * delta_n * welford_M2
            - 4.0 * delta_n * M3;
    }

    // ─────────────────────────────────────────────────────────────
    //  update_null() — call once per null/missing row
    // ─────────────────────────────────────────────────────────────
    void update_null() {
        ++count;
        ++null_count;
    }

    // ─────────────────────────────────────────────────────────────
    //  update_string() — call once per non-null string row
    // ─────────────────────────────────────────────────────────────
    void update_string(const std::string& s) {
        ++count;
        int64_t len = static_cast<int64_t>(s.size());
        min_str_len = std::min(min_str_len, len);
        max_str_len = std::max(max_str_len, len);
        double delta = static_cast<double>(len) - mean_str_len;
        mean_str_len += delta / static_cast<double>(count - null_count);
    }

    // ─────────────────────────────────────────────────────────────
    //  update_string_sv() — zero-copy string_view variant
    //  Avoids heap allocation vs update_string(std::string).
    // ─────────────────────────────────────────────────────────────
    void update_string_sv(std::string_view sv) {
        ++count;
        int64_t len = static_cast<int64_t>(sv.size());
        if (len < min_str_len) min_str_len = len;
        if (len > max_str_len) max_str_len = len;
        double delta = static_cast<double>(len) - mean_str_len;
        mean_str_len += delta / static_cast<double>(count - null_count);
    }

    // ─────────────────────────────────────────────────────────────
    //  finalize() — call ONCE after all rows processed
    //  Computes final mean, variance, stddev, skewness, kurtosis
    // ─────────────────────────────────────────────────────────────
    void finalize() {
        int64_t n = count - null_count;

        if (n < 1) {
            // All nulls — nothing to compute
            null_pct = 100.0;
            return;
        }

        null_pct = 100.0 * static_cast<double>(null_count)
                         / static_cast<double>(count);
        mean     = welford_mean;

        if (n >= 2) {
            variance = welford_M2 / static_cast<double>(n - 1); // sample variance
            stddev   = std::sqrt(variance);
        }

        // Skewness (Fisher's moment coefficient)
        // skew = (n * M3) / ((n-1) * (n-2) * stddev^3)
        if (n >= 3 && stddev > 1e-10) {
            double dn = static_cast<double>(n);
            skewness = (dn / ((dn - 1.0) * (dn - 2.0)))
                     * (M3 / (stddev * stddev * stddev));
        }

        // Excess kurtosis
        // kurt = n(n+1)/((n-1)(n-2)(n-3)) * M4/s^4
        //      - 3(n-1)^2/((n-2)(n-3))
        if (n >= 4 && stddev > 1e-10) {
            double dn  = static_cast<double>(n);
            double s4  = variance * variance;
            kurtosis = (dn * (dn + 1.0))
                     / ((dn - 1.0) * (dn - 2.0) * (dn - 3.0))
                     * (M4 / s4)
                     - 3.0 * (dn - 1.0) * (dn - 1.0)
                     / ((dn - 2.0) * (dn - 3.0));
        }
    }

    // ─────────────────────────────────────────────────────────────
    //  merge(other) — combine two parallel accumulators
    //
    //  Uses Chan et al. 1979 / Pébay 2008 parallel Welford formula.
    //  This is numerically stable and exact.
    //  Call finalize() AFTER merging all accumulators, NOT before.
    // ─────────────────────────────────────────────────────────────
    void merge(const ColumnAccumulator& o) {
        if (o.count == 0) return;

        // Save non-null counts BEFORE modifying anything
        int64_t nA = non_null_count();
        int64_t nB = o.non_null_count();

        // Merge type
        if (type == ColumnType::UNKNOWN) type = o.type;

        // Merge counts
        count      += o.count;
        null_count += o.null_count;
        zero_count += o.zero_count;

        // Merge numeric range
        if (nB > 0) {
            if (nA == 0 || o.val_min < val_min) val_min = o.val_min;
            if (nA == 0 || o.val_max > val_max) val_max = o.val_max;
        }

        // Merge string stats
        if (nB > 0 && (type == ColumnType::STRING || type == ColumnType::DATETIME)) {
            if (nA == 0) {
                min_str_len  = o.min_str_len;
                max_str_len  = o.max_str_len;
                mean_str_len = o.mean_str_len;
            } else {
                if (o.min_str_len < min_str_len) min_str_len = o.min_str_len;
                if (o.max_str_len > max_str_len) max_str_len = o.max_str_len;
                double ds = o.mean_str_len - mean_str_len;
                mean_str_len += ds * static_cast<double>(nB) / static_cast<double>(nA + nB);
            }
        }

        // Merge Welford stats using parallel merge formula
        if (nA == 0) {
            // This accumulator had no non-null values — adopt other's stats
            welford_mean = o.welford_mean;
            welford_M2   = o.welford_M2;
            M3           = o.M3;
            M4           = o.M4;
            return;
        }
        if (nB == 0) return;

        double dnA = static_cast<double>(nA);
        double dnB = static_cast<double>(nB);
        double dn  = dnA + dnB;
        double d   = o.welford_mean - welford_mean;
        double d2  = d * d;
        double d3  = d2 * d;
        double d4  = d2 * d2;

        // Compute in order M4 → M3 → M2 → mean (avoids clobbering)
        double new_M4 = M4 + o.M4
            + d4 * dnA * dnB * (dnA*dnA - dnA*dnB + dnB*dnB) / (dn*dn*dn)
            + 6.0 * d2 * (dnA*dnA * o.welford_M2 + dnB*dnB * welford_M2) / (dn*dn)
            + 4.0 * d  * (dnA * o.M3 - dnB * M3) / dn;

        double new_M3 = M3 + o.M3
            + d3 * dnA * dnB * (dnA - dnB) / (dn*dn)
            + 3.0 * d  * (dnA * o.welford_M2 - dnB * welford_M2) / dn;

        double new_M2 = welford_M2 + o.welford_M2 + d2 * dnA * dnB / dn;

        welford_mean = welford_mean + d * dnB / dn;
        welford_M2   = new_M2;
        M3           = new_M3;
        M4           = new_M4;
    }

    // ─────────────────────────────────────────────────────────────
    //  Convenience getters
    // ─────────────────────────────────────────────────────────────
    int64_t non_null_count() const { return count - null_count; }
    double  range()          const { return val_max - val_min; }
    bool    all_null()       const { return null_count == count; }
};

} // namespace zedda