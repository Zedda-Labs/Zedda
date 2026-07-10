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
// ─────────────────────────────────────────────────────────────────────────────
static inline bool fast_is_null(const char* s, size_t len) {
    switch (len) {
        case 0: return true;
        case 1: return s[0] == '?';
        case 2: return s[0]=='N' && s[1]=='A';
        case 3: return ((s[0]=='N'||s[0]=='n') &&
                        (s[1]=='A'||s[1]=='a') &&
                        (s[2]=='N'||s[2]=='n'))          // NaN / nan
                    || ( s[0]=='N' && s[1]=='/' && s[2]=='A');  // N/A
        case 4: return (std::memcmp(s,"null",4)==0)
                    || (std::memcmp(s,"NULL",4)==0)
                    || (std::memcmp(s,"None",4)==0)
                    || (std::memcmp(s,"none",4)==0)
                    || (std::memcmp(s,"#N/A",4)==0);
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

} // namespace zedda
