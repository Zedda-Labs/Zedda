#pragma once

#include "zedda/column_accumulator.hpp"
#include "zedda/hyperloglog.hpp"
#include "zedda/profile_result.hpp"
#include <string>
#include <vector>
#include <cstdint>
#include <string_view>
#include <unordered_set>

// ── Arrow C Data Interface ──────────────────────────────────────────
#ifdef __cplusplus
extern "C" {
#endif
struct ArrowSchema {
  const char* format;
  const char* name;
  const char* metadata;
  int64_t flags;
  int64_t n_children;
  struct ArrowSchema** children;
  struct ArrowSchema* dictionary;
  void (*release)(struct ArrowSchema*);
  void* private_data;
};

struct ArrowArray {
  int64_t length;
  int64_t null_count;
  int64_t offset;
  int64_t n_buffers;
  int64_t n_children;
  const void** buffers;
  struct ArrowArray** children;
  struct ArrowArray* dictionary;
  void (*release)(struct ArrowArray*);
  void* private_data;
};
#ifdef __cplusplus
}
#endif
// ─────────────────────────────────────────────────────────────────

namespace zedda {

class ArrowProfiler {
public:
    ArrowProfiler(const std::string& file_name, int64_t total_rows, bool correlate = false);
    // FIX C-L5: Use = default destructor to allow implicit move operations.
    ~ArrowProfiler() = default;

    // Allow caller to explicitly override correlation computation.
    void set_skip_correlation(bool skip) {
        skip_correlation_ = skip;
        skip_correlation_overridden_ = true;
    }

    // Consume a PyArrow RecordBatch via Arrow C Data Interface
    // schema_ptr and array_ptr are memory addresses cast to uintptr_t
    void consume_batch(uintptr_t schema_ptr, uintptr_t array_ptr);

    // Finalize computation and build the profile
    DatasetProfile finalize();

private:
    std::string file_name_;
    int64_t total_rows_;
    bool correlate_ = false;
    int64_t rows_processed_ = 0;
    bool initialized_ = false;
    bool finalized_ = false;
    DatasetProfile cached_profile_;

    // Skip correlation above 50 numeric columns unless correlate=true (matches ProfileBuilder).
    static constexpr int64_t MAX_CORR_NUMERIC_COLS = 50;

    std::vector<ColumnAccumulator> accs_;
    std::vector<HyperLogLog> hlls_;
    std::vector<ColumnPairAccumulator> pair_accs_;
    std::vector<std::string> format_strings_;
    std::vector<std::string> unsupported_types_;
    bool skip_correlation_ = false;
    bool skip_correlation_overridden_ = false;
    // FIX C-L4: Track unsupported formats so we only warn once per format,
    // not once per column per batch (was 1000× log spam for long streams).
    std::unordered_set<std::string> warned_formats_;

    void initialize_columns(struct ArrowSchema* schema);
    bool is_null(const uint8_t* validity_bitmap, int64_t index);
};

} // namespace zedda
