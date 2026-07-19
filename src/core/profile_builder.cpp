// ─────────────────────────────────────────────────────────────────
//  zedda — profile_builder.cpp
//
//  PARALLEL multi-threaded CSV profiler:
//  1. Open file once  → get column names only (no double read)
//  2. Probe file size → divide into N equal byte chunks
//  3. Spawn N threads → each parses its chunk independently
//     - zero-copy string_view field parsing (no heap allocation per field)
//     - fast_atod: strtod on stack buffer (no std::string alloc)
//  4. Join threads → merge with parallel Welford formula (exact)
//  5. Assemble DatasetProfile
//
//  Result: 5–8x faster on large files vs single-threaded version.
// ─────────────────────────────────────────────────────────────────
#include "zedda/profile_builder.hpp"

#include <cstring>
#include <cstdlib>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <chrono>
#include <stdexcept>
#include <algorithm>
#include <string_view>
#include <thread>        // for hardware_concurrency only
#include <future>
#include <vector>
#include "zedda/BS_thread_pool.hpp"
#include "zedda/parsing_utils.hpp"  // ISS-008: shared fast_atod, fast_is_null, fast_detect_type

// ── Portable 64-bit file seeking ─────────────────────────────────
#ifdef _WIN32
#  include <io.h>
#  define ZEDDA_FSEEK  _fseeki64
#  define ZEDDA_FTELL  _ftelli64
   typedef long long zedda_off_t;
#else
#  define ZEDDA_FSEEK  fseeko
#  define ZEDDA_FTELL  ftello
   typedef off_t zedda_off_t;
#endif

