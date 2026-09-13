#pragma once

#include <cstdint>
#include <cmath>
#include <string>
#include <string_view>
#include <limits>
#include <algorithm>
#include <unordered_set>
#include <vector>
#include <cstring>

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
    int64_t  count               = 0;   // total rows seen (legacy)
    int64_t  null_count          = 0;   // null / missing rows (legacy)
    int64_t  zero_count          = 0;   // rows where value == 0
    int64_t  type_mismatch_count = 0;   // rows dropped due to type mismatch
    
    // ── canonical v0.5 counters ───────────────────────────────────
    int64_t  valid_count       = 0;   // successfully parsed and non-null
    int64_t  missing_count     = 0;   // explicitly null or missing
    int64_t  invalid_count     = 0;   // type mismatch or invalid format
    int64_t  parse_error_count = 0;   // structurally malformed

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
    double type_mismatch_pct = 0.0;

    // ── Histogram reservoir (numeric cols only) ─────────────────
    // Keeps the first HISTOGRAM_RESERVOIR_CAP numeric values seen
    // by this accumulator. After all threads merge, make_column_profile()
    // computes 16-bin histogram from the merged reservoir using the
    // global min/max — no second file read required.
    static constexpr size_t HISTOGRAM_RESERVOIR_CAP = 512;
    std::vector<double> histogram_reservoir;
    uint64_t prng_state = 0x853c49e6748fea9bULL; // LCG state

    // ── Distinct string values (string / datetime cols) ────────
    // Tracks distinct values for low-cardinality string columns.
    // Once size hits DISTINCT_VALUES_CAP the set is cleared and
    // distinct_overflowed is set — memory freed immediately.
    static constexpr size_t DISTINCT_VALUES_CAP = 100'000;
    static constexpr size_t SMALL_CARD_CAP = 64;
    std::vector<std::string> small_distinct_values;
    std::unordered_set<std::string> distinct_values;
    bool distinct_overflowed = false;

    void flush_distinct() {
        if (!small_distinct_values.empty() && !distinct_overflowed) {
            for (auto& s : small_distinct_values) {
                distinct_values.insert(std::move(s));
            }
            small_distinct_values.clear();
        }
    }

    // ── Exact numeric unique tracking ────────────────────────
    // For int/float cols, track exact distinct values to fix the
    // HyperLogLog overcount on small datasets.
    static constexpr size_t EXACT_NUMERIC_CAP = 100'000;

    // FIX C-2 / BN-4: Custom hash for double to avoid std::hash collisions on adjacent integers.
    struct DoubleHash {
        std::size_t operator()(double v) const {
            if (v == 0.0) v = 0.0;  // Canonicalize -0.0 to +0.0
            uint64_t x;
            std::memcpy(&x, &v, sizeof(double));
            x ^= x >> 33;
            x *= 0xff51afd7ed558ccdULL;
            x ^= x >> 33;
            x *= 0xc4ceb9fe1a85ec53ULL;
            x ^= x >> 33;
            return static_cast<std::size_t>(x);
        }
    };
    std::unordered_set<double, DoubleHash> exact_numeric_values;
    bool exact_numeric_overflowed = false;

    // ── Exact int64 tracking ──────────────────────────────────────
    bool is_pure_int64 = true;
    int64_t exact_int_sum = 0;
    int64_t exact_int_min = std::numeric_limits<int64_t>::max();
    int64_t exact_int_max = std::numeric_limits<int64_t>::lowest();

    // Preserve Arrow 64-bit integer identity independently of double-backed
    // statistics and histogram state. Replaces exact_numeric_values when pure.
    std::unordered_set<int64_t> exact_int_values;
    bool exact_integer_overflowed = false;

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
        if (std::isnan(value) || std::isinf(value)) {
            update_null();
            return;
        }

        ++count;
        ++valid_count;

        // If a float update is called, we lose pure int64 status.
        if (is_pure_int64) {
            is_pure_int64 = false;
            // Flush exact_int_values to exact_numeric_values
            if (!exact_numeric_overflowed && !exact_integer_overflowed) {
                for (int64_t ival : exact_int_values) {
                    exact_numeric_values.insert(static_cast<double>(ival));
                    if (exact_numeric_values.size() > EXACT_NUMERIC_CAP) {
                        exact_numeric_overflowed = true;
                        exact_numeric_values.clear();
                        break;
                    }
                }
            } else {
                exact_numeric_overflowed = true;
                exact_numeric_values.clear();
            }
            exact_int_values.clear();
        }

        // SEC-C03: Defensive guard — ensure non-null count is positive
        // before performing Welford division. Should always hold, but
        // protects against edge cases in parallel merge scenarios.
        int64_t n = valid_count;
        if (n < 1) return;

        if (value < val_min) val_min = value;
        if (value > val_max) val_max = value;
        if (value == 0.0)    ++zero_count;

        // Welford step
        double delta  = value - welford_mean;
        welford_mean += delta / static_cast<double>(n);
        double delta2 = value - welford_mean;
        welford_M2   += delta * delta2;

        // Higher moments (Welford-style extension)
        double dn = static_cast<double>(n);
        double delta_n  = delta / dn;
        double term1    = delta * delta2 * (dn - 1.0);
        M3 += term1 * delta_n * (dn - 2.0) - 3.0 * delta_n * welford_M2;
        M4 += term1 * delta_n * delta_n * (dn * dn - 3.0 * dn + 3.0)
            + 6.0 * delta_n * delta_n * welford_M2
            - 4.0 * delta_n * M3;

        // Task 2.9: Deterministic representative sampling (Algorithm R)
        if (histogram_reservoir.size() < HISTOGRAM_RESERVOIR_CAP) {
            histogram_reservoir.push_back(value);
        } else {
            prng_state = prng_state * 6364136223846793005ULL + 1442695040888963407ULL;
            uint32_t r = static_cast<uint32_t>(prng_state >> 32);
            if (r % static_cast<uint32_t>(valid_count) < HISTOGRAM_RESERVOIR_CAP) {
                histogram_reservoir[r % HISTOGRAM_RESERVOIR_CAP] = value;
            }
        }

        // Exact unique tracking: cap at EXACT_NUMERIC_CAP
        if (!exact_numeric_overflowed) {
            exact_numeric_values.insert(value);
            if (exact_numeric_values.size() > EXACT_NUMERIC_CAP) {
                exact_numeric_overflowed = true;
                exact_numeric_values.clear();
            }
        }
    }

    void update_int64(int64_t value) {
        ++count;
        ++valid_count;

        if (is_pure_int64) {
            if (value < exact_int_min) exact_int_min = value;
            if (value > exact_int_max) exact_int_max = value;
            
            // Check for sum overflow
            int64_t new_sum;
            if (safe_add_int64(exact_int_sum, value, new_sum)) {
                is_pure_int64 = false; // Overflow occurred, degrade to double
            } else {
                exact_int_sum = new_sum;
            }
            
            if (is_pure_int64 && !exact_integer_overflowed) {
                exact_int_values.insert(value);
                if (exact_int_values.size() > EXACT_NUMERIC_CAP) {
                    exact_integer_overflowed = true;
                    exact_int_values.clear();
                }
            }
        }
        
        // Always run double state in parallel
        if (value == 0) ++zero_count;
        if (value < val_min) val_min = static_cast<double>(value);
        if (value > val_max) val_max = static_cast<double>(value);

        double dval = static_cast<double>(value);
        int64_t n = valid_count;
        if (n >= 1) {
            double delta  = dval - welford_mean;
            welford_mean += delta / static_cast<double>(n);
            double delta2 = dval - welford_mean;
            welford_M2   += delta * delta2;

            double dn = static_cast<double>(n);
            double delta_n  = delta / dn;
            double term1    = delta * delta2 * (dn - 1.0);
            M3 += term1 * delta_n * (dn - 2.0) - 3.0 * delta_n * welford_M2;
            M4 += term1 * delta_n * delta_n * (dn * dn - 3.0 * dn + 3.0)
                + 6.0 * delta_n * delta_n * welford_M2
                - 4.0 * delta_n * M3;
        }

        if (histogram_reservoir.size() < HISTOGRAM_RESERVOIR_CAP) {
            histogram_reservoir.push_back(dval);
        } else {
            prng_state = prng_state * 6364136223846793005ULL + 1442695040888963407ULL;
            uint32_t r = static_cast<uint32_t>(prng_state >> 32);
            if (r % static_cast<uint32_t>(valid_count) < HISTOGRAM_RESERVOIR_CAP) {
                histogram_reservoir[r % HISTOGRAM_RESERVOIR_CAP] = dval;
            }
        }
    }

    void update_uint64(uint64_t value) {
        if (value > static_cast<uint64_t>(std::numeric_limits<int64_t>::max())) {
            update(static_cast<double>(value));
        } else {
            update_int64(static_cast<int64_t>(value));
        }
    }

    // ─────────────────────────────────────────────────────────────
    //  update_null() — call once per null/missing row
    // ─────────────────────────────────────────────────────────────
    void update_null() {
        ++count;
        ++null_count;
        ++missing_count;
    }

    // ─────────────────────────────────────────────────────────────
    //  update_type_mismatch() — call once per row that violates column type
    // ─────────────────────────────────────────────────────────────
    void update_type_mismatch() {
        ++count;
        ++type_mismatch_count;
        ++invalid_count;
    }

    void update_parse_error() {
        ++count;
        ++parse_error_count;
    }

    // ─────────────────────────────────────────────────────────────
    //  update_string() — call once per non-null string row
    // ─────────────────────────────────────────────────────────────
    void update_string(const std::string& s) {
        ++count;
        ++valid_count;
        int64_t len = static_cast<int64_t>(s.size());
        min_str_len = std::min(min_str_len, len);
        max_str_len = std::max(max_str_len, len);
        double delta = static_cast<double>(len) - mean_str_len;
        mean_str_len += delta / static_cast<double>(valid_count);
    }

    static inline bool safe_add_int64(int64_t a, int64_t b, int64_t& result) {
        if (b > 0 && a > std::numeric_limits<int64_t>::max() - b) return true;
        if (b < 0 && a < std::numeric_limits<int64_t>::lowest() - b) return true;
        result = a + b;
        return false;
    }

    // ─────────────────────────────────────────────────────────────
    //  update_string_sv() — zero-copy string_view variant
    //  Avoids heap allocation vs update_string(std::string).
    // ─────────────────────────────────────────────────────────────
    void update_string_sv(std::string_view sv) {
        ++count;
        ++valid_count;
        int64_t len = static_cast<int64_t>(sv.size());
        if (len < min_str_len) min_str_len = len;
        if (len > max_str_len) max_str_len = len;
        double delta = static_cast<double>(len) - mean_str_len;
        mean_str_len += delta / static_cast<double>(valid_count);

        // Distinct value tracking: cap at DISTINCT_VALUES_CAP
        if (!distinct_overflowed) {
            if (distinct_values.empty() && small_distinct_values.size() < SMALL_CARD_CAP) {
                bool found = false;
                for (const auto& s : small_distinct_values) {
                    if (s == sv) {
                        found = true;
                        break;
                    }
                }
                if (!found) {
                    small_distinct_values.emplace_back(sv);
                }
            } else {
                if (!small_distinct_values.empty()) {
                    for (auto& s : small_distinct_values) {
                        distinct_values.insert(std::move(s));
                    }
                    small_distinct_values.clear();
                }
                distinct_values.emplace(sv);
                if (distinct_values.size() > DISTINCT_VALUES_CAP) {
                    distinct_overflowed = true;
                    distinct_values.clear();  // free memory immediately
                }
            }
        }
    }

    // ─────────────────────────────────────────────────────────────
    //  finalize() — call ONCE after all rows processed
    //  Computes final mean, variance, stddev, skewness, kurtosis
    // ─────────────────────────────────────────────────────────────
    void finalize() {
        flush_distinct();
        int64_t n = valid_count;

        if (n < 1) {
            // All nulls — nothing to compute
            null_pct = (count > 0) ? 100.0 * static_cast<double>(null_count) / static_cast<double>(count) : 0.0;
            type_mismatch_pct = (count > 0) ? 100.0 * static_cast<double>(type_mismatch_count) / static_cast<double>(count) : 0.0;
            return;
        }

        // Use full count for null_pct as expected, but ensure count > 0
        null_pct = (count > 0) ? 100.0 * static_cast<double>(null_count) / static_cast<double>(count) : 0.0;
        type_mismatch_pct = (count > 0) ? 100.0 * static_cast<double>(type_mismatch_count) / static_cast<double>(count) : 0.0;
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
        ColumnType orig_type = type;

        // FIX C-M8 / C-L6: Apply a type-promotion lattice during merge.
        // Previously, if thread 0 saw INTEGER (first non-null "1") and
        // thread 5 saw FLOAT (first non-null "1.5"), the merge kept
        // thread 0's INTEGER label — but thread 5's accumulator had
        // called update(1.5), so the final profile reported type_str="int"
        // for a column containing floats. Now we promote to the wider type.
        // Lattice: UNKNOWN < BOOLEAN < STRING < DATETIME < INTEGER < FLOAT
        // (Numeric wins over STRING so that numeric columns with garbage don't get forced to string type,
        // which restores the single-threaded v0.4.4 behavior where numeric garbage is coerced).
        auto type_rank = [](ColumnType t) -> int {
            switch (t) {
                case ColumnType::UNKNOWN:  return 0;
                case ColumnType::BOOLEAN:  return 1;
                case ColumnType::STRING:   return 2;
                case ColumnType::DATETIME: return 3;
                case ColumnType::INTEGER:  return 4;
                case ColumnType::FLOAT:    return 5;
            }
            return 0;
        };
        if (type_rank(o.type) > type_rank(type)) {
            type = o.type;
        }

        int64_t new_mismatch_from_a = 0;
        int64_t new_mismatch_from_b = 0;

        if (type == ColumnType::INTEGER || type == ColumnType::FLOAT) {
            if (orig_type != ColumnType::INTEGER && orig_type != ColumnType::FLOAT && orig_type != ColumnType::UNKNOWN) {
                new_mismatch_from_a = valid_count; // The ones that were considered valid strings
            }
            if (o.type != ColumnType::INTEGER && o.type != ColumnType::FLOAT && o.type != ColumnType::UNKNOWN) {
                new_mismatch_from_b = o.valid_count;
            }
        }

        // Merge counts
        count               += o.count;
        null_count          += o.null_count;
        zero_count          += o.zero_count;
        
        type_mismatch_count += o.type_mismatch_count + new_mismatch_from_a + new_mismatch_from_b;
        invalid_count       += o.invalid_count + new_mismatch_from_a + new_mismatch_from_b;
        
        valid_count         = valid_count + o.valid_count - new_mismatch_from_a - new_mismatch_from_b;
        missing_count       += o.missing_count;
        parse_error_count   += o.parse_error_count;

        // Threads that accumulated strings have invalid numeric stats. Filter them out.
        int64_t numA = (orig_type == ColumnType::INTEGER || orig_type == ColumnType::FLOAT) ? nA : 0;
        int64_t numB = (o.type == ColumnType::INTEGER || o.type == ColumnType::FLOAT) ? nB : 0;

        // Merge exact int64 tracking
        if (is_pure_int64 && o.is_pure_int64) {
            if (numB > 0) {
                if (numA == 0 || o.exact_int_min < exact_int_min) exact_int_min = o.exact_int_min;
                if (numA == 0 || o.exact_int_max > exact_int_max) exact_int_max = o.exact_int_max;
                
                int64_t new_sum;
                if (safe_add_int64(exact_int_sum, o.exact_int_sum, new_sum)) {
                    is_pure_int64 = false;
                } else {
                    exact_int_sum = new_sum;
                }
            }
        } else {
            is_pure_int64 = false;
        }

        // Flush local exact_int_values if local lost purity
        if (!is_pure_int64 && !exact_int_values.empty()) {
            if (!exact_numeric_overflowed && !exact_integer_overflowed) {
                for (int64_t ival : exact_int_values) {
                    exact_numeric_values.insert(static_cast<double>(ival));
                    if (exact_numeric_values.size() > EXACT_NUMERIC_CAP) {
                        exact_numeric_overflowed = true;
                        exact_numeric_values.clear();
                        break;
                    }
                }
            } else {
                exact_numeric_overflowed = true;
                exact_numeric_values.clear();
            }
            exact_int_values.clear();
        }

        // Merge numeric range
        if (numB > 0) {
            if (numA == 0 || o.val_min < val_min) val_min = o.val_min;
            if (numA == 0 || o.val_max > val_max) val_max = o.val_max;
        }

        // FIX C-L6: Merge string stats whenever EITHER side has STRING/DATETIME
        // type (was: only when local type is STRING/DATETIME — silently dropped
        // string stats from thread 5 if thread 0 saw INTEGER).
        if (nB > 0 && (o.type == ColumnType::STRING || o.type == ColumnType::DATETIME
                       || type == ColumnType::STRING || type == ColumnType::DATETIME)) {
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

        // ── Merge distinct string values ────────────────────────
        flush_distinct();
        if (!distinct_overflowed && !o.distinct_overflowed) {
            for (const auto& s : o.small_distinct_values) {
                distinct_values.insert(s);
                if (distinct_values.size() > DISTINCT_VALUES_CAP) {
                    distinct_overflowed = true;
                    distinct_values.clear();
                    break;
                }
            }
            if (!distinct_overflowed) {
                for (const auto& s : o.distinct_values) {
                    distinct_values.insert(s);
                    if (distinct_values.size() > DISTINCT_VALUES_CAP) {
                        distinct_overflowed = true;
                        distinct_values.clear();
                        break;
                    }
                }
            }
        } else {
            distinct_overflowed = true;
            distinct_values.clear();
        }

        // Task 2.9: Deterministic proportional merge for representative sampling
        // FIX C-3: Properly merge reservoirs with probability proportional to thread weights,
        // rather than deterministic biased slicing.
        if (!o.histogram_reservoir.empty()) {
            std::vector<double> merged;
            merged.reserve(HISTOGRAM_RESERVOIR_CAP);
            
            double total_n = static_cast<double>(numA + numB);
            size_t a_size = histogram_reservoir.size();
            size_t b_size = o.histogram_reservoir.size();
            
            for (size_t i = 0; i < HISTOGRAM_RESERVOIR_CAP; ++i) {
                if (a_size == 0 && b_size == 0) break;
                
                prng_state = prng_state * 6364136223846793005ULL + 1442695040888963407ULL;
                double r = static_cast<double>(prng_state >> 11) * (1.0 / 9007199254740992.0);
                
                if ((a_size > 0 && r < (static_cast<double>(numA) / total_n)) || b_size == 0) {
                    prng_state = prng_state * 6364136223846793005ULL + 1442695040888963407ULL;
                    merged.push_back(histogram_reservoir[prng_state % a_size]);
                } else {
                    prng_state = prng_state * 6364136223846793005ULL + 1442695040888963407ULL;
                    merged.push_back(o.histogram_reservoir[prng_state % b_size]);
                }
            }
            histogram_reservoir = std::move(merged);
        }

        // ── Merge exact numeric unique set ───────────────────
        if (!exact_numeric_overflowed && !o.exact_numeric_overflowed) {
            for (double v : o.exact_numeric_values) {
                exact_numeric_values.insert(v);
                if (exact_numeric_values.size() > EXACT_NUMERIC_CAP) {
                    exact_numeric_overflowed = true;
                    exact_numeric_values.clear();
                    break;
                }
            }
        } else {
            exact_numeric_overflowed = true;
            exact_numeric_values.clear();
        }

        if (!exact_integer_overflowed && !o.exact_integer_overflowed) {
            for (int64_t value : o.exact_int_values) {
                if (is_pure_int64) {
                    exact_int_values.insert(value);
                    if (exact_int_values.size() > EXACT_NUMERIC_CAP) {
                        exact_integer_overflowed = true;
                        exact_int_values.clear();
                        break;
                    }
                } else {
                    exact_numeric_values.insert(static_cast<double>(value));
                    if (exact_numeric_values.size() > EXACT_NUMERIC_CAP) {
                        exact_numeric_overflowed = true;
                        exact_numeric_values.clear();
                        break;
                    }
                }
            }
        } else {
            if (is_pure_int64) {
                exact_integer_overflowed = true;
                exact_int_values.clear();
            } else {
                exact_numeric_overflowed = true;
                exact_numeric_values.clear();
            }
        }

        // Merge Welford stats using parallel merge formula
        if (numA == 0) {
            // This accumulator had no non-null values — adopt other's stats
            welford_mean = o.welford_mean;
            welford_M2   = o.welford_M2;
            M3           = o.M3;
            M4           = o.M4;
            return;
        }
        if (numB == 0) return;

        double dnA = static_cast<double>(numA);
        double dnB = static_cast<double>(numB);
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
    // FIX C-6: Return explicitly valid count instead of total count - null_count,
    // which incorrectly included type mismatches and parse errors.
    int64_t non_null_count() const { return valid_count; }
    double  range()          const { return val_max - val_min; }
    bool    all_null()       const { return null_count == count; }
};

} // namespace zedda
