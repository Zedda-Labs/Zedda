#pragma once

#include "zedda/column_accumulator.hpp"
#include "zedda/hyperloglog.hpp"
#include "zedda/profile_result.hpp"
#include <string>
#include <vector>
#include <cstdint>
#include <string_view>

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
    ArrowProfiler(const std::string& file_name, int64_t total_rows);
    ~ArrowProfiler();

    // Consume a PyArrow RecordBatch via Arrow C Data Interface
    // schema_ptr and array_ptr are memory addresses cast to uintptr_t
    void consume_batch(uintptr_t schema_ptr, uintptr_t array_ptr);

    // Finalize computation and build the profile
    DatasetProfile finalize();

private:
    std::string file_name_;
    int64_t total_rows_;
    int64_t rows_processed_ = 0;
    bool initialized_ = false;

    std::vector<ColumnAccumulator> accs_;
    std::vector<HyperLogLog> hlls_;
    std::vector<ColumnPairAccumulator> pair_accs_;
    std::vector<std::string> format_strings_;

    void initialize_columns(struct ArrowSchema* schema);
    bool is_null(const uint8_t* validity_bitmap, int64_t index);
};

} // namespace zedda