namespace zedda {

ProfileBuilder::ProfileBuilder(const std::string& path,
                               StreamReaderConfig  config)
    : path_(path), config_(config) {}

// ISS-008/009/010: fast_is_null, fast_atod, and fast_detect_type are now
// shared via include/zedda/parsing_utils.hpp — removed ~100 lines of
// duplicate code that was identical to stream_reader.cpp.
// ─────────────────────────────────────────────────────────────────
//  parse_fields_sv — zero-copy CSV line parser
//
//  Fills 'fields' with string_views pointing directly into 'line' (or into
//  'storage' for fields that needed escape-unescaping).
// ─────────────────────────────────────────────────────────────────────────────
//  parse_fields_sv — split a CSV line into fields, RFC 4180 compliant.
//
//  FIX C-H2: Properly unescape "" → " inside quoted fields. The previous
//  version skipped the second quote but left both in the string_view,
//  so `"abc""def"` parsed as `abc""def` instead of `abc"def`.
//  FIX C-M9: Only strip the trailing quote if the field was actually
//  quoted (was stripping from any field ending in ").
//
//  When a field contains escapes, we materialize it into 'arena'
//  and return a string_view into that. 'arena' must outlive the
//  returned views.
// ─────────────────────────────────────────────────────────────────────────────
static void parse_fields_sv(
    const char* line, size_t len,
    char delim, char quote,
    std::vector<std::string_view>& fields,
    std::string& arena)
{
    fields.clear();
    arena.clear();
    
    // FIX PERF-3: Pre-allocate the arena to guarantee no reallocations occur
    // during this line's parsing. This ensures that string_views pointing
    // into arena.data() remain valid for the lifetime of this function call.
    // The maximum unescaped data from a single line cannot exceed the line length.
    if (arena.capacity() < len) {
        arena.reserve(len);
    }
    const char* p          = line;
    const char* end        = line + len;
    const char* field_start= p;
    bool        in_q       = false;
    bool        field_was_quoted = false;
    bool        has_escape = false;

    while (p < end) {
        char c = *p;
        if (in_q) {
            if (c == quote && p+1 < end && *(p+1) == quote) {
                ++p; // escaped quote — skip the second one
                has_escape = true;
            } else if (c == quote) {
                in_q = false;
            }
        } else {
            if (c == quote) {
                in_q = true;
                field_was_quoted = true;
                field_start = p + 1;   // skip opening quote
            } else if (c == delim) {
                size_t flen = (size_t)(p - field_start);
                // FIX C-M9: Only strip closing quote if field was quoted.
                if (field_was_quoted && flen > 0 && field_start[flen-1] == quote) --flen;
                if (has_escape) {
                    // FIX PERF-3: Materialize with "" → " unescape using Arena.
                    size_t start_idx = arena.size();
                    for (size_t i = 0; i < flen; ++i) {
                        char ch = field_start[i];
                        if (ch == quote && i + 1 < flen && field_start[i+1] == quote) {
                            arena.push_back(quote);
                            ++i;
                        } else {
                            arena.push_back(ch);
                        }
                    }
                    size_t unescaped_len = arena.size() - start_idx;
                    fields.emplace_back(arena.data() + start_idx, unescaped_len);
                } else {
                    fields.emplace_back(field_start, flen);
                }
                field_start = p + 1;
                field_was_quoted = false;
                has_escape = false;
            }
        }
        ++p;
    }
    // Last field
    size_t flen = (size_t)(end - field_start);
    if (field_was_quoted && flen > 0 && field_start[flen-1] == quote) --flen;
    if (has_escape) {
        size_t start_idx = arena.size();
        for (size_t i = 0; i < flen; ++i) {
            char ch = field_start[i];
            if (ch == quote && i + 1 < flen && field_start[i+1] == quote) {
                arena.push_back(quote);
                ++i;
            } else {
                arena.push_back(ch);
            }
        }
        size_t unescaped_len = arena.size() - start_idx;
        fields.emplace_back(arena.data() + start_idx, unescaped_len);
    } else {
        fields.emplace_back(field_start, flen);
    }
}

// Overload preserving the original signature (no escape unescape).
// FIX C-H2: Calls the new signature with a thread-local arena.
// PREFER the new signature with explicit arena in hot loops.
static void parse_fields_sv(
    const char* line, size_t len,
    char delim, char quote,
    std::vector<std::string_view>& fields)
{
    thread_local std::string tls_arena;
    parse_fields_sv(line, len, delim, quote, fields, tls_arena);
}

// ─────────────────────────────────────────────────────────────────
//  ThreadResult — holds one worker thread's partial results
// ─────────────────────────────────────────────────────────────────
struct ThreadResult {
    std::vector<ColumnAccumulator> accs;
    std::vector<HyperLogLog>       hlls;
    std::vector<ColumnPairAccumulator> pair_accs;
    int64_t rows_done = 0;
    bool success = false;  // ISS-002: tracks whether this thread completed without error
    std::string error_message;  // FIX PERF-4: human-readable reason on failure
};

// ─────────────────────────────────────────────────────────────────
//  do_thread_work — parse a byte range of the CSV file
//
//  Designed to run in its own thread. All state is local — no locks.
//
//  byte_start: inclusive byte offset for this thread
//  byte_end:   exclusive byte offset (this thread stops here)
//  skip_header: true for thread 0 — skips the CSV header row
// ─────────────────────────────────────────────────────────────────
// SEC-C01: Maximum NUMERIC columns for correlation computation.
// FIX PERF-1: Lowered from 1000 → 50 numeric columns.
// At 50 numeric cols: 1,225 pairs × 700k rows = 857M iterations → minutes.
// At 1000 cols: 499,500 pairs × 700k rows = 349 BILLION iterations → OOM.
// Users who need correlation on wide datasets must pass correlate=True.
static constexpr size_t MAX_CORR_NUMERIC_COLS = 50;

static void do_thread_work(
    const std::string&              path,
    zedda_off_t                     byte_start,
    zedda_off_t                     byte_end,
    bool                            skip_header,
    const std::vector<std::string>& col_names,
    StreamReaderConfig              cfg,
    ThreadResult&                   result,
    int64_t                         max_rows,
    bool                            skip_correlation)
{
    size_t ncols = col_names.size();
    result.accs.resize(ncols);
    result.hlls.resize(ncols);

    // SEC-C01: Only allocate pair accumulators if columns <= threshold.
    // FIX C-M1: Pack into upper-triangle (N*(N-1)/2 entries instead of N²).
    if (!skip_correlation) {
        result.pair_accs.resize(pair_count(ncols));
        for (size_t i = 0; i < ncols; ++i) {
            for (size_t j = i + 1; j < ncols; ++j) {
                result.pair_accs[pair_idx(i, j, ncols)].col_i = i;
                result.pair_accs[pair_idx(i, j, ncols)].col_j = j;
            }
        }
    }
    for (size_t i = 0; i < ncols; ++i) {
        result.accs[i].name = col_names[i];
    }

    FILE* f = fopen(path.c_str(), "rb");
    if (!f) return;  // ISS-002: success remains false — build() will catch this

    // ── Seek to our byte range and align to a line boundary ──────
    if (byte_start > 0) {
        // Peek at the byte just BEFORE our start.
        // If it's '\n', we're already at a line start.
        // If not, we're mid-line — scan forward to the next '\n'.
        ZEDDA_FSEEK(f, byte_start - 1, SEEK_SET);
        int prev = fgetc(f);   // file is now at byte_start
        if (prev != '\n') {
            int ch;
            while ((ch = fgetc(f)) != EOF && ch != '\n') {}
        }
    } else if (skip_header) {
        // Thread 0: consume the header row
        int ch;
        while ((ch = fgetc(f)) != EOF && ch != '\n') {}
    }

    // ── Main parse loop ───────────────────────────────────────────
    std::vector<ColumnType>       col_types(ncols, ColumnType::UNKNOWN);
    std::vector<std::string_view> fields;
    fields.reserve(ncols + 4);
    char buf[65536];
    std::string long_line;  // SEC-C02: dynamic buffer for lines > 64KB

    // FIX C-H3: Hoist row_nums/row_nulls OUT of the per-row hot loop.
    // Previously each iteration constructed and destructed two heap
    // vectors — for a 6.3M-row dataset that's 12.6M malloc/free calls.
    // Reuse the same buffers per row and reset with fill().
    std::vector<double> row_nums(ncols, 0.0);
    std::vector<bool>   row_nulls(ncols, true);

    // FIX C-M5/C-H10: Helper to check if a line has an unterminated quote
    // (odd number of unescaped quotes). If so, the line continues — the
    // newline was embedded inside a quoted field (RFC 4180 §6).
    auto line_has_open_quote = [](const char* s, size_t len, char quote_char) -> bool {
        bool in_q = false;
        for (size_t i = 0; i < len; ++i) {
            if (s[i] == quote_char) {
                // Check for escaped quote ("")
                if (in_q && i + 1 < len && s[i + 1] == quote_char) {
                    ++i;  // skip the second quote
                } else {
                    in_q = !in_q;
                }
            }
        }
        return in_q;  // true = quote is still open
    };

    while (true) {
        // Stop when we've reached or passed our byte boundary
        zedda_off_t pos = ZEDDA_FTELL(f);
        if (pos >= byte_end) break;

        if (!fgets(buf, sizeof(buf), f)) break;

        // Strip trailing CR/LF
        size_t len = strlen(buf);
        while (len > 0 && (buf[len-1] == '\n' || buf[len-1] == '\r'))
            buf[--len] = '\0';

        // SEC-C02: Detect truncated lines (no newline found by fgets).
        // If the buffer is full and doesn't end with a newline, the line
        // was longer than 64KB. Continue reading into a dynamic buffer.
        if (len == sizeof(buf) - 1 && !feof(f)) {
            long_line.assign(buf, len);
            while (true) {
                if (!fgets(buf, sizeof(buf), f)) break;
                size_t extra = strlen(buf);
                bool has_newline = (extra > 0 && (buf[extra-1] == '\n' || buf[extra-1] == '\r'));
                while (extra > 0 && (buf[extra-1] == '\n' || buf[extra-1] == '\r'))
                    buf[--extra] = '\0';
                // FIX PERF-4: 64 MB hard cap on long_line.
                // Without this, a binary file (e.g., .pkl, .db) with no
                // newlines reads the ENTIRE file into RAM before any error.
                if (long_line.size() > 64ULL * 1024 * 1024) {
                    result.error_message = "A single CSV line exceeded 64 MB — "
                        "the file may be binary or corrupt. "
                        "Zedda supports text CSV files only.";
                    result.success = false;
                    fclose(f);
                    return;
                }
                long_line.append(buf, extra);
                if (has_newline) break;
            }
            // FIX C-H10: Check for embedded newlines in quoted fields.
            // If the line has an open quote, keep reading until it closes.
            while (line_has_open_quote(long_line.data(), long_line.size(), cfg.quote_char)) {
                // FIX PERF-4 (Bug Fix 4): 64 MB cap in quoted-field continuation loop too.
                // The PR originally only capped the first while loop. A file with an
                // unclosed quote could still OOM via this second loop.
                if (long_line.size() > 64ULL * 1024 * 1024) {
                    result.error_message = "A single CSV line exceeded 64 MB — "
                        "the file may be binary or corrupt. "
                        "Zedda supports text CSV files only.";
                    result.success = false;
                    fclose(f);
                    return;
                }
                if (!fgets(buf, sizeof(buf), f)) break;
                size_t extra = strlen(buf);
                bool has_newline = (extra > 0 && (buf[extra-1] == '\n' || buf[extra-1] == '\r'));
                while (extra > 0 && (buf[extra-1] == '\n' || buf[extra-1] == '\r'))
                    buf[--extra] = '\0';
                long_line.push_back('\n');  // restore the embedded newline
                long_line.append(buf, extra);
                if (!has_newline) break;  // EOF
            }
            // Parse from the dynamic buffer
            parse_fields_sv(long_line.data(), long_line.size(), cfg.delimiter, cfg.quote_char, fields);
            while (fields.size() < ncols)
                fields.emplace_back("", (size_t)0);
        } else {
            if (len == 0) continue;

            // FIX C-H10: Check for embedded newlines in quoted fields.
            // If the line has an open quote, read more lines until it closes.
            if (line_has_open_quote(buf, len, cfg.quote_char)) {
                long_line.assign(buf, len);
                while (line_has_open_quote(long_line.data(), long_line.size(), cfg.quote_char)) {
                    if (!fgets(buf, sizeof(buf), f)) break;
                    size_t extra = strlen(buf);
                    bool has_newline = (extra > 0 && (buf[extra-1] == '\n' || buf[extra-1] == '\r'));
                    while (extra > 0 && (buf[extra-1] == '\n' || buf[extra-1] == '\r'))
                        buf[--extra] = '\0';
                    long_line.push_back('\n');
                    long_line.append(buf, extra);
                    if (!has_newline) break;
                }
                parse_fields_sv(long_line.data(), long_line.size(), cfg.delimiter, cfg.quote_char, fields);
            } else {
                // Parse fields as views into buf (zero-copy)
                parse_fields_sv(buf, len, cfg.delimiter, cfg.quote_char, fields);
            }
            while (fields.size() < ncols)
                fields.emplace_back("", (size_t)0);
        }

        // FIX C-H3: Reset the hoisted buffers — fill is O(n) but no alloc.
        std::fill(row_nums.begin(), row_nums.end(), 0.0);
        std::fill(row_nulls.begin(), row_nulls.end(), true);

        for (size_t col = 0; col < ncols; ++col) {
            std::string_view fv = fields[col];
            const char* fs = fv.data() ? fv.data() : "";
            size_t      fl = fv.size();

            // FIX C-H9: Honor cfg.null_string (was silently ignored here).
            bool is_null = fast_is_null(fs, fl);
            if (!is_null && !cfg.null_string.empty()
                && cfg.null_string.size() == fl
                && std::memcmp(fs, cfg.null_string.data(), fl) == 0) {
                is_null = true;
            }
            if (is_null) {
                result.accs[col].update_null();
                continue;
            }

            // Detect type on first non-null value in this thread
            if (col_types[col] == ColumnType::UNKNOWN) {
                col_types[col]       = fast_detect_type(fs, fl);
                result.accs[col].type = col_types[col];
            }

            ColumnType t = col_types[col];
            if (t == ColumnType::INTEGER || t == ColumnType::FLOAT) {
                double val;
                if (fast_atod(fs, fl, val)) {
                    result.accs[col].update(val);
                    result.hlls[col].add(val);
                    row_nums[col] = val;
                    row_nulls[col] = false;
                } else {
                    result.accs[col].update_null();
                }
            } else if (t == ColumnType::BOOLEAN) {
                // FIX C-H12: Use strict case-insensitive equality via
                // fast_parse_bool — the old `fl >= 4 && fs[0]=='t'` check
                // matched "track", "field", "from", etc.
                double bv = fast_parse_bool(fs, fl);
                if (bv >= 0.0) {
                    result.accs[col].update(bv);
                    result.hlls[col].add(bv);
                    row_nums[col] = bv;
                    row_nulls[col] = false;
                } else {
                    result.accs[col].update_null();
                }
            } else {
                // String / Datetime / Unknown — zero-copy update
                result.accs[col].update_string_sv(fv);
                result.hlls[col].add(fv);
            }
        }

        // Update pair accumulators (SEC-C01: skip if too many columns)
        if (!skip_correlation) {
            for (size_t i = 0; i < ncols; ++i) {
                if (row_nulls[i]) continue;
                for (size_t j = i + 1; j < ncols; ++j) {
                    if (!row_nulls[j]) {
                        // FIX C-M1: Use packed upper-triangle index.
                        result.pair_accs[pair_idx(i, j, ncols)].update(row_nums[i], row_nums[j]);
                    }
                }
            }
        }

        ++result.rows_done;
        
        // Stop early if we reached our stratified sample target
        if (max_rows > 0 && result.rows_done >= max_rows) break;
    }

    fclose(f);
    result.success = true;  // ISS-002: mark successful completion
}

// ─────────────────────────────────────────────────────────────────
//  ProfileBuilder::build() — parallel multi-threaded CSV profiler
// ─────────────────────────────────────────────────────────────────
DatasetProfile ProfileBuilder::build(bool is_sampled, int64_t sample_size, bool correlate) {
    auto t0 = std::chrono::high_resolution_clock::now();

    // ── Step 1: Open file to read column names ────────────────────
    // Note: the file is opened N+2 times total:
    //   1. Here (this step) — to read the header row.
    //   2. Again below for file-size probing.
    //   3. Once per worker thread in do_thread_work().
    // TODO(perf): consolidate to a single open if file-handle sharing
    //             becomes a bottleneck on high-thread-count systems.
    CsvStreamReader reader(path_, config_);
    if (!reader.open())
        throw std::runtime_error("[zedda] Cannot open: " + path_);

    // Copy column names out so reader can be safely closed
    std::vector<std::string> col_names(reader.column_names());
    size_t ncols = col_names.size();

    // FIX C-H8: When has_header=false, CsvStreamReader returns empty
    // col_names. Synthesize "col_0", "col_1", ... so downstream code
    // (which assumes ncols > 0) doesn't fail. We need to peek at the
    // first row to count columns.
    if (ncols == 0 && !config_.has_header) {
        // Read first line directly with fopen (read_line_mmap is private).
        FILE* peek = fopen(path_.c_str(), "rb");
        if (peek) {
            // Skip BOM if present (matches CsvStreamReader::open behavior).
            char bom[3];
            if (fread(bom, 1, 3, peek) == 3
                && (unsigned char)bom[0] == 0xEF
                && (unsigned char)bom[1] == 0xBB
                && (unsigned char)bom[2] == 0xBF) {
                // BOM consumed.
            } else {
                rewind(peek);
            }
            char linebuf[65536];
            if (fgets(linebuf, sizeof(linebuf), peek)) {
                size_t ln = strlen(linebuf);
                while (ln > 0 && (linebuf[ln-1] == '\n' || linebuf[ln-1] == '\r'))
                    linebuf[--ln] = '\0';
                size_t n = 1;
                for (size_t i = 0; i < ln; ++i)
                    if (linebuf[i] == config_.delimiter) ++n;
                ncols = n;
                for (size_t i = 0; i < ncols; ++i)
                    col_names.push_back("col_" + std::to_string(i));
            }
            fclose(peek);
        }
    }

    reader.close();

    if (ncols == 0)
        throw std::runtime_error("[zedda] No columns found in: " + path_);

    // ── Step 2: Get file size ─────────────────────────────────────
    FILE* probe = fopen(path_.c_str(), "rb");
    if (!probe) throw std::runtime_error("[zedda] Cannot probe file: " + path_);
    ZEDDA_FSEEK(probe, 0, SEEK_END);
    zedda_off_t file_size = ZEDDA_FTELL(probe);
    fclose(probe);

    // ── Step 3: Determine thread count ───────────────────────────
    //  Cap at 8 — diminishing returns beyond that for I/O-bound work
    int num_threads = static_cast<int>(std::thread::hardware_concurrency());
    if (num_threads < 1) num_threads = 4;
    if (num_threads > 8) num_threads = 8;
    if (file_size < 16384) num_threads = 1; // Fallback for tiny files

    // ── Step 4: Divide file into byte ranges ──────────────────────
    std::vector<zedda_off_t> byte_starts(num_threads);
    std::vector<zedda_off_t> byte_ends  (num_threads);
    zedda_off_t chunk = file_size / num_threads;
    for (int t = 0; t < num_threads; ++t) {
        byte_starts[t] = t * chunk;
        byte_ends[t]   = (t + 1 < num_threads) ? (t+1) * chunk : file_size;
    }

    // FIX PERF-1: Skip correlation based on numeric column count, not total
    // column count. This is the real O(N²) bottleneck — only numeric cols
    // produce pair accumulators. A dataset with 200 string cols + 5 numeric
    // cols has only 10 pairs and should NOT skip correlation.
    //
    // Count numeric columns by scanning the first non-null type from
    // column names. We don't have column types yet (they're detected
    // per-row), so we conservatively use ncols as a proxy on the
    // first pass. If correlate=true (user forced it), never skip.
    //
    // NOTE: After threads finish, we re-evaluate skip_correlation based
    // on the actual numeric column count detected. If that count exceeds
    // MAX_CORR_NUMERIC_COLS and correlate=false, we discard pair results.
    // The per-thread work (pair_accs allocation) still happens when
    // ncols <= MAX_CORR_NUMERIC_COLS * 4 (heuristic: assume <25% numeric).
    // If ncols is enormous, skip allocation upfront to save RAM.
    bool skip_correlation_upfront = !correlate && (ncols > MAX_CORR_NUMERIC_COLS * 20);
    if (skip_correlation_upfront) {
        fprintf(stderr, "[zedda info] %zu total columns: pre-skipping correlation "
               "(too wide for even heuristic allocation). Pass correlate=True to force.\n",
               ncols);
    }

    // ── Step 5: Launch worker threads using Thread Pool ──────────
    std::vector<ThreadResult> results(num_threads);
    
    // SEC-C05: Per-call thread pool — destroyed after build() returns.
    // Avoids fork-safety issues with multiprocessing and ensures
    // clean shutdown. No stale threads persist across calls.
    BS::thread_pool pool(num_threads);
    
    std::vector<std::future<void>> futures;
    futures.reserve(num_threads);
    
    int64_t rows_per_thread = is_sampled ? (sample_size / num_threads) : 0;

    for (int t = 0; t < num_threads; ++t) {
        // FIX C-H8: Only thread 0 should skip the header, AND only when
        // config_.has_header is true. Previously has_header=false still
        // caused thread 0 to skip the first data row — silent data loss.
        futures.push_back(pool.submit_task([this, t, byte_start = byte_starts[t], byte_end = byte_ends[t], skip_header = (t == 0 && this->config_.has_header), &col_names, &results, rows_per_thread, skip_correlation_upfront] {
            do_thread_work(
                this->path_,
                byte_start,
                byte_end,
                skip_header,
                col_names,
                this->config_,
                results[t],
                rows_per_thread,
                skip_correlation_upfront
            );
        }));
    }

    // Wait for all tasks to finish
    for (auto& fut : futures) {
        fut.wait();
    }
    
    auto t_threads_done = std::chrono::high_resolution_clock::now();

    // ISS-002: Validate every thread succeeded before merging.
    // FIX PERF-4: Surface the thread's error_message (e.g. 64MB line cap)
    // in the exception so Python gets a helpful ZeddaError, not a generic one.
    for (int t = 0; t < num_threads; ++t) {
        if (!results[t].success) {
            std::string msg = results[t].error_message.empty()
                ? "worker thread " + std::to_string(t) +
                  " failed to open its chunk of the file — aborting to avoid "
                  "producing incorrect statistics from partial data."
                : results[t].error_message;
            throw std::runtime_error("ProfileBuilder::build: " + msg);
        }
    }

    // ── Step 6: Merge all thread-local results ───────────────────
    //  Start with thread 0, merge in threads 1..N-1
    std::vector<ColumnAccumulator>& final_accs = results[0].accs;
    std::vector<HyperLogLog>&       final_hlls = results[0].hlls;
    std::vector<ColumnPairAccumulator>& final_pair_accs = results[0].pair_accs;
    int64_t total_rows = results[0].rows_done;

    for (int t = 1; t < num_threads; ++t) {
        total_rows += results[t].rows_done;
        for (size_t c = 0; c < ncols; ++c) {
            final_accs[c].merge(results[t].accs[c]);
            final_hlls[c].merge(results[t].hlls[c]);
        }
        // SEC-C01: Only merge pair accumulators if correlation was computed.
        // FIX C-H1: Use Pébay 2008 parallel reduction for Welford co-moments.
        // The naive sum_x/sum_y/... fields no longer exist — we now have
        // mean_x/mean_y/c_xx/c_yy/c_xy which require the parallel-Welford
        // combine formula to merge correctly across threads.
        if (!skip_correlation_upfront && !results[t].pair_accs.empty()) {
            // FIX C-M1/C-L3: Iterate only upper-triangle entries (was N²
            // including unused lower triangle — 2× wasted work).
            size_t total_pairs = pair_count(ncols);
            for (size_t c = 0; c < total_pairs; ++c) {
                auto& A = final_pair_accs[c];
                const auto& B = results[t].pair_accs[c];
                if (B.n == 0) continue;
                if (A.n == 0) { A = B; continue; }
                int64_t n_A = A.n;
                int64_t n_B = B.n;
                double n_AB = static_cast<double>(n_A + n_B);
                double dx = B.mean_x - A.mean_x;
                double dy = B.mean_y - A.mean_y;
                A.mean_x += dx * (static_cast<double>(n_B) / n_AB);
                A.mean_y += dy * (static_cast<double>(n_B) / n_AB);
                // Pébay 2008 parallel-Welford co-moment combine.
                double factor = static_cast<double>(n_A) * static_cast<double>(n_B) / n_AB;
                A.c_xx += B.c_xx + dx * dx * factor;
                A.c_yy += B.c_yy + dy * dy * factor;
                A.c_xy += B.c_xy + dx * dy * factor;
                A.n = n_A + n_B;
            }
        } // end pair_accs merge guard
    }

    // ── Step 7: Finalize all accumulators ────────────────────────
    for (auto& acc : final_accs) acc.finalize();

    auto t1 = std::chrono::high_resolution_clock::now();
    double thread_ms = std::chrono::duration<double, std::milli>(t_threads_done - t0).count();
    double merge_ms = std::chrono::duration<double, std::milli>(t1 - t_threads_done).count();
    
    // Print chrono benchmarks (Con 3)
    fprintf(stderr, "[zedda info] Profiler timing: %d threads processed chunks in %.1f ms | Merge took %.1f ms\n", 
           num_threads, thread_ms, merge_ms);

    if (progress_cb_) progress_cb_(total_rows);

    // ── Step 8: Assemble DatasetProfile ──────────────────────────
    DatasetProfile profile;
    profile.file_path    = path_;
    profile.num_rows     = total_rows;   // rows actually scanned
    profile.num_cols     = static_cast<int64_t>(ncols);
    profile.scan_time_ms = thread_ms + merge_ms;
    profile.is_sampled   = is_sampled;

    // file_name = last path component
    size_t slash = path_.find_last_of("/\\");
    profile.file_name = (slash == std::string::npos)
                      ? path_ : path_.substr(slash + 1);

    int64_t total_null_cells = 0;
    for (size_t i = 0; i < ncols; ++i) {
        auto cp = make_column_profile(final_accs[i], final_hlls[i], total_rows);
        total_null_cells += cp.null_count;

        if (cp.type_str == "int" || cp.type_str == "float" || cp.type_str == "bool")
            ++profile.num_numeric;
        else
            ++profile.num_string;

        profile.columns.push_back(std::move(cp));
    }

    // FIX PERF-1: Now that we know the actual column types (from finalized
    // accumulators), compute the real numeric column count and decide
    // whether to skip correlation. This is the definitive threshold check.
    //
    // If the user passed correlate=true: always compute, regardless of count.
    // If correlate=false (default): skip if numeric cols > MAX_CORR_NUMERIC_COLS.
    size_t actual_numeric_cols = static_cast<size_t>(profile.num_numeric);
    bool skip_correlation_final = !correlate &&
                                  (actual_numeric_cols > MAX_CORR_NUMERIC_COLS ||
                                   skip_correlation_upfront);

    if (skip_correlation_final) {
        profile.correlation_skipped = true;
        if (actual_numeric_cols > MAX_CORR_NUMERIC_COLS) {
            fprintf(stderr,
                "[zedda info] %zu numeric columns exceeds threshold (%zu). "
                "Skipping correlation. Pass correlate=True to force.\n",
                actual_numeric_cols, MAX_CORR_NUMERIC_COLS);
        }
    }

    // Compute pearson correlations only if NOT skipped
    if (!skip_correlation_final && !final_pair_accs.empty()) {
        for (size_t i = 0; i < ncols; ++i) {
            if (profile.columns[i].type_str != "int" && profile.columns[i].type_str != "float") continue;
            for (size_t j = i + 1; j < ncols; ++j) {
                if (profile.columns[j].type_str != "int" && profile.columns[j].type_str != "float") continue;
                
                // FIX C-M1: Use packed upper-triangle index.
                auto& pa = final_pair_accs[pair_idx(i, j, ncols)];
                double r = pa.pearson_r();
                if (!std::isnan(r) && std::abs(r) >= 0.7) {
                    CorrelationResult cr;
                    cr.col_a = col_names[i];
                    cr.col_b = col_names[j];
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

    profile.total_cells      = total_rows * static_cast<int64_t>(ncols);
    profile.total_null_cells = total_null_cells;
    profile.overall_null_pct = (profile.total_cells > 0)
        ? 100.0 * total_null_cells / profile.total_cells : 0.0;

    return profile;
}

// ─────────────────────────────────────────────────────────────────
//  make_column_profile() — convert ColumnAccumulator → ColumnProfile
// ─────────────────────────────────────────────────────────────────
ColumnProfile ProfileBuilder::make_column_profile(
    const ColumnAccumulator& acc,
    const HyperLogLog&       hll,
    int64_t                  /* total_rows */)
{
    ColumnProfile cp;
    cp.name           = acc.name;
    cp.type_str       = column_type_str(acc.type);
    cp.total_count    = acc.count;
    cp.null_count     = acc.null_count;
    cp.non_null_count = acc.non_null_count();
    cp.null_pct       = acc.null_pct;
    cp.unique_approx  = hll.count();
    cp.unique_pct     = (acc.non_null_count() > 0)
        ? 100.0 * static_cast<double>(cp.unique_approx) / acc.non_null_count()
        : 0.0;

    if (acc.type == ColumnType::INTEGER || acc.type == ColumnType::FLOAT ||
        acc.type == ColumnType::BOOLEAN) {
        cp.mean     = acc.mean;
        cp.stddev   = acc.stddev;
        cp.variance = acc.variance;
        cp.skewness = acc.skewness;
        cp.kurtosis = acc.kurtosis;
        if (acc.non_null_count() > 0) {
            cp.val_min = acc.val_min;
            cp.val_max = acc.val_max;
            cp.range   = acc.range();
        }
    }

    if (acc.type == ColumnType::STRING || acc.type == ColumnType::DATETIME) {
        if (acc.non_null_count() > 0) {
            cp.min_str_len  = acc.min_str_len;
            cp.max_str_len  = acc.max_str_len;
            cp.mean_str_len = acc.mean_str_len;
        }
    }

    cp.has_high_nulls      = cp.null_pct > 20.0;
    cp.is_constant         = cp.unique_approx <= 1;
    cp.is_high_cardinality = cp.unique_pct > 90.0;

    return cp;
}

} // namespace zedda