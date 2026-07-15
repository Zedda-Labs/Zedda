#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  zedda::CsvStreamReader — memory-mapped, SIMD-accelerated CSV parser
//
//  PUBLIC API IS UNCHANGED from the original fgets-based version.
//  All callers (ProfileBuilder, Python bindings, tests) work without
//  modification.
//
//  INTERNAL ARCHITECTURE (v2 — mmap + SIMD):
//
//  FAST PATH (use_mmap_ == true):
//    File is memory-mapped via MmapFile.  Parsing uses string_view slices
//    into the mapped buffer — zero copy for field values.  The SIMD scanner
//    locates delimiter/newline boundaries 32-64 bytes at a time.
//    Memory layout: file bytes → mmap buffer → string_view fields → accumulators
//    (no heap allocation per field; ~195M std::string allocations eliminated)
//
//  FALLBACK PATH (use_mmap_ == false):
//    Original fgets + std::string path — used when mmap fails (network FS,
//    containers, permission issues, Windows with unusual file types).
//    Performance is identical to the original v1 implementation.
//
//  CHUNKING:
//    read_chunk() still processes config_.chunk_size rows per call.
//    The chunk boundary logic now works on mmap_pos_ (byte cursor in the
//    mapped buffer) instead of fgets() reads.  ChunkResult is unchanged.
// ─────────────────────────────────────────────────────────────────────────────

#include <string>
#include <string_view>
#include <vector>
#include <deque>
#include <functional>
#include <cstdint>

#include "zedda/column_accumulator.hpp"
#include "zedda/mmap_reader.hpp"
#include "zedda/simd_scanner.hpp"

namespace zedda {

// ─────────────────────────────────────────────────────────────────────────────
//  ChunkResult — unchanged from v1
// ─────────────────────────────────────────────────────────────────────────────
struct ChunkResult {
    int64_t rows_processed = 0;
    int64_t total_rows     = 0;
    bool    done           = false;
};

// ─────────────────────────────────────────────────────────────────────────────
//  StreamReaderConfig — unchanged from v1
// ─────────────────────────────────────────────────────────────────────────────
struct StreamReaderConfig {
    int64_t     chunk_size  = 65536;   // rows per chunk (64K default)
    char        delimiter   = ',';
    char        quote_char  = '"';
    bool        has_header  = true;
    std::string null_string = "";      // treat this string as null
};

// ─────────────────────────────────────────────────────────────────────────────
//  CsvStreamReader — public API identical to v1
// ─────────────────────────────────────────────────────────────────────────────
class CsvStreamReader {
public:
    explicit CsvStreamReader(const std::string& path,
                             StreamReaderConfig  config = {});
    // FIX C-L12: noexcept — destructors that throw during stack unwinding
    // cause std::terminate. close() is noexcept.
    ~CsvStreamReader() noexcept;

    // Returns false if file could not be opened
    bool open();
    void close();

    // Build one accumulator per column (call after open())
    std::vector<ColumnAccumulator> make_accumulators() const;

    // Process next chunk — updates accumulators in place
    ChunkResult read_chunk(std::vector<ColumnAccumulator>& accumulators);

    // Getters — unchanged
    bool                            done()         const { return done_; }
    int64_t                         rows_read()    const { return rows_read_; }
    const std::vector<std::string>& column_names() const { return col_names_; }
    size_t                          num_columns()  const { return col_names_.size(); }
    const std::string&              path()         const { return path_; }

private:
    // ── Configuration ─────────────────────────────────────────────────────────
    std::string        path_;
    StreamReaderConfig config_;

    // ── State ─────────────────────────────────────────────────────────────────
    bool    done_      = false;
    int64_t rows_read_ = 0;

    std::vector<std::string> col_names_;
    std::vector<ColumnType>  col_types_;   // detected after first chunk

    // ── Fast path: mmap + SIMD ────────────────────────────────────────────────
    MmapFile mmap_file_;         // RAII mapped buffer
    size_t   mmap_pos_ = 0;      // current read cursor in the mapped buffer
    ScanFn   scanner_fn_;        // best available scanner (set in open())
    bool     use_mmap_ = false;  // true when mmap succeeded
    // FIX C-H10: Track quote state across read_line_mmap() calls so that
    // embedded newlines inside quoted fields (RFC 4180 §6) don't split
    // a logical record into two lines. When in_quote_ is true, the next
    // newline is part of the field data, not a record terminator.
    bool     in_quote_ = false;

    // ── Fallback path: fgets ──────────────────────────────────────────────────
    FILE*       file_     = nullptr;
    std::string line_buf_;        // reused line buffer for fgets path

    // Storage for escaped-quote fields that cannot be represented as string_view
    // (e.g., fields containing "" escaped quotes that must be unescaped).
    // Cleared at the start of each read_chunk() call.
    std::deque<std::string> fields_storage_;

    // ── Internal helpers — mmap (fast) path ───────────────────────────────────

    /// Read the next CSV line from the mmap buffer.
    /// Returns a string_view into the buffer (zero copy, no allocation).
    /// Advances mmap_pos_ past the newline.
    /// Returns empty string_view when EOF is reached.
    std::string_view read_line_mmap();

    /// Parse a CSV line (given as string_view into mmap buffer) into fields.
    /// Fields are returned as string_view slices — zero copy, no allocation.
    /// Uses the SIMD scanner to find delimiter/quote boundaries.
    bool parse_line_sv(std::string_view                  line,
                       std::vector<std::string_view>&    fields);

    /// Update an accumulator from a string_view field — zero copy hot path.
    void update_accumulator_sv(ColumnAccumulator&  acc,
                               std::string_view    field,
                               ColumnType          type);

    /// Type detection from string_view (no allocation)
    ColumnType detect_type_sv(std::string_view sv);

    /// Null check from string_view (no allocation)
    bool is_null_sv(std::string_view field) const noexcept;

    // ── Internal helpers — fgets (fallback) path ──────────────────────────────
    bool read_header_fgets();
    bool read_header_mmap();
    bool parse_line(const std::string&        line,
                    std::vector<std::string>& fields);
    ColumnType detect_type(const std::string& sample);
    void update_accumulator(ColumnAccumulator&  acc,
                            const std::string&  field,
                            ColumnType          type);
    bool is_null(const std::string& field) const;
};

} // namespace zedda