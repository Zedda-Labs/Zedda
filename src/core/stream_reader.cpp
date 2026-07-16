// ─────────────────────────────────────────────────────────────────────────────
//  zedda::CsvStreamReader — implementation (v2: mmap + SIMD)
//
//  KEY DESIGN DECISIONS:
//
//  1. DUAL PATH ARCHITECTURE
//     Fast path (mmap + SIMD) and fallback path (fgets) share the same
//     public interface.  use_mmap_ is set once in open() and never changes.
//     read_chunk() dispatches based on use_mmap_.
//
//  2. ZERO-COPY FIELD PARSING
//     In the mmap path, parse_line_sv() returns std::string_view slices
//     that point directly into the mmap'd buffer.  No heap allocation occurs
//     per field.  update_accumulator_sv() calls acc.update_string_sv() for
//     string columns — also zero copy.  The buffer stays valid for the entire
//     lifetime of MmapFile (i.e., until close() is called).
//
//  3. FAST NUMERIC PARSING
//     fast_atod() works on char* + length — compatible with both string_view
//     (via .data() + .size()) and std::string.  No change needed there.
//
//  4. TYPE DETECTION CACHING
//     col_types_ is filled on first non-null value per column (same as v1).
//     Once UNKNOWN becomes a real type, the branch is never taken again for
//     that column — effectively the type check is O(1) amortized.
//
//  5. WINDOWS \r\n HANDLING
//     read_line_mmap() strips both '\r' and '\n' from line endings.
//     The SIMD scanner finds '\r' and '\n' simultaneously; the caller skips
//     both when present (the '\r' advances pos_ by 1, then '\n' by 1 more).
// ─────────────────────────────────────────────────────────────────────────────

#include "zedda/stream_reader.hpp"
#include "zedda/hyperloglog.hpp"

#include <iostream>
#include <sstream>
#include <cstring>
#include <cctype>
#include <algorithm>
#include <stdexcept>
#include <cmath>

#include "zedda/fast_float/fast_float.h"
#include "zedda/parsing_utils.hpp"

