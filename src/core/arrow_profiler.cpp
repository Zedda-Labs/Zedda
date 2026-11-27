#include "zedda/arrow_profiler.hpp"
#include <cstring>
#include <stdexcept>
#include <iostream>
#include <cmath>
#include <algorithm>

namespace zedda {

namespace {

inline bool arrow_is_null(const uint8_t* validity_bitmap, int64_t index) {
    if (!validity_bitmap) return false;
    return (validity_bitmap[index / 8] & (1 << (index % 8))) == 0;
}

double float16_to_double(uint16_t h) {
    uint32_t sign = (h >> 15) & 0x1;
    uint32_t exp  = (h >> 10) & 0x1f;
    uint32_t frac =  h        & 0x3ff;
    float val;
    if (exp == 0) {
        if (frac == 0) {
            val = sign ? -0.0f : 0.0f;
        } else {
            exp = 1;
            while ((frac & 0x400) == 0) { frac <<= 1; exp--; }
            frac &= 0x3ff;
            uint32_t f32 = (sign << 31) | ((exp + 112) << 23) | (frac << 13);
            std::memcpy(&val, &f32, 4);
        }
    } else if (exp == 31) {
        uint32_t f32 = (sign << 31) | 0x7f800000 | (frac << 13);
        std::memcpy(&val, &f32, 4);
    } else {
        uint32_t f32 = (sign << 31) | ((exp + 112) << 23) | (frac << 13);
        std::memcpy(&val, &f32, 4);
    }
    return static_cast<double>(val);
}

template <typename IntT>
void consume_int_col(
    struct ArrowArray* child,
    const uint8_t* validity_bitmap,
    int64_t num_rows,
    const void* buf1,
    ColumnAccumulator& acc,
    HyperLogLog& hll)
{
    const IntT* data = reinterpret_cast<const IntT*>(buf1);
    for (int64_t i = 0; i < num_rows; ++i) {
        int64_t idx = i + child->offset;
        if (arrow_is_null(validity_bitmap, idx) || data == nullptr) {
            acc.update_null();
        } else {
            int64_t v = static_cast<int64_t>(data[idx]);
            acc.update_int64(v);
            hll.add(static_cast<double>(v));
        }
    }
}

template <typename OffsetT>
void consume_varlen_col(
    struct ArrowArray* child,
    const uint8_t* validity_bitmap,
    int64_t num_rows,
    ColumnAccumulator& acc,
    HyperLogLog& hll)
{
    const OffsetT* offsets = (child->n_buffers > 1 && child->buffers[1])
        ? reinterpret_cast<const OffsetT*>(child->buffers[1]) : nullptr;
    const char* str_data = (child->n_buffers > 2 && child->buffers[2])
        ? reinterpret_cast<const char*>(child->buffers[2]) : nullptr;

    for (int64_t i = 0; i < num_rows; ++i) {
        int64_t adj_i = i + child->offset;
        if (arrow_is_null(validity_bitmap, adj_i) || offsets == nullptr) {
            acc.update_null();
        } else {
            OffsetT start = offsets[adj_i];
            OffsetT end   = offsets[adj_i + 1];
            OffsetT len   = end - start;
            if (str_data != nullptr && len > 0) {
                std::string_view sv(str_data + start, static_cast<size_t>(len));
                acc.update_string_sv(sv);
                hll.add(sv);
            } else {
                acc.update_string_sv("");
                hll.add(std::string_view(""));
            }
        }
    }
}

enum class ArrowNumFormat { I8, U8, I16, U16, I32, U32, I64, U64, F16, F32, F64, NONE };

ArrowNumFormat get_num_format(std::string_view fmt) {
    if (fmt == "c") return ArrowNumFormat::I8;
    if (fmt == "C") return ArrowNumFormat::U8;
    if (fmt == "s") return ArrowNumFormat::I16;
    if (fmt == "S") return ArrowNumFormat::U16;
    if (fmt == "i") return ArrowNumFormat::I32;
    if (fmt == "I") return ArrowNumFormat::U32;
    if (fmt == "l") return ArrowNumFormat::I64;
    if (fmt == "L") return ArrowNumFormat::U64;
    if (fmt == "e") return ArrowNumFormat::F16;
    if (fmt == "f") return ArrowNumFormat::F32;
    if (fmt == "g") return ArrowNumFormat::F64;
    return ArrowNumFormat::NONE;
}

double read_arrow_numeric(ArrowNumFormat nf, const void* raw, int64_t idx) {
    switch (nf) {
        case ArrowNumFormat::I8:  return static_cast<double>(reinterpret_cast<const int8_t*>(raw)[idx]);
        case ArrowNumFormat::U8:  return static_cast<double>(reinterpret_cast<const uint8_t*>(raw)[idx]);
        case ArrowNumFormat::I16: return static_cast<double>(reinterpret_cast<const int16_t*>(raw)[idx]);
        case ArrowNumFormat::U16: return static_cast<double>(reinterpret_cast<const uint16_t*>(raw)[idx]);
        case ArrowNumFormat::I32: return static_cast<double>(reinterpret_cast<const int32_t*>(raw)[idx]);
        case ArrowNumFormat::U32: return static_cast<double>(reinterpret_cast<const uint32_t*>(raw)[idx]);
        case ArrowNumFormat::I64: return static_cast<double>(reinterpret_cast<const int64_t*>(raw)[idx]);
        case ArrowNumFormat::U64: return static_cast<double>(reinterpret_cast<const uint64_t*>(raw)[idx]);
        case ArrowNumFormat::F16: return float16_to_double(reinterpret_cast<const uint16_t*>(raw)[idx]);
        case ArrowNumFormat::F32: return static_cast<double>(reinterpret_cast<const float*>(raw)[idx]);
        case ArrowNumFormat::F64: return reinterpret_cast<const double*>(raw)[idx];
        case ArrowNumFormat::NONE: return 0.0;
    }
    return 0.0;
}

} // namespace

ArrowProfiler::ArrowProfiler(const std::string& file_name, int64_t total_rows, bool correlate)
    : file_name_(file_name), total_rows_(total_rows), correlate_(correlate) {}
// FIX C-L5: Destructor declared as = default in header (no out-of-line definition needed).

bool ArrowProfiler::is_null(const uint8_t* validity_bitmap, int64_t index) {
    return arrow_is_null(validity_bitmap, index);
}

void ArrowProfiler::initialize_columns(struct ArrowSchema* schema) {
    int64_t num_cols = schema->n_children;
    accs_.resize(num_cols);
    hlls_.resize(num_cols);
    format_strings_.resize(num_cols);
    unsupported_types_.resize(num_cols);

    int64_t numeric_cols = 0;
    for (int64_t i = 0; i < num_cols; ++i) {
        struct ArrowSchema* child = schema->children[i];
        accs_[i].name = child->name ? child->name : "";
        format_strings_[i] = child->format ? child->format : "";
        
        std::string_view fmt(format_strings_[i]);
        if (fmt == "c" || fmt == "C" || fmt == "s" || fmt == "S" || 
            fmt == "i" || fmt == "I" || fmt == "l" || fmt == "L") {
            accs_[i].type = ColumnType::INTEGER;
            ++numeric_cols;
        } else if (fmt == "e" || fmt == "f" || fmt == "g") {
            accs_[i].type = ColumnType::FLOAT;
            ++numeric_cols;
        } else if (fmt == "b") {
            accs_[i].type = ColumnType::BOOLEAN;
        } else if (fmt == "u" || fmt == "U" || fmt == "z" || fmt == "Z") {
            accs_[i].type = ColumnType::STRING;
        } else if (fmt.length() >= 2 && (fmt.substr(0, 2) == "td" || fmt.substr(0, 2) == "tt" || fmt.substr(0, 2) == "ts")) {
            accs_[i].type = ColumnType::DATETIME;
        } else {
            accs_[i].type = ColumnType::UNKNOWN;
            unsupported_types_[i] = format_strings_[i];
        }
    }

    // Skip O(n^2) correlation matrix above MAX_CORR_NUMERIC_COLS numeric columns unless correlate=true.
    if (!skip_correlation_overridden_) {
        skip_correlation_ = !correlate_ && (numeric_cols > MAX_CORR_NUMERIC_COLS);
    }
    if (!skip_correlation_) {
        pair_accs_.resize(pair_count(num_cols));
        for (int64_t i = 0; i < num_cols; ++i) {
            for (int64_t j = i + 1; j < num_cols; ++j) {
                pair_accs_[pair_idx(i, j, num_cols)].col_i = static_cast<int>(i);
                pair_accs_[pair_idx(i, j, num_cols)].col_j = static_cast<int>(j);
            }
        }
    }
    
    initialized_ = true;
}

void ArrowProfiler::consume_batch(uintptr_t schema_ptr, uintptr_t array_ptr) {
    if (finalized_) {
        throw std::runtime_error("[zedda] Cannot consume batch after profiler is finalized");
    }

    // SEC-C07: Validate Arrow pointers before dereferencing
    if (schema_ptr == 0 || array_ptr == 0) {
        throw std::runtime_error("[zedda] Null Arrow schema/array pointer passed to consume_batch");
    }

    struct ArrowSchema* schema = reinterpret_cast<struct ArrowSchema*>(schema_ptr);
    struct ArrowArray* array = reinterpret_cast<struct ArrowArray*>(array_ptr);

    // SEC-C07: Validate release callbacks (null release = already consumed or invalid)
    if (schema->release == nullptr) {
        throw std::runtime_error("[zedda] Arrow schema has null release callback — already consumed or invalid");
    }
    if (array->release == nullptr) {
        throw std::runtime_error("[zedda] Arrow array has null release callback — already consumed or invalid");
    }

    // RAII guard to ensure Arrow C Data interface release callbacks are invoked
    // exactly once after consumption, preventing PyArrow buffer memory leaks.
    struct ArrowReleaseGuard {
        struct ArrowSchema* sch;
        struct ArrowArray* arr;
        ~ArrowReleaseGuard() {
            if (arr && arr->release) {
                arr->release(arr);
            }
            if (sch && sch->release) {
                sch->release(sch);
            }
        }
    } release_guard{schema, array};

    // SEC-C07: Validate column count consistency
    if (!initialized_ && schema->n_children != array->n_children) {
        throw std::runtime_error(
            "[zedda] Arrow schema/array column count mismatch: schema=" +
            std::to_string(schema->n_children) + " array=" +
            std::to_string(array->n_children));
    }
    
    if (!initialized_) {
        initialize_columns(schema);
    }

    if (initialized_) {
        if (static_cast<size_t>(schema->n_children) != accs_.size() ||
            static_cast<size_t>(array->n_children) != accs_.size()) {

            throw std::runtime_error(
                "[zedda] Arrow batch column count mismatch: schema=" +
                std::to_string(schema->n_children) +
                " array=" +
                std::to_string(array->n_children) +
                " expected=" +
                std::to_string(accs_.size()));
        }

        // SEC-C07 / Task 2.7: Validate schema compatibility across batches
        for (int64_t i = 0; i < schema->n_children; ++i) {
            struct ArrowSchema* child = schema->children[i];
            std::string name = child->name ? child->name : "";
            std::string fmt = child->format ? child->format : "";
            if (name != accs_[i].name || fmt != format_strings_[i]) {
                throw std::runtime_error(
                    "[zedda] Arrow batch schema mismatch at column " + std::to_string(i) +
                    ": expected name='" + accs_[i].name + "', format='" + format_strings_[i] +
                    "'; got name='" + name + "', format='" + fmt + "'");
            }
        }
    }

    int64_t num_rows = array->length;
    rows_processed_ += num_rows;

    for (int64_t col = 0; col < array->n_children; ++col) {
        struct ArrowArray* child = array->children[col];
        ColumnType type = accs_[col].type;
        std::string_view fmt = format_strings_[col];

        const uint8_t* validity_bitmap = nullptr;
        if (child->n_buffers > 0 && child->buffers != nullptr && child->buffers[0] != nullptr) {
            validity_bitmap = reinterpret_cast<const uint8_t*>(child->buffers[0]);
        }

        if (child->null_count == num_rows) {
            for (int64_t i = 0; i < num_rows; ++i) accs_[col].update_null();
            continue;
        }

        // We only parse types we care about natively, others become UNKNOWN/NULL equivalent.
        // FIX C-H5: Add explicit branches for int8/16/uint32/64 (c,C,s,S,I,L),
        // float16 (e), boolean (b), and datetime (t*).
        if (type == ColumnType::INTEGER) {
            const void* buf1 = (child->buffers && child->n_buffers > 1) ? child->buffers[1] : nullptr;
            if (fmt == "i")      consume_int_col<int32_t>(child, validity_bitmap, num_rows, buf1, accs_[col], hlls_[col]);
            else if (fmt == "l") consume_int_col<int64_t>(child, validity_bitmap, num_rows, buf1, accs_[col], hlls_[col]);
            else if (fmt == "c") consume_int_col<int8_t>(child, validity_bitmap, num_rows, buf1, accs_[col], hlls_[col]);
            else if (fmt == "C") consume_int_col<uint8_t>(child, validity_bitmap, num_rows, buf1, accs_[col], hlls_[col]);
            else if (fmt == "s") consume_int_col<int16_t>(child, validity_bitmap, num_rows, buf1, accs_[col], hlls_[col]);
            else if (fmt == "S") consume_int_col<uint16_t>(child, validity_bitmap, num_rows, buf1, accs_[col], hlls_[col]);
            else if (fmt == "I") consume_int_col<uint32_t>(child, validity_bitmap, num_rows, buf1, accs_[col], hlls_[col]);
            else if (fmt == "L") { // uint64
                const uint64_t* data = reinterpret_cast<const uint64_t*>(buf1);
                for (int64_t i = 0; i < num_rows; ++i) {
                    int64_t idx = i + child->offset;
                    if (is_null(validity_bitmap, idx) || data == nullptr) accs_[col].update_null();
                    else { accs_[col].update_uint64(data[idx]); hlls_[col].add(static_cast<double>(data[idx])); }
                }
            } else {
                for (int64_t i = 0; i < num_rows; ++i) accs_[col].update_null();
            }
        } else if (type == ColumnType::FLOAT) {
            const void* buf1 = (child->buffers && child->n_buffers > 1) ? child->buffers[1] : nullptr;
            if (fmt == "f") { // float32
                const float* data = reinterpret_cast<const float*>(buf1);
                for (int64_t i = 0; i < num_rows; ++i) {
                    if (is_null(validity_bitmap, i + child->offset) || data == nullptr) accs_[col].update_null();
                    else { double val = static_cast<double>(data[i + child->offset]); accs_[col].update(val); hlls_[col].add(val); }
                }
            } else if (fmt == "g") { // float64
                const double* data = reinterpret_cast<const double*>(buf1);
                for (int64_t i = 0; i < num_rows; ++i) {
                    if (is_null(validity_bitmap, i + child->offset) || data == nullptr) accs_[col].update_null();
                    else { double val = data[i + child->offset]; accs_[col].update(val); hlls_[col].add(val); }
                }
            } else if (fmt == "e") { // float16
                const uint16_t* data = reinterpret_cast<const uint16_t*>(buf1);
                for (int64_t i = 0; i < num_rows; ++i) {
                    if (is_null(validity_bitmap, i + child->offset) || data == nullptr) accs_[col].update_null();
                    else {
                        double val = float16_to_double(data[i + child->offset]);
                        accs_[col].update(val);
                        hlls_[col].add(val);
                    }
                }
            } else {
                for (int64_t i = 0; i < num_rows; ++i) accs_[col].update_null();
            }
        } else if (type == ColumnType::BOOLEAN && fmt == "b") {
            // FIX C-H5: Handle boolean columns (was silently all-null).
            const uint8_t* data = (child->buffers && child->n_buffers > 1) ? reinterpret_cast<const uint8_t*>(child->buffers[1]) : nullptr;
            for (int64_t i = 0; i < num_rows; ++i) {
                if (is_null(validity_bitmap, i + child->offset) || data == nullptr) accs_[col].update_null();
                else {
                    int64_t bit_i = i + child->offset;
                    double val = (data[bit_i / 8] & (1 << (bit_i % 8))) ? 1.0 : 0.0;
                    accs_[col].update(val);
                    hlls_[col].add(val);
                }
            }
        } else if (type == ColumnType::DATETIME) {
            const void* buf1 = (child->buffers && child->n_buffers > 1) ? child->buffers[1] : nullptr;
            if (fmt == "tdD" || fmt == "tts" || fmt == "ttm") {
                // 32-bit physical width
                const int32_t* data = reinterpret_cast<const int32_t*>(buf1);
                for (int64_t i = 0; i < num_rows; ++i) {
                    if (is_null(validity_bitmap, i + child->offset) || data == nullptr) accs_[col].update_null();
                    else { double val = static_cast<double>(data[i + child->offset]); accs_[col].update(val); hlls_[col].add(val); }
                }
            } else {
                // 64-bit physical width (tdm, ttu, ttn, ts...)
                const int64_t* data = reinterpret_cast<const int64_t*>(buf1);
                for (int64_t i = 0; i < num_rows; ++i) {
                    if (is_null(validity_bitmap, i + child->offset) || data == nullptr) accs_[col].update_null();
                    else { double val = static_cast<double>(data[i + child->offset]); accs_[col].update(val); hlls_[col].add(val); }
                }
            }
        } else if (type == ColumnType::STRING && (fmt == "u" || fmt == "z")) {
            consume_varlen_col<int32_t>(child, validity_bitmap, num_rows, accs_[col], hlls_[col]);
        } else if (type == ColumnType::STRING && (fmt == "U" || fmt == "Z")) {
            consume_varlen_col<int64_t>(child, validity_bitmap, num_rows, accs_[col], hlls_[col]);
        } else {
            // Unhandled types — record as null and log a warning.
            // FIX C-L4: Only warn once per format string to prevent log spam
            // (was 1000× identical warnings for long batch streams).
            std::string fmt_key(fmt);
            if (warned_formats_.find(fmt_key) == warned_formats_.end()) {
                warned_formats_.insert(fmt_key);
                std::cerr << "[zedda warning] Column '" << (schema->children[col]->name ? schema->children[col]->name : "unknown")
                          << "' has unsupported Arrow format '" << fmt
                          << "' - falling back to all-null processing.\n";
            }
            for (int64_t i = 0; i < num_rows; ++i) accs_[col].update_null();
        }
    }

    // ── Update Pair Accumulators for Correlation (SEC-C01: skip if wide) ──
    if (!skip_correlation_) {
    size_t ncols = accs_.size();
    for (size_t i = 0; i < ncols; ++i) {
        if (accs_[i].type != ColumnType::INTEGER && accs_[i].type != ColumnType::FLOAT) continue;
        struct ArrowArray* child_i = array->children[i];
        if (child_i->null_count == num_rows) continue;
        ArrowNumFormat nf_i = get_num_format(format_strings_[i]);
        if (nf_i == ArrowNumFormat::NONE || !child_i->buffers || child_i->n_buffers < 2 || !child_i->buffers[1]) continue;

        const uint8_t* val_i = (child_i->n_buffers > 0 && child_i->buffers[0]) ? reinterpret_cast<const uint8_t*>(child_i->buffers[0]) : nullptr;
        const void* raw_i = child_i->buffers[1];

        for (size_t j = i + 1; j < ncols; ++j) {
            if (accs_[j].type != ColumnType::INTEGER && accs_[j].type != ColumnType::FLOAT) continue;
            struct ArrowArray* child_j = array->children[j];
            if (child_j->null_count == num_rows) continue;
            ArrowNumFormat nf_j = get_num_format(format_strings_[j]);
            if (nf_j == ArrowNumFormat::NONE || !child_j->buffers || child_j->n_buffers < 2 || !child_j->buffers[1]) continue;

            const uint8_t* val_j = (child_j->n_buffers > 0 && child_j->buffers[0]) ? reinterpret_cast<const uint8_t*>(child_j->buffers[0]) : nullptr;
            const void* raw_j = child_j->buffers[1];

            auto& pa = pair_accs_[pair_idx(i, j, ncols)];

            for (int64_t row = 0; row < num_rows; ++row) {
                int64_t idx_i = row + child_i->offset;
                int64_t idx_j = row + child_j->offset;
                if (is_null(val_i, idx_i) || is_null(val_j, idx_j)) continue;

                double x = read_arrow_numeric(nf_i, raw_i, idx_i);
                double y = read_arrow_numeric(nf_j, raw_j, idx_j);
                if (std::isfinite(x) && std::isfinite(y)) {
                    pa.update(x, y);
                }
            }
        }
    }
    } // end skip_correlation_ guard

    // NOTE: Do NOT call schema->release() or array->release() here.
    // PyArrow set those release callbacks and owns the memory.
    // Calling release() from C++ would cause a double-free / crash.
    // PyArrow frees the structs when the Python batch object is GC'd.
}

DatasetProfile ArrowProfiler::finalize() {
    if (finalized_) {
        return cached_profile_;
    }

    DatasetProfile profile;
    profile.file_name = file_name_;
    profile.file_path = file_name_;
    profile.num_rows = total_rows_;
    profile.num_cols = accs_.size();
    profile.scan_time_ms = 0;
    profile.correlation_skipped = skip_correlation_;

    int64_t total_null_cells = 0;
    for (size_t i = 0; i < accs_.size(); ++i) {
        accs_[i].finalize();
        
        ColumnProfile cp;
        cp.name = accs_[i].name;
        cp.type_str = column_type_str(accs_[i].type);
        cp.total_count = accs_[i].count;
        cp.null_count = accs_[i].null_count;
        cp.non_null_count = accs_[i].non_null_count();
        cp.null_pct = accs_[i].null_pct;
        cp.unique_approx = hlls_[i].count();
        cp.unique_pct = (accs_[i].valid_count > 0)
            ? (100.0 * cp.unique_approx / accs_[i].valid_count)
            : 0.0;
        
        // Add new canonical counters
        cp.valid_count = accs_[i].valid_count;
        cp.missing_count = accs_[i].null_count;
        cp.invalid_count = accs_[i].invalid_count;
        cp.parse_error_count = accs_[i].parse_error_count;
        if (!unsupported_types_[i].empty()) {
            cp.unsupported_types.push_back(unsupported_types_[i]);
        }
        
        if (accs_[i].type == ColumnType::INTEGER || accs_[i].type == ColumnType::FLOAT || accs_[i].type == ColumnType::BOOLEAN) {
            cp.mean = accs_[i].mean;
            cp.stddev = accs_[i].stddev;
            cp.variance = accs_[i].variance;
            cp.skewness = accs_[i].skewness;
            cp.kurtosis = accs_[i].kurtosis;
            if (cp.valid_count > 0) {
                cp.val_min = accs_[i].val_min;
                cp.val_max = accs_[i].val_max;
                cp.range = accs_[i].range();
                
                cp.is_pure_int64 = accs_[i].is_pure_int64;
                cp.exact_numeric_overflowed = accs_[i].exact_numeric_overflowed;
                if (accs_[i].is_pure_int64) {
                    cp.exact_int_min = accs_[i].exact_int_min;
                    cp.exact_int_max = accs_[i].exact_int_max;
                    cp.exact_int_sum = accs_[i].exact_int_sum;
                }
            }
        }
        
        if (accs_[i].type == ColumnType::STRING || accs_[i].type == ColumnType::DATETIME) {
            if (cp.valid_count > 0) {
                cp.min_str_len = accs_[i].min_str_len;
                cp.max_str_len = accs_[i].max_str_len;
                cp.mean_str_len = accs_[i].mean_str_len;
            }
        }
        
        cp.has_high_nulls = cp.null_pct > 20.0;
        cp.is_constant = cp.unique_approx <= 1;
        cp.is_high_cardinality = cp.unique_pct > 90.0;

        // ── Histogram bins (numeric cols, from merged reservoir) ───
        if ((accs_[i].type == ColumnType::INTEGER || accs_[i].type == ColumnType::FLOAT)
            && !accs_[i].histogram_reservoir.empty()
            && cp.val_max > cp.val_min) {
            double range_v = cp.val_max - cp.val_min;
            std::array<int64_t, 16> bins = {};
            for (double v : accs_[i].histogram_reservoir) {
                int idx = static_cast<int>((v - cp.val_min) / range_v * 16);
                if (idx >= 16) idx = 15;
                if (idx < 0)  idx = 0;
                ++bins[idx];
            }
            cp.histogram_bins = bins;
        } else if ((accs_[i].type == ColumnType::INTEGER || accs_[i].type == ColumnType::FLOAT)
                   && cp.val_min == cp.val_max && cp.valid_count > 0) {
            cp.histogram_bins[0] = cp.valid_count;
        }

        // ── Distinct string values / top_values ────────────────
        if ((accs_[i].type == ColumnType::STRING || accs_[i].type == ColumnType::DATETIME)
            && !accs_[i].distinct_overflowed) {
            cp.top_values.assign(accs_[i].distinct_values.begin(), accs_[i].distinct_values.end());
            std::sort(cp.top_values.begin(), cp.top_values.end());
            cp.unique_exact       = static_cast<int64_t>(cp.top_values.size());
            cp.exact_unique_valid = true;
            cp.unique_approx      = cp.unique_exact;
            
            if (cp.top_values.size() > 100) {
                cp.top_values.resize(100);
            }
        }

        // ── Exact numeric unique count ──────────────────────
        if (accs_[i].type == ColumnType::INTEGER) {
            if (!accs_[i].exact_integer_overflowed) {
                cp.unique_exact = static_cast<int64_t>(
                    accs_[i].exact_int_values.size() + accs_[i].exact_uint_values.size());
                cp.exact_unique_valid = true;
                cp.unique_approx      = cp.unique_exact;
                cp.unique_pct = (cp.valid_count > 0)
                    ? 100.0 * static_cast<double>(cp.unique_exact) / cp.valid_count
                    : 0.0;
                for (int64_t v : accs_[i].exact_int_values) {
                    cp.top_values.push_back(std::to_string(v));
                }
                for (uint64_t v : accs_[i].exact_uint_values) {
                    cp.top_values.push_back(std::to_string(v));
                }
                std::sort(cp.top_values.begin(), cp.top_values.end());
                if (cp.top_values.size() > 100) {
                    cp.top_values.resize(100);
                }
            }
        } else if (accs_[i].type == ColumnType::FLOAT) {
            if (!accs_[i].exact_numeric_overflowed) {
                cp.unique_exact       = static_cast<int64_t>(accs_[i].exact_numeric_values.size());
                cp.exact_unique_valid = true;
                cp.unique_approx      = cp.unique_exact;
                cp.unique_pct = (cp.valid_count > 0)
                    ? 100.0 * static_cast<double>(cp.unique_exact) / cp.valid_count
                    : 0.0;
                for (double v : accs_[i].exact_numeric_values) {
                    cp.top_values.push_back(std::to_string(v));
                }
                std::sort(cp.top_values.begin(), cp.top_values.end());
                if (cp.top_values.size() > 100) {
                    cp.top_values.resize(100);
                }
            }
        }
        
        total_null_cells += cp.null_count;
        
        if (cp.type_str == "int" || cp.type_str == "float" || cp.type_str == "bool") {
            profile.num_numeric++;
        } else {
            profile.num_string++;
        }
        
        profile.columns.push_back(std::move(cp));
    }
    
    // Compute pearson correlations (SEC-C01: skip if wide)
    if (!skip_correlation_) {
        for (size_t i = 0; i < accs_.size(); ++i) {
            if (profile.columns[i].type_str != "int" && profile.columns[i].type_str != "float") continue;
            for (size_t j = i + 1; j < accs_.size(); ++j) {
                if (profile.columns[j].type_str != "int" && profile.columns[j].type_str != "float") continue;
                
                // FIX C-M1: Use packed upper-triangle index.
                auto& pa = pair_accs_[pair_idx(i, j, accs_.size())];
                double r = pa.pearson_r();
                // Correlation threshold 0.5 (Moderate Effect Size)
                // Justification: In EDA, we want to surface potential relationships 
                // for further investigation. According to Cohen's standard (1988), 
                // |r| >= 0.5 represents a "large" effect size in social sciences, 
                // and a "moderate" effect in hard sciences. This strikes a balance 
                // between missing weak signals and surfacing spurious noise.
                if (!std::isnan(r) && std::abs(r) >= 0.5) {
                    CorrelationResult cr;
                    cr.col_a = accs_[i].name;
                    cr.col_b = accs_[j].name;
                    cr.r = r;
                    cr.direction = (r > 0) ? "positive" : "negative";
                    cr.strength = CorrelationResult::get_strength(r);
                    profile.correlations.push_back(cr);
                }
            }
        }
        std::sort(profile.correlations.begin(), profile.correlations.end(),
            [](const CorrelationResult& a, const CorrelationResult& b) {
                return std::abs(a.r) > std::abs(b.r);
            });
    }

    profile.total_cells = profile.num_rows * profile.num_cols;
    profile.total_null_cells = total_null_cells;
    profile.overall_null_pct = (profile.total_cells > 0) ? (100.0 * static_cast<double>(total_null_cells) / profile.total_cells) : 0.0;

    // FIX C-L18: Release the O(N²) pair_accs_ memory now that correlations
    // have been computed. Previously 64 MB stayed allocated until ~ArrowProfiler.
    pair_accs_.clear();
    pair_accs_.shrink_to_fit();

    finalized_ = true;
    cached_profile_ = profile;

    return profile;
}

} // namespace zedda
