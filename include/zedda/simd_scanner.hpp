#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  zedda::simd_scanner — SIMD-accelerated CSV delimiter/newline finder
//
//  ARCHITECTURE:
//  This header declares three implementations of the same function:
//    find_next_special_scalar()  — portable, the correctness reference
//    find_next_special_avx2()    — 32 bytes/cycle, requires AVX2
//    find_next_special_avx512()  — 64 bytes/cycle, requires AVX-512BW
//
//  RUNTIME DISPATCH:
//  CPU features are checked once at startup via has_avx2() / has_avx512f().
//  select_best_scanner() returns a function pointer to the best available
//  implementation. This pointer is stored and called in the hot loop —
//  NO branching on CPU features inside the per-row or per-byte loop.
//
//  SAFETY GUARANTEE:
//  - The SIMD functions are compiled in simd_scanner.cpp with -mavx2 / /arch:AVX2.
//    The dispatch decision is made at RUNTIME, so a user on a CPU without AVX2
//    will always get the scalar path — they never execute the AVX2 instructions.
//  - ZEDDA_FORCE_SCALAR=1 env var forces scalar for testing / debugging.
//
//  TECHNIQUE (AVX2 hot loop, same as simdjson/simdcsv):
//    1. _mm256_loadu_si256  — load 32 bytes (unaligned OK)
//    2. _mm256_cmpeq_epi8   — compare all 32 bytes against delimiter
//    3. _mm256_cmpeq_epi8   — compare all 32 bytes against quote char
//    4. _mm256_cmpeq_epi8   — compare all 32 bytes against '\n'
//    5. OR the three result vectors
//    6. _mm256_movemask_epi8 — collapse to 32-bit integer bitmask
//    7. If mask != 0: __builtin_ctz gives index of first match
//    8. If mask == 0: advance by 32 bytes, loop
//    Remainder (< 32 bytes) handled by scalar fallback.
// ─────────────────────────────────────────────────────────────────────────────

#include <cstddef>
#include <cstdint>

namespace zedda {

// ─────────────────────────────────────────────────────────────────────────────
//  CPU feature detection
//  These functions are safe to call on ANY CPU — they detect features,
//  they do NOT execute AVX instructions themselves.
// ─────────────────────────────────────────────────────────────────────────────

/// Returns true if the current CPU supports AVX2 (256-bit integer SIMD).
bool has_avx2() noexcept;

/// Returns true if the current CPU supports AVX-512F + AVX-512BW.
/// (AVX-512BW needed for byte-level comparisons with 512-bit vectors)
bool has_avx512f() noexcept;

// ─────────────────────────────────────────────────────────────────────────────
//  Three scan implementations — identical signatures, different throughput
//
//  Scans data[pos .. len-1] for the first occurrence of:
//    - delim      (CSV field separator, typically ',')
//    - quote      (CSV quote character, typically '"')
//    - '\n'       (line ending)
//    - '\r'       (Windows line ending prefix)
//
//  Returns: byte offset of the first match relative to data[0].
//           Returns len if no match found (caller should treat as end-of-data).
//
//  The scalar version is the CORRECTNESS REFERENCE. AVX2/AVX-512 must
//  return EXACTLY the same value as scalar on every input.
// ─────────────────────────────────────────────────────────────────────────────

/// Portable scalar implementation — always correct, works on any CPU.
size_t find_next_special_scalar(const char* data, size_t len, size_t pos,
                                char delim, char quote) noexcept;

/// AVX2 implementation — 32 bytes per iteration.
/// Only call this when has_avx2() == true.
/// Compiled with -mavx2 / /arch:AVX2 flags (simd_scanner.cpp only).
size_t find_next_special_avx2(const char* data, size_t len, size_t pos,
                               char delim, char quote) noexcept;

/// AVX-512 implementation — 64 bytes per iteration.
/// Only call this when has_avx512f() == true.
/// Compiled with -mavx512f -mavx512bw / /arch:AVX512 flags.
size_t find_next_special_avx512(const char* data, size_t len, size_t pos,
                                 char delim, char quote) noexcept;

// ─────────────────────────────────────────────────────────────────────────────
//  Function pointer type + runtime selector
// ─────────────────────────────────────────────────────────────────────────────

/// Signature for any scan implementation.
using ScanFn = size_t(*)(const char*, size_t, size_t, char, char) noexcept;

/// Pick the best available implementation for this CPU.
/// Call once at startup; store the result; use it in the hot loop.
/// Priority: AVX-512 > AVX2 > scalar.
ScanFn select_best_scanner() noexcept;

/// Returns the active scanner, respecting ZEDDA_FORCE_SCALAR=1 env var.
/// Cached after first call (thread-safe via once_flag).
ScanFn get_active_scanner() noexcept;

} // namespace zedda
