#include "zedda/arrow_profiler.hpp"
#include <cstring>
#include <stdexcept>
#include <iostream>
#include <cmath>
#include <algorithm>

namespace zedda {

ArrowProfiler::ArrowProfiler(const std::string& file_name, int64_t total_rows)
    : file_name_(file_name), total_rows_(total_rows) {}
// FIX C-L5: Destructor declared as = default in header (no out-of-line definition needed).

bool ArrowProfiler::is_null(const uint8_t* validity_bitmap, int64_t index) {
    if (!validity_bitmap) return false;
    return (validity_bitmap[index / 8] & (1 << (index % 8))) == 0;
}

void ArrowProfiler::initialize_columns(struct ArrowSchema* schema) {
    int64_t num_cols = schema->n_children;
    accs_.resize(num_cols);
    hlls_.resize(num_cols);
    format_strings_.resize(num_cols);

    // SEC-C01: Skip correlation for wide datasets.
    // FIX C-M1: Pack into upper-triangle (N*(N-1)/2 instead of N²).
    skip_correlation_ = (num_cols > MAX_CORR_COLS);
    if (!skip_correlation_) {
        pair_accs_.resize(pair_count(num_cols));
        for (int64_t i = 0; i < num_cols; ++i) {
            for (int64_t j = i + 1; j < num_cols; ++j) {
                pair_accs_[pair_idx(i, j, num_cols)].col_i = i;
                pair_accs_[pair_idx(i, j, num_cols)].col_j = j;
            }
        }
    }
    
    for (int64_t i = 0; i < num_cols; ++i) {
        struct ArrowSchema* child = schema->children[i];
        accs_[i].name = child->name ? child->name : "";
        format_strings_[i] = child->format ? child->format : "";
        
        std::string_view fmt(format_strings_[i]);
        if (fmt == "c" || fmt == "C" || fmt == "s" || fmt == "S" || 
            fmt == "i" || fmt == "I" || fmt == "l" || fmt == "L") {
            accs_[i].type = ColumnType::INTEGER;
        } else if (fmt == "e" || fmt == "f" || fmt == "g") {
            accs_[i].type = ColumnType::FLOAT;
        } else if (fmt == "b") {
            accs_[i].type = ColumnType::BOOLEAN;
        } else if (fmt == "u" || fmt == "U" || fmt == "z" || fmt == "Z") {
            accs_[i].type = ColumnType::STRING;
        } else if (fmt.length() >= 2 && (fmt.substr(0, 2) == "td" || fmt.substr(0, 2) == "tt" || fmt.substr(0, 2) == "ts")) {
            accs_[i].type = ColumnType::DATETIME;
        } else {
            accs_[i].type = ColumnType::UNKNOWN;
        }
    }
    
    // SEC-C01: Only initialize pair accumulators within threshold.
    // FIX C-M1: Use packed upper-triangle index (pair_accs_ was resized
    // to pair_count(num_cols) above, not num_cols²).
    if (!skip_correlation_) {
        for (int64_t i = 0; i < num_cols; ++i) {
            for (int64_t j = i + 1; j < num_cols; ++j) {
                pair_accs_[pair_idx(i, j, num_cols)].col_i = i;
                pair_accs_[pair_idx(i, j, num_cols)].col_j = j;
            }
        }
    }
    initialized_ = true;
}

void ArrowProfiler::consume_batch(uintptr_t schema_ptr, uintptr_t array_ptr) {
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

    // ISS-001: Validate column count on EVERY batch, not just the first.
    // A mismatched batch would cause OOB access in accs_[], hlls_[], pair_accs_[].
    if (initialized_ && static_cast<size_t>(schema->n_children) != accs_.size()) {
        throw std::runtime_error(
            "ArrowProfiler::consume_batch: column count mismatch — expected " +
            std::to_string(accs_.size()) + ", got " +
            std::to_string(schema->n_children));
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
        // float16 (e), boolean (b), and datetime (t*). Previously these all
        // fell into the all-null branch — silent data loss for boolean and
        // datetime columns.
        if (type == ColumnType::INTEGER) {
            // FIX C-M7: Reorder null-check to short-circuit safely.
            const void* buf1 = (child->buffers && child->n_buffers > 1) ? child->buffers[1] : nullptr;
            if (fmt == "i") { // int32
                const int32_t* data = reinterpret_cast<const int32_t*>(buf1);
                for (int64_t i = 0; i < num_rows; ++i) {
                    if (is_null(validity_bitmap, i + child->offset) || data == nullptr) accs_[col].update_null();
                    else { double val = static_cast<double>(data[i + child->offset]); accs_[col].update(val); hlls_[col].add(val); }
                }
            } else if (fmt == "l") { // int64
                const int64_t* data = reinterpret_cast<const int64_t*>(buf1);
                for (int64_t i = 0; i < num_rows; ++i) {
                    if (is_null(validity_bitmap, i + child->offset) || data == nullptr) accs_[col].update_null();
                    else { double val = static_cast<double>(data[i + child->offset]); accs_[col].update(val); hlls_[col].add(val); }
                }
            } else if (fmt == "c") { // int8
                const int8_t* data = reinterpret_cast<const int8_t*>(buf1);
                for (int64_t i = 0; i < num_rows; ++i) {
                    if (is_null(validity_bitmap, i + child->offset) || data == nullptr) accs_[col].update_null();
                    else { double val = static_cast<double>(data[i + child->offset]); accs_[col].update(val); hlls_[col].add(val); }
                }
            } else if (fmt == "C") { // uint8
                const uint8_t* data = reinterpret_cast<const uint8_t*>(buf1);
                for (int64_t i = 0; i < num_rows; ++i) {
                    if (is_null(validity_bitmap, i + child->offset) || data == nullptr) accs_[col].update_null();
                    else { double val = static_cast<double>(data[i + child->offset]); accs_[col].update(val); hlls_[col].add(val); }
                }
            } else if (fmt == "s") { // int16
                const int16_t* data = reinterpret_cast<const int16_t*>(buf1);
                for (int64_t i = 0; i < num_rows; ++i) {
                    if (is_null(validity_bitmap, i + child->offset) || data == nullptr) accs_[col].update_null();
                    else { double val = static_cast<double>(data[i + child->offset]); accs_[col].update(val); hlls_[col].add(val); }
                }
            } else if (fmt == "S") { // uint16
                const uint16_t* data = reinterpret_cast<const uint16_t*>(buf1);
                for (int64_t i = 0; i < num_rows; ++i) {
                    if (is_null(validity_bitmap, i + child->offset) || data == nullptr) accs_[col].update_null();
                    else { double val = static_cast<double>(data[i + child->offset]); accs_[col].update(val); hlls_[col].add(val); }
                }
            } else if (fmt == "I") { // uint32
                const uint32_t* data = reinterpret_cast<const uint32_t*>(buf1);
                for (int64_t i = 0; i < num_rows; ++i) {
                    if (is_null(validity_bitmap, i + child->offset) || data == nullptr) accs_[col].update_null();
                    else { double val = static_cast<double>(data[i + child->offset]); accs_[col].update(val); hlls_[col].add(val); }
                }
            } else if (fmt == "L") { // uint64
                const uint64_t* data = reinterpret_cast<const uint64_t*>(buf1);
                for (int64_t i = 0; i < num_rows; ++i) {
                    if (is_null(validity_bitmap, i + child->offset) || data == nullptr) accs_[col].update_null();
                    else { double val = static_cast<double>(data[i + child->offset]); accs_[col].update(val); hlls_[col].add(val); }
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
            } else if (fmt == "e") { // float16 — convert to float via bit manipulation
                const uint16_t* data = reinterpret_cast<const uint16_t*>(buf1);
                for (int64_t i = 0; i < num_rows; ++i) {
                    if (is_null(validity_bitmap, i + child->offset) || data == nullptr) accs_[col].update_null();
                    else {
                        // IEEE 754 half-precision → float
                        uint16_t h = data[i + child->offset];
                        uint32_t sign = (h >> 15) & 0x1;
                        uint32_t exp  = (h >> 10) & 0x1f;
                        uint32_t frac =  h        & 0x3ff;
                        float val;
                        if (exp == 0) {
                            if (frac == 0) {
                                val = sign ? -0.0f : 0.0f;
                            } else {
                                // Subnormal
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
                        accs_[col].update(static_cast<double>(val));
                        hlls_[col].add(static_cast<double>(val));
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
            // FIX C-H5: Treat datetime as int64 (was silently all-null).
            const void* buf1 = (child->buffers && child->n_buffers > 1) ? child->buffers[1] : nullptr;
            const int64_t* data = reinterpret_cast<const int64_t*>(buf1);
            for (int64_t i = 0; i < num_rows; ++i) {
                if (is_null(validity_bitmap, i + child->offset) || data == nullptr) accs_[col].update_null();
                else { double val = static_cast<double>(data[i + child->offset]); accs_[col].update(val); hlls_[col].add(val); }
            }
        } else if (type == ColumnType::STRING && fmt == "u") {
            const int32_t* offsets = child->n_buffers > 1 && child->buffers[1] ? reinterpret_cast<const int32_t*>(child->buffers[1]) : nullptr;
            const char* str_data = child->n_buffers > 2 && child->buffers[2] ? reinterpret_cast<const char*>(child->buffers[2]) : nullptr;
            
            for (int64_t i = 0; i < num_rows; ++i) {
                int64_t adj_i = i + child->offset;
                if (is_null(validity_bitmap, adj_i) || offsets == nullptr) {
                    accs_[col].update_null();
                } else {
                    int32_t start = offsets[adj_i];
                    int32_t end = offsets[adj_i + 1];
                    int32_t len = end - start;
                    if (str_data != nullptr && len > 0) {
                        std::string_view sv(str_data + start, len);
                        accs_[col].update_string_sv(sv);
                        hlls_[col].add(sv);
                    } else {
                        accs_[col].update_string_sv("");
                        hlls_[col].add(std::string_view(""));
                    }
                }
            }
        } else if (type == ColumnType::STRING && fmt == "U") { // large string
            const int64_t* offsets = child->n_buffers > 1 && child->buffers[1] ? reinterpret_cast<const int64_t*>(child->buffers[1]) : nullptr;
            const char* str_data = child->n_buffers > 2 && child->buffers[2] ? reinterpret_cast<const char*>(child->buffers[2]) : nullptr;
            
            for (int64_t i = 0; i < num_rows; ++i) {
                int64_t adj_i = i + child->offset;
                if (is_null(validity_bitmap, adj_i) || offsets == nullptr) {
                    accs_[col].update_null();
                } else {
                    int64_t start = offsets[adj_i];
                    int64_t end = offsets[adj_i + 1];
                    int64_t len = end - start;
                    if (str_data != nullptr && len > 0) {
                        std::string_view sv(str_data + start, len);
                        accs_[col].update_string_sv(sv);
                        hlls_[col].add(sv);
                    } else {
                        accs_[col].update_string_sv("");
                        hlls_[col].add(std::string_view(""));
                    }
                }
            }
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
    enum class NumFormat { I32, I64, F32, F64, NONE };
    auto get_num_format = [](std::string_view fmt) {
        if (fmt == "i") return NumFormat::I32;
        if (fmt == "l") return NumFormat::I64;
        if (fmt == "f") return NumFormat::F32;
        if (fmt == "g") return NumFormat::F64;
        return NumFormat::NONE;
    };

    // ISS-001: Use accs_.size() (the established column count) for all indexing,
    // never array->n_children directly — the batch-level check above guards
    // against these being different.
    size_t ncols = accs_.size();
    for (size_t i = 0; i < ncols; ++i) {
        if (accs_[i].type != ColumnType::INTEGER && accs_[i].type != ColumnType::FLOAT) continue;
        struct ArrowArray* child_i = array->children[i];
        // FIX C-H6: Skip columns where the producer marked null_count == num_rows
        // AND omitted the validity bitmap. The is_null() function returns false
        // for a null bitmap, which would feed garbage data into Pearson.
        if (child_i->null_count == num_rows) continue;
        std::string_view fmt_i = format_strings_[i];
        NumFormat nf_i = get_num_format(fmt_i);
        if (nf_i == NumFormat::NONE || !child_i->buffers || child_i->n_buffers < 2 || !child_i->buffers[1]) continue;

        const uint8_t* val_i = (child_i->n_buffers > 0 && child_i->buffers[0]) ? reinterpret_cast<const uint8_t*>(child_i->buffers[0]) : nullptr;
        const void* raw_i = child_i->buffers[1];

        for (size_t j = i + 1; j < ncols; ++j) {
            if (accs_[j].type != ColumnType::INTEGER && accs_[j].type != ColumnType::FLOAT) continue;
            struct ArrowArray* child_j = array->children[j];
            // FIX C-H6: same all-null guard for column j.
            if (child_j->null_count == num_rows) continue;
            std::string_view fmt_j = format_strings_[j];
            NumFormat nf_j = get_num_format(fmt_j);
            if (nf_j == NumFormat::NONE || !child_j->buffers || child_j->n_buffers < 2 || !child_j->buffers[1]) continue;

            const uint8_t* val_j = (child_j->n_buffers > 0 && child_j->buffers[0]) ? reinterpret_cast<const uint8_t*>(child_j->buffers[0]) : nullptr;
            const void* raw_j = child_j->buffers[1];

            // FIX C-M1: Use packed upper-triangle index.
            auto& pa = pair_accs_[pair_idx(i, j, ncols)];

            for (int64_t row = 0; row < num_rows; ++row) {
                if (is_null(val_i, row + child_i->offset) || is_null(val_j, row + child_j->offset)) continue;

                double x = 0.0, y = 0.0;
                if (nf_i == NumFormat::I32) x = static_cast<double>(reinterpret_cast<const int32_t*>(raw_i)[row + child_i->offset]);
                else if (nf_i == NumFormat::I64) x = static_cast<double>(reinterpret_cast<const int64_t*>(raw_i)[row + child_i->offset]);
                else if (nf_i == NumFormat::F32) x = static_cast<double>(reinterpret_cast<const float*>(raw_i)[row + child_i->offset]);
                else if (nf_i == NumFormat::F64) x = reinterpret_cast<const double*>(raw_i)[row + child_i->offset];

                if (nf_j == NumFormat::I32) y = static_cast<double>(reinterpret_cast<const int32_t*>(raw_j)[row + child_j->offset]);
                else if (nf_j == NumFormat::I64) y = static_cast<double>(reinterpret_cast<const int64_t*>(raw_j)[row + child_j->offset]);
                else if (nf_j == NumFormat::F32) y = static_cast<double>(reinterpret_cast<const float*>(raw_j)[row + child_j->offset]);
                else if (nf_j == NumFormat::F64) y = reinterpret_cast<const double*>(raw_j)[row + child_j->offset];

                pa.update(x, y);
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
    DatasetProfile profile;
    profile.file_name = file_name_;
    profile.file_path = file_name_;
    profile.num_rows = total_rows_;
    profile.num_cols = accs_.size();
    profile.scan_time_ms = 0;

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
        cp.unique_pct = (cp.non_null_count > 0) ? (100.0 * cp.unique_approx / cp.non_null_count) : 0.0;
        
        if (accs_[i].type == ColumnType::INTEGER || accs_[i].type == ColumnType::FLOAT || accs_[i].type == ColumnType::BOOLEAN) {
            cp.mean = accs_[i].mean;
            cp.stddev = accs_[i].stddev;
            cp.variance = accs_[i].variance;
            cp.skewness = accs_[i].skewness;
            cp.kurtosis = accs_[i].kurtosis;
            if (cp.non_null_count > 0) {
                cp.val_min = accs_[i].val_min;
                cp.val_max = accs_[i].val_max;
                cp.range = accs_[i].range();
            }
        }
        
        if (accs_[i].type == ColumnType::STRING || accs_[i].type == ColumnType::DATETIME) {
            if (cp.non_null_count > 0) {
                cp.min_str_len = accs_[i].min_str_len;
                cp.max_str_len = accs_[i].max_str_len;
                cp.mean_str_len = accs_[i].mean_str_len;
            }
        }
        
        cp.has_high_nulls = cp.null_pct > 20.0;
        cp.is_constant = cp.unique_approx <= 1;
        cp.is_high_cardinality = cp.unique_pct > 90.0;
        
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
                if (!std::isnan(r) && std::abs(r) >= 0.7) {
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

    return profile;
}

} // namespace zedda