namespace zedda {

// ─────────────────────────────────────────────────────────────────────────────
//  Constructor / Destructor
// ─────────────────────────────────────────────────────────────────────────────
CsvStreamReader::CsvStreamReader(const std::string& path,
                                 StreamReaderConfig  config)
    : path_(path)
    , config_(config)
    , mmap_file_(path)
    , scanner_fn_(get_active_scanner())   // best scanner selected once at construction
{}

// FIX C-L12: Mark destructor noexcept — destructors that throw during
// stack unwinding cause std::terminate. close() only calls fclose (no throw)
// and MmapFile::close() (noexcept), so this is safe.
CsvStreamReader::~CsvStreamReader() noexcept {
    close();
}

// ─────────────────────────────────────────────────────────────────────────────
//  open() — try mmap first, fall back to fgets on failure
// ─────────────────────────────────────────────────────────────────────────────
bool CsvStreamReader::open() {
    // ── Attempt mmap ──────────────────────────────────────────────────────────
    if (mmap_file_.open()) {
        use_mmap_ = true;
        mmap_pos_ = 0;
        // FIX C-H10: Reset quote state on open.
        in_quote_ = false;

        // FIX C-H11: Skip a leading UTF-8 BOM (EF BB BF) if present.
        // Without this, the first column header would be prefixed with
        // 3 garbage bytes, breaking all subsequent name-based lookups.
        if (mmap_file_.size() >= 3) {
            const unsigned char* p = reinterpret_cast<const unsigned char*>(mmap_file_.data());
            if (p[0] == 0xEF && p[1] == 0xBB && p[2] == 0xBF) {
                mmap_pos_ = 3;
            }
        }

        // Validate: not a binary file (check first 512 bytes for NULL bytes)
        size_t probe_len = std::min(mmap_file_.size(), size_t(512));
        const char* buf  = mmap_file_.data();
        for (size_t i = mmap_pos_; i < probe_len; ++i) {
            if (buf[i] == '\0') {
                throw std::runtime_error(
                    "File appears to be binary (contains NULL bytes), not CSV: " + path_);
            }
        }

        if (config_.has_header) {
            if (!read_header_mmap()) {
                throw std::runtime_error("[zedda] Failed to read header from: " + path_ + " at line 1");
            }
        }
        return true;
    }

    // ── Fallback: fgets ───────────────────────────────────────────────────────
    use_mmap_ = false;
    file_ = fopen(path_.c_str(), "rb");
    if (!file_) {
        throw std::runtime_error(
            "Cannot open file: '" + path_ + "'\n"
            "Check: file exists, readable permissions, valid path");
    }

    // FIX C-H11: Skip UTF-8 BOM in fgets path too.
    char bom[3];
    size_t bom_n = fread(bom, 1, 3, file_);
    if (bom_n == 3 && (unsigned char)bom[0] == 0xEF
        && (unsigned char)bom[1] == 0xBB && (unsigned char)bom[2] == 0xBF) {
        // BOM consumed — do not rewind.
    } else {
        rewind(file_);
    }

    // Binary check for fgets path (same as v1)
    char probe[512];
    size_t n = fread(probe, 1, 512, file_);
    rewind(file_);
    // Re-skip BOM if present (rewind reset it).
    if (bom_n == 3 && (unsigned char)bom[0] == 0xEF
        && (unsigned char)bom[1] == 0xBB && (unsigned char)bom[2] == 0xBF) {
        fseek(file_, 3, SEEK_SET);
    }
    for (size_t i = 0; i < n; i++) {
        if (probe[i] == '\0') {
            throw std::runtime_error(
                "File appears to be binary (contains NULL bytes), not CSV: " + path_);
        }
    }

    if (config_.has_header) {
        if (!read_header_fgets()) {
            throw std::runtime_error("[zedda] Failed to read header from: " + path_ + " at line 1");
        }
    }
    return true;
}

void CsvStreamReader::close() {
    mmap_file_.close();
    if (file_) {
        fclose(file_);
        file_ = nullptr;
    }
}

// ─────────────────────────────────────────────────────────────────────────────
//  make_accumulators() — unchanged from v1
// ─────────────────────────────────────────────────────────────────────────────
std::vector<ColumnAccumulator> CsvStreamReader::make_accumulators() const {
    std::vector<ColumnAccumulator> accs;
    accs.resize(col_names_.size());
    for (size_t i = 0; i < col_names_.size(); ++i) {
        accs[i].name = col_names_[i];
        accs[i].type = ColumnType::UNKNOWN;
    }
    return accs;
}

// ─────────────────────────────────────────────────────────────────────────────
//  read_chunk() — main dispatch
// ─────────────────────────────────────────────────────────────────────────────
ChunkResult CsvStreamReader::read_chunk(std::vector<ColumnAccumulator>& accs) {
    ChunkResult result;

    if (done_) {
        result.done = true;
        return result;
    }

    // Ensure col_types_ is sized correctly
    if (col_types_.size() < accs.size()) {
        col_types_.resize(accs.size(), ColumnType::UNKNOWN);
    }

    int64_t chunk_rows = 0;

    if (use_mmap_) {
        // ── FAST PATH: mmap + SIMD + string_view ─────────────────────────────
        // Release any escaped-quote strings from the previous chunk before
        // reusing fields_storage_ for this chunk.
        fields_storage_.clear();

        // Pre-allocate field vector once per chunk (reuse across rows)
        std::vector<std::string_view> sv_fields;
        sv_fields.reserve(accs.size());

        while (chunk_rows < config_.chunk_size) {
            std::string_view line = read_line_mmap();

            if (line.data() == nullptr) {
                // EOF: mmap_pos_ hit end of buffer
                done_ = true;
                break;
            }

            if (line.empty()) continue;  // skip blank lines

            sv_fields.clear();
            if (!parse_line_sv(line, sv_fields)) continue;

            // Pad to column count (missing trailing fields = empty string_view)
            if (sv_fields.size() < accs.size()) {
                std::cerr << "[zedda warning] Row " << (rows_read_ + 1)
                          << " has only " << sv_fields.size()
                          << " columns (expected " << accs.size()
                          << ") - padding with nulls.\n";
                while (sv_fields.size() < accs.size()) {
                    sv_fields.push_back(std::string_view{});
                }
            }
            // FIX C-M3: Warn when a row has MORE fields than expected.
            // Previously extra fields were silently truncated (the per-row
            // loop only iterates up to accs.size()), producing incorrect
            // stats with no warning.
            else if (sv_fields.size() > accs.size()) {
                // Only warn once per 1000 occurrences to avoid log spam.
                static thread_local int64_t extra_fields_count = 0;
                if (++extra_fields_count <= 10 || extra_fields_count % 1000 == 0) {
                    std::cerr << "[zedda warning] Row " << (rows_read_ + 1)
                              << " has " << sv_fields.size()
                              << " columns (expected " << accs.size()
                              << ") - extra fields truncated."
                              << (extra_fields_count > 10 ? " (further warnings suppressed)" : "")
                              << "\n";
                }
            }

            for (size_t col = 0; col < accs.size(); ++col) {
                std::string_view field = sv_fields[col];

                if (is_null_sv(field)) {
                    accs[col].update_null();
                    continue;
                }

                // Auto-detect type on first non-null value
                if (col_types_[col] == ColumnType::UNKNOWN) {
                    col_types_[col] = detect_type_sv(field);
                    accs[col].type  = col_types_[col];
                }

                update_accumulator_sv(accs[col], field, col_types_[col]);
            }

            ++chunk_rows;
            ++rows_read_;
        }

    } else {
        // ── FALLBACK PATH: fgets + std::string ───────────────────────────────
        std::vector<std::string> fields;
        fields.reserve(accs.size());
        char buf[65536];

        while (chunk_rows < config_.chunk_size) {
            if (fgets(buf, sizeof(buf), file_) == nullptr) {
                done_ = true;
                break;
            }

            size_t len = strlen(buf);
            bool has_newline = (len > 0 && (buf[len-1] == '\n' || buf[len-1] == '\r'));
            while (len > 0 && (buf[len-1] == '\n' || buf[len-1] == '\r')) buf[--len] = '\0';
            line_buf_.assign(buf, len);

            while (!has_newline) {
                if (fgets(buf, sizeof(buf), file_) == nullptr) break;
                size_t extra = strlen(buf);
                has_newline = (extra > 0 && (buf[extra-1] == '\n' || buf[extra-1] == '\r'));
                while (extra > 0 && (buf[extra-1] == '\n' || buf[extra-1] == '\r')) buf[--extra] = '\0';
                line_buf_.append(buf, extra);
            }

            if (line_buf_.empty()) continue;
            fields.clear();
            if (!parse_line(line_buf_, fields)) continue;

            fields.resize(accs.size(), "");

            for (size_t col = 0; col < accs.size(); ++col) {
                const std::string& field = fields[col];
                if (is_null(field)) {
                    accs[col].update_null();
                    continue;
                }
                if (col_types_[col] == ColumnType::UNKNOWN) {
                    col_types_[col] = detect_type(field);
                    accs[col].type  = col_types_[col];
                }
                update_accumulator(accs[col], field, col_types_[col]);
            }

            ++chunk_rows;
            ++rows_read_;
        }
    }

    result.rows_processed = chunk_rows;
    result.total_rows     = rows_read_;
    result.done           = done_;
    return result;
}

// ─────────────────────────────────────────────────────────────────────────────
//  read_line_mmap() — zero-copy line reader for the mmap buffer
//
//  Returns a string_view into the mmap'd buffer for the current line.
//  Advances mmap_pos_ past the '\n' (and '\r' if present before '\n').
//  Returns a null string_view (data() == nullptr) when EOF is reached.
//
//  FIX C-H10: Quote-aware newline detection. RFC 4180 §6 allows embedded
//  newlines inside quoted fields ("line1\nline2"). The previous version
//  split at the first \n regardless of quote state, corrupting records
//  with multi-line quoted fields. Now we track in_quote_ across calls
//  and skip newlines that appear inside quoted fields.
// ─────────────────────────────────────────────────────────────────────────────
std::string_view CsvStreamReader::read_line_mmap() {
    const char* buf = mmap_file_.data();
    size_t      len = mmap_file_.size();

    if (mmap_pos_ >= len) return std::string_view{};  // EOF

    size_t line_start = mmap_pos_;
    char   quote_char = config_.quote_char;

    // Scan for the end of line, respecting quote state.
    // We use the SIMD scanner to find candidate \n/\r positions, then
    // check if we're inside a quoted field. If so, continue scanning.
    while (mmap_pos_ < len) {
        size_t eol = scanner_fn_(buf, len, mmap_pos_, '\n', '\r');
        if (eol >= len) {
            // No more newlines — rest of file is the last line.
            mmap_pos_ = len;
            break;
        }

        // Count quote chars between line_start (or last position) and eol
        // to determine if we're inside a quoted field. We scan the segment
        // [mmap_pos_, eol) for the quote char, toggling in_quote_ on each
        // unescaped quote ("" is an escaped quote, not a field terminator).
        for (size_t i = mmap_pos_; i < eol; ++i) {
            if (buf[i] == quote_char) {
                // Check for escaped quote ("")
                if (in_quote_ && i + 1 < eol && buf[i + 1] == quote_char) {
                    ++i;  // skip the second quote
                } else {
                    in_quote_ = !in_quote_;
                }
            }
        }

        if (!in_quote_) {
            // We're outside a quoted field — this newline is a real EOL.
            size_t line_end = eol;
            mmap_pos_ = eol;
            // Skip \r\n or \n or \r
            if (mmap_pos_ < len && buf[mmap_pos_] == '\r') ++mmap_pos_;
            if (mmap_pos_ < len && buf[mmap_pos_] == '\n') ++mmap_pos_;
            return std::string_view(buf + line_start, line_end - line_start);
        }

        // We're inside a quoted field — this newline is embedded data.
        // Continue scanning from the next position.
        mmap_pos_ = eol;
        if (mmap_pos_ < len && buf[mmap_pos_] == '\r') ++mmap_pos_;
        if (mmap_pos_ < len && buf[mmap_pos_] == '\n') ++mmap_pos_;
    }

    // Reached EOF — return whatever remains (may be inside an unterminated quote).
    return std::string_view(buf + line_start, mmap_pos_ - line_start);
}

// ─────────────────────────────────────────────────────────────────────────────
//  parse_line_sv() — SIMD-accelerated RFC 4180 CSV parser
//
//  Operates entirely on string_view into the mmap'd buffer.
//  No heap allocation occurs.  Fields are string_view slices of `line`.
//
//  Quoted field handling:
//    - When we enter a quoted field, we scan for the next '"' using SIMD.
//    - Escaped quotes ("") require building a std::string — rare case,
//      handled gracefully with a local buffer.
//    - Unquoted fields: scan directly for the next delimiter using SIMD.
// ─────────────────────────────────────────────────────────────────────────────
bool CsvStreamReader::parse_line_sv(std::string_view                line,
                                    std::vector<std::string_view>&  fields) {
    fields.clear();

    const char* data  = line.data();
    size_t      len   = line.size();
    const char  delim = config_.delimiter;
    const char  quote = config_.quote_char;

    if (len == 0) {
        // Empty line — push one empty field and return
        fields.push_back(std::string_view{});
        return true;
    }

    size_t pos = 0;

    // RFC 4180 parsing loop.
    // Invariant: at the start of each iteration, pos points to the first
    // byte of the next field (which may be a quote, a regular char, or == len
    // only when the line ends with a trailing delimiter).
    while (true) {
        // Guard: if we've consumed all bytes, we're done (no trailing empty field
        // unless the line ended with a delimiter, handled inside each branch).
        if (pos >= len) break;

        if (data[pos] == quote) {
            // ── Quoted field ─────────────────────────────────────────────────
            size_t field_start = ++pos;  // skip opening quote

            // Check for escaped-quote ("") pattern first:
            // scan byte-by-byte inside the quoted region.
            // We prefer correctness over performance here — quoted fields
            // with escaped quotes are uncommon in hot CSV workloads.
            bool has_escape = false;
            size_t qpos = pos;
            while (qpos < len && data[qpos] != quote) ++qpos;
            // Check for "" (escaped quote)
            if (qpos + 1 < len && data[qpos + 1] == quote) has_escape = true;

            if (!has_escape) {
                // Simple quoted field — zero-copy string_view
                fields.push_back(std::string_view(data + field_start, qpos - field_start));
                pos = qpos + 1;  // skip closing quote
            } else {
                // Quoted field with escaped quotes — must unescape, rare allocation
                std::string unescaped;
                unescaped.reserve(64);
                size_t p = field_start;
                while (p < len) {
                    if (data[p] == quote) {
                        if (p + 1 < len && data[p + 1] == quote) {
                            unescaped += quote;
                            p += 2;
                        } else {
                            break;  // closing quote
                        }
                    } else {
                        unescaped += data[p++];
                    }
                }
                // Store in fields_storage_ (lives for duration of the chunk)
                fields_storage_.push_back(std::move(unescaped));
                fields.push_back(std::string_view(fields_storage_.back()));
                pos = (p < len) ? p + 1 : p;  // safely skip closing quote if present
            }

            // After closing quote: expect delimiter or end-of-line
            if (pos < len && data[pos] == delim) {
                ++pos;  // consume delimiter and continue to next field
                // If delimiter is at the very end, we'll push empty field at bottom
                if (pos == len) {
                    fields.push_back(std::string_view{});
                    break;
                }
                continue;
            }
            // End of line after closing quote — done
            break;

        } else {
            // ── Unquoted field — SIMD scan for next delimiter ─────────────────
            // scanner_fn_ returns position of next: delim, quote, \n, or \r.
            // Since the line has already had its trailing newline stripped by
            // read_line_mmap(), we pass delim as BOTH the delim and quote args
            // so the scanner stops only at the field delimiter (treating any
            // in-field quote as a regular character — liberal CSV mode).
            size_t field_start = pos;
            size_t end_pos     = scanner_fn_(data, len, pos, delim, delim);

            fields.push_back(std::string_view(data + field_start, end_pos - field_start));
            pos = end_pos;

            if (pos < len && data[pos] == delim) {
                ++pos;  // consume delimiter
                // Trailing delimiter means one more empty field follows
                if (pos == len) {
                    fields.push_back(std::string_view{});
                    break;
                }
                continue;
            }
            // No delimiter found — this was the last field
            break;
        }
    }

    return true;
}

// ─────────────────────────────────────────────────────────────────────────────
//  detect_type_sv() — type inference from string_view (no allocation)
// ─────────────────────────────────────────────────────────────────────────────

ColumnType CsvStreamReader::detect_type_sv(std::string_view sv) {
    if (sv.empty()) return ColumnType::UNKNOWN;

    const char* s   = sv.data();
    size_t      len = sv.size();

    // Boolean check — case-insensitive compare without allocation
    auto eq_ci = [](std::string_view a, const char* b) {
        if (a.size() != strlen(b)) return false;
        for (size_t i = 0; i < a.size(); ++i)
            if (tolower((unsigned char)a[i]) != tolower((unsigned char)b[i])) return false;
        return true;
    };
    if (eq_ci(sv, "true") || eq_ci(sv, "false") ||
        eq_ci(sv, "yes")  || eq_ci(sv, "no")    ||
        sv == "1"         || sv == "0")
        return ColumnType::BOOLEAN;

    // Integer check
    size_t start = (s[0] == '-' || s[0] == '+') ? 1 : 0;
    bool is_int  = (start < len);
    for (size_t i = start; i < len && is_int; ++i) {
        if (!std::isdigit(static_cast<unsigned char>(s[i]))) is_int = false;
    }
    if (is_int) return ColumnType::INTEGER;

    // Float check
    double dummy;
    if (fast_atod(s, len, dummy)) return ColumnType::FLOAT;

    // Datetime heuristic
    bool has_date_sep = (sv.find('-') != sv.npos || sv.find('/') != sv.npos);
    bool has_time_sep = (sv.find(':') != sv.npos || sv.find('T') != sv.npos);
    if (has_date_sep && len >= 8) return ColumnType::DATETIME;
    if (has_date_sep && has_time_sep) return ColumnType::DATETIME;

    return ColumnType::STRING;
}

// ─────────────────────────────────────────────────────────────────────────────
//  is_null_sv() — null check without allocation
// ─────────────────────────────────────────────────────────────────────────────
bool CsvStreamReader::is_null_sv(std::string_view field) const noexcept {
    if (field.empty()) return true;

    // Check config null_string first
    if (!config_.null_string.empty() &&
        field == std::string_view(config_.null_string))
        return true;

    // FIX C-L11: Delegate to fast_is_null for consistent case-insensitive
    // null detection (was exact-case for "null"/"NULL"/"none"/"None" but
    // case-insensitive for "NaN"/"nan" — inconsistent with fast_is_null).
    return fast_is_null(field.data(), field.size());
}

// ─────────────────────────────────────────────────────────────────────────────
//  update_accumulator_sv() — zero-copy accumulator update
// ─────────────────────────────────────────────────────────────────────────────
void CsvStreamReader::update_accumulator_sv(ColumnAccumulator& acc,
                                             std::string_view   field,
                                             ColumnType         type) {
    switch (type) {
        case ColumnType::INTEGER:
        case ColumnType::FLOAT: {
            double val;
            if (fast_atod(field.data(), field.size(), val)) {
                acc.update(val);
            } else {
                acc.update_null();
            }
            break;
        }
        case ColumnType::BOOLEAN: {
            // FIX C-H12: Use strict case-insensitive parser to avoid
            // matching "track", "field", "from", etc.
            double bv = fast_parse_bool(field.data(), field.size());
            if (bv >= 0.0) acc.update(bv); else acc.update_null();
            break;
        }
        case ColumnType::STRING:
        case ColumnType::DATETIME:
        case ColumnType::UNKNOWN:
        default: {
            // update_string_sv is the zero-copy path — already exists in
            // column_accumulator.hpp (added in v1 but unused until now)
            acc.update_string_sv(field);
            break;
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
//  read_header_mmap() — parse header row from mmap buffer
// ─────────────────────────────────────────────────────────────────────────────
bool CsvStreamReader::read_header_mmap() {
    std::string_view header_line = read_line_mmap();
    if (header_line.data() == nullptr || header_line.empty()) {
        return false;
    }

    std::vector<std::string_view> name_views;
    if (!parse_line_sv(header_line, name_views)) {
        return false;
    }

    col_names_.clear();
    col_names_.reserve(name_views.size());

    for (auto sv : name_views) {
        size_t start = 0;
        while (start < sv.size() && (sv[start] == ' ' || sv[start] == '\t' || sv[start] == '"'))
            ++start;
        size_t end = sv.size();
        while (end > start && (sv[end-1] == ' ' || sv[end-1] == '\t' || sv[end-1] == '"'))
            --end;
        col_names_.push_back(std::string(sv.substr(start, end - start)));
    }

    return !col_names_.empty();
}

// ─────────────────────────────────────────────────────────────────────────────
//  Fallback path — identical to v1 implementation
// ─────────────────────────────────────────────────────────────────────────────
bool CsvStreamReader::read_header_fgets() {
    char buf[65536];
    if (fgets(buf, sizeof(buf), file_) == nullptr) return false;
    size_t len = strlen(buf);
    bool has_newline = (len > 0 && (buf[len-1] == '\n' || buf[len-1] == '\r'));
    while (len > 0 && (buf[len-1] == '\n' || buf[len-1] == '\r')) buf[--len] = '\0';
    line_buf_.assign(buf, len);
    while (!has_newline) {
        if (fgets(buf, sizeof(buf), file_) == nullptr) break;
        size_t extra = strlen(buf);
        has_newline = (extra > 0 && (buf[extra-1] == '\n' || buf[extra-1] == '\r'));
        while (extra > 0 && (buf[extra-1] == '\n' || buf[extra-1] == '\r')) buf[--extra] = '\0';
        line_buf_.append(buf, extra);
    }
    std::vector<std::string> names;
    if (!parse_line(line_buf_, names)) return false;
    for (auto& name : names) {
        size_t start = name.find_first_not_of(" \t\"");
        size_t end   = name.find_last_not_of(" \t\"");
        if (start != std::string::npos)
            name = name.substr(start, end - start + 1);
    }
    col_names_ = std::move(names);
    return !col_names_.empty();
}

bool CsvStreamReader::parse_line(const std::string&        line,
                                  std::vector<std::string>& fields) {
    fields.clear();
    std::string field;
    field.reserve(64);
    bool in_quotes = false;
    size_t i = 0;
    const size_t n = line.size();
    while (i < n) {
        char c = line[i];
        if (in_quotes) {
            if (c == config_.quote_char) {
                if (i + 1 < n && line[i+1] == config_.quote_char) {
                    field += c;
                    ++i;
                } else {
                    in_quotes = false;
                }
            } else {
                field += c;
            }
        } else {
            if (c == config_.quote_char) {
                in_quotes = true;
            } else if (c == config_.delimiter) {
                fields.push_back(field);
                field.clear();
            } else {
                field += c;
            }
        }
        ++i;
    }
    fields.push_back(field);
    return true;
}

ColumnType CsvStreamReader::detect_type(const std::string& s) {
    if (s.empty()) return ColumnType::UNKNOWN;
    std::string lower = s;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
    if (lower == "true" || lower == "false" ||
        lower == "yes"  || lower == "no"    ||
        lower == "1"    || lower == "0")
        return ColumnType::BOOLEAN;
    size_t start = (s[0] == '-' || s[0] == '+') ? 1 : 0;
    bool is_int = (start < s.size());
    for (size_t i = start; i < s.size() && is_int; ++i)
        if (!std::isdigit(static_cast<unsigned char>(s[i]))) is_int = false;
    if (is_int) return ColumnType::INTEGER;
    double dummy;
    if (fast_atod(s.data(), s.size(), dummy)) return ColumnType::FLOAT;
    bool has_date_sep = (s.find('-') != std::string::npos || s.find('/') != std::string::npos);
    bool has_time_sep = (s.find(':') != std::string::npos || s.find('T') != std::string::npos);
    if (has_date_sep && s.size() >= 8) return ColumnType::DATETIME;
    if (has_date_sep && has_time_sep)  return ColumnType::DATETIME;
    return ColumnType::STRING;
}

void CsvStreamReader::update_accumulator(ColumnAccumulator& acc,
                                          const std::string& field,
                                          ColumnType         type) {
    switch (type) {
        case ColumnType::INTEGER:
        case ColumnType::FLOAT: {
            double val;
            if (fast_atod(field.data(), field.size(), val)) {
                acc.update(val);
            } else {
                acc.update_null();
            }
            break;
        }
        case ColumnType::BOOLEAN: {
            // FIX C-H12: Use strict case-insensitive parser to avoid
            // matching "track", "field", "from", etc.
            double bv = fast_parse_bool(field.data(), field.size());
            if (bv >= 0.0) acc.update(bv); else acc.update_null();
            break;
        }
        default: {
            acc.update_string(field);
            break;
        }
    }
}

bool CsvStreamReader::is_null(const std::string& field) const {
    if (field.empty())                    return true;
    if (field == config_.null_string)     return true;
    if (field == "NA"   || field == "N/A") return true;
    if (field == "null" || field == "NULL") return true;
    if (field == "nan"  || field == "NaN")  return true;
    if (field == "none" || field == "None") return true;
    if (field == "#N/A" || field == "?")    return true;
    return false;
}

} // namespace zedda