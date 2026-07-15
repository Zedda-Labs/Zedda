#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  zedda/parsing_utils.hpp — Shared CSV parsing utilities
//
//  ISS-008/009/010: Extracted from stream_reader.cpp and profile_builder.cpp
//  to eliminate identical duplicate implementations.
//
//  Contains:
//    fast_atod()       — fast numeric parsing via fast_float
//    fast_is_null()    — branch-minimal null check
//    fast_detect_type() — column type inference
// ─────────────────────────────────────────────────────────────────────────────

#include <cctype>
#include <cmath>
#include <cstring>
#include "zedda/column_accumulator.hpp"
#include "zedda/fast_float/fast_float.h"

namespace zedda {

// ─────────────────────────────────────────────────────────────────────────────
//  fast_atod — wrapper around fast_float, works on char* + length
//
//  NaN/Inf REJECTION: CSV fields like "NaN", "inf", "-inf", "infinity" are
//  NOT valid numeric values in CSV context — they should be classified as
//  STRING or NULL.  We reject them via:
//    1. fast_float::chars_format::no_infnan  — tells fast_float to reject them
//    2. std::isfinite() post-check           — defense-in-depth
// ─────────────────────────────────────────────────────────────────────────────
static inline bool fast_atod(const char* s, size_t len, double& out) {
    if (len == 0) return false;

    // Strip leading whitespace
    size_t i = 0;
    while (i < len && std::isspace(static_cast<unsigned char>(s[i]))) {
        ++i;
    }
    if (i == len) return false;

    // Strip trailing whitespace (compute effective end)
    size_t end_idx = len;
    while (end_idx > i && std::isspace(static_cast<unsigned char>(s[end_idx - 1]))) {
        --end_idx;
    }
    if (i == end_idx) return false;

    // Handle unary '+' (fast_float requires explicit opt-in for leading '+')
    if (s[i] == '+') {
        ++i;
        if (i == end_idx) return false;
    }

    // Parse with no_infnan: rejects "NaN", "inf", "-inf", "infinity"
    constexpr auto fmt = fast_float::chars_format::general
                       | fast_float::chars_format::no_infnan;
    fast_float::parse_options opts(fmt);
    auto result = fast_float::from_chars_float_advanced(s + i, s + end_idx, out, opts);
    if (result.ec != std::errc()) {
        return false;
    }

    // Ensure the entire trimmed input was consumed (no trailing garbage)
    if (result.ptr != s + end_idx) {
        return false;
    }

    // Defense-in-depth: reject non-finite results even if fast_float
    // somehow produced them (e.g., overflow to infinity)
    if (!std::isfinite(out)) {
        return false;
    }

    return true;
}

// ─────────────────────────────────────────────────────────────────────────────
//  fast_is_null — branch-minimal null check (no alloc)
//
//  FIX C-L7: All null markers are now case-insensitive (was inconsistent —
//  "NaN"/"nan" was case-insensitive but "null"/"NULL" and "none"/"None"
//  were exact-case only, so "Null", "nULL", "NONE" were not detected).
//  FIX C-L8: Single "?" is still treated as null for R/pandas backward
//  compatibility (documented behavior — "?" is a common missing-value
//  marker in survey data exports).
// ─────────────────────────────────────────────────────────────────────────────
static inline bool fast_is_null(const char* s, size_t len) {
    switch (len) {
        case 0: return true;
        case 1: return s[0] == '?';
        case 2: {
            // "NA" case-insensitive
            char a = s[0], b = s[1];
            if (a >= 'A' && a <= 'Z') a += 32;
            if (b >= 'A' && b <= 'Z') b += 32;
            return a == 'n' && b == 'a';
        }
        case 3: {
            // "NaN"/"nan" case-insensitive, OR "N/A" (case-insensitive)
            char a = s[0], b = s[1], c = s[2];
            if (a >= 'A' && a <= 'Z') a += 32;
            if (b >= 'A' && b <= 'Z') b += 32;
            if (c >= 'A' && c <= 'Z') c += 32;
            return (a == 'n' && b == 'a' && c == 'n')
                || (a == 'n' && b == '/' && c == 'a');
        }
        case 4: {
            // "null", "none", "#n/a" — all case-insensitive.
            // FIX C-L7: Was exact-case only for "null"/"NULL"/"None"/"none".
            char a = s[0], b = s[1], c = s[2], d = s[3];
            if (a >= 'A' && a <= 'Z') a += 32;
            if (b >= 'A' && b <= 'Z') b += 32;
            if (c >= 'A' && c <= 'Z') c += 32;
            if (d >= 'A' && d <= 'Z') d += 32;
            return (a == 'n' && b == 'u' && c == 'l' && d == 'l')      // null
                || (a == 'n' && b == 'o' && c == 'n' && d == 'e')      // none
                || (a == '#' && b == 'n' && c == '/' && d == 'a');     // #n/a
        }
        default: return false;
    }
}

// ─────────────────────────────────────────────────────────────────────────────
//  fast_detect_type — infer ColumnType from char* (no alloc)
// ─────────────────────────────────────────────────────────────────────────────
static inline ColumnType fast_detect_type(const char* s, size_t len) {
    if (len == 0) return ColumnType::UNKNOWN;

    // Boolean literals
    if (len==4 && (std::memcmp(s,"true",4)==0||std::memcmp(s,"True",4)==0||std::memcmp(s,"TRUE",4)==0)) return ColumnType::BOOLEAN;
    if (len==5 && (std::memcmp(s,"false",5)==0||std::memcmp(s,"False",5)==0||std::memcmp(s,"FALSE",5)==0)) return ColumnType::BOOLEAN;
    if (len==3 && (std::memcmp(s,"yes",3)==0||std::memcmp(s,"Yes",3)==0||std::memcmp(s,"YES",3)==0)) return ColumnType::BOOLEAN;
    if (len==2 && (std::memcmp(s,"no",2)==0||std::memcmp(s,"No",2)==0||std::memcmp(s,"NO",2)==0)) return ColumnType::BOOLEAN;

    // Integer: optional sign, then all digits
    size_t start = (s[0]=='-'||s[0]=='+') ? 1u : 0u;
    if (start < len) {
        bool all_dig = true;
        for (size_t i = start; i < len && all_dig; ++i)
            if (!isdigit((unsigned char)s[i])) all_dig = false;
        if (all_dig) return ColumnType::INTEGER;
    }

    // Float: use fast_atod
    double dummy;
    if (fast_atod(s, len, dummy)) return ColumnType::FLOAT;

    return ColumnType::STRING;
}

// ─────────────────────────────────────────────────────────────────────────────
//  fast_parse_bool — strict case-insensitive boolean parser.
//
//  FIX C-H12: Replaces the loose `fl >= 4 && fs[0]=='t'` check that
//  matched "track", "field", "from", etc. Returns 1.0 for true, 0.0
//  for false, or -1.0 to indicate "not a recognized bool literal".
//  Accepts only: 1/0, true/false, yes/no, y/n (case-insensitive).
// ─────────────────────────────────────────────────────────────────────────────
static inline double fast_parse_bool(const char* s, size_t len) {
    auto ieq = [](const char* a, size_t alen, const char* b) {
        size_t blen = std::strlen(b);
        if (alen != blen) return false;
        for (size_t i = 0; i < blen; ++i) {
            char ca = a[i], cb = b[i];
            if (ca >= 'A' && ca <= 'Z') ca += 32;
            if (cb >= 'A' && cb <= 'Z') cb += 32;
            if (ca != cb) return false;
        }
        return true;
    };
    if (ieq(s, len, "1") || ieq(s, len, "true") || ieq(s, len, "yes") || ieq(s, len, "y"))
        return 1.0;
    if (ieq(s, len, "0") || ieq(s, len, "false") || ieq(s, len, "no") || ieq(s, len, "n"))
        return 0.0;
    return -1.0;
}

} // namespace zedda
