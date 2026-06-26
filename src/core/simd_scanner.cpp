// ─────────────────────────────────────────────────────────────────────────────
//  zedda::simd_scanner — implementation
//
//  COMPILE FLAGS (applied per-file in CMakeLists.txt, NOT globally):
//    GCC/Clang : -mavx2 -mavx512f -mavx512bw
//    MSVC      : /arch:AVX2  (MSVC does not need a separate AVX-512 flag;
//                             intrinsics are available with /arch:AVX2 + headers)
//
//  WHY PER-FILE FLAGS?
//  If we applied -mavx2 globally, the compiler would emit AVX2 instructions
//  in every .cpp (including auto-vectorized loops in profile_builder.cpp).
//  That would crash on CPUs without AVX2.  Restricting to this one file means
//  only the functions below use AVX2 instructions — and they are only CALLED
//  at runtime when has_avx2() returns true.
//
//  WINDOWS NOTE:
//  MSVC uses __cpuid / __cpuidex for CPU detection (no __builtin_cpu_supports).
//  The intrinsic headers are <intrin.h> on MSVC, <immintrin.h> on GCC/Clang.
// ─────────────────────────────────────────────────────────────────────────────

#include "zedda/simd_scanner.hpp"

#include <cstdlib>   // getenv
#include <mutex>     // once_flag
#include <cstring>   // memset

// ── Intrinsic headers ─────────────────────────────────────────────────────────
#if defined(_MSC_VER)
#  include <intrin.h>          // __cpuid, __cpuidex
#  include <immintrin.h>       // AVX2 / AVX-512 intrinsics
#elif defined(__GNUC__) || defined(__clang__)
#  include <immintrin.h>       // AVX2 / AVX-512
#  include <cpuid.h>           // __get_cpuid_count (fallback)
#endif

namespace zedda {

// ─────────────────────────────────────────────────────────────────────────────
//  CPU Feature Detection
//  GCC/Clang: __builtin_cpu_supports("avx2") — simplest, handles XSAVE check.
//  MSVC:      manual __cpuidex read of CPUID leaf 7, subleaf 0.
// ─────────────────────────────────────────────────────────────────────────────

bool has_avx2() noexcept {
#if defined(__GNUC__) || defined(__clang__)
    return __builtin_cpu_supports("avx2");
#elif defined(_MSC_VER)
    // CPUID leaf 7, subleaf 0 — EBX bit 5 = AVX2
    int info[4] = {};
    __cpuidex(info, 7, 0);
    return (info[1] & (1 << 5)) != 0;
#else
    return false;  // unknown compiler — safe fallback
#endif
}

bool has_avx512f() noexcept {
#if defined(__GNUC__) || defined(__clang__)
    // AVX-512F: leaf 7.0 EBX bit 16; AVX-512BW: leaf 7.0 EBX bit 30
    // We need both for byte-level 512-bit comparisons
    return __builtin_cpu_supports("avx512f") && __builtin_cpu_supports("avx512bw");
#elif defined(_MSC_VER)
    int info[4] = {};
    __cpuidex(info, 7, 0);
    bool f   = (info[1] & (1 << 16)) != 0;  // AVX-512F
    bool bw  = (info[1] & (1 << 30)) != 0;  // AVX-512BW
    return f && bw;
#else
    return false;
#endif
}

// ─────────────────────────────────────────────────────────────────────────────
//  SCALAR implementation — the correctness reference
//
//  Simple byte-by-byte loop.  Checks for delimiter, quote_char, '\n', '\r'.
//  ALL other implementations must return EXACTLY the same index as this.
// ─────────────────────────────────────────────────────────────────────────────

size_t find_next_special_scalar(const char* data, size_t len, size_t pos,
                                char delim, char quote) noexcept {
    while (pos < len) {
        char c = data[pos];
        if (c == delim || c == quote || c == '\n' || c == '\r') {
            return pos;
        }
        ++pos;
    }
    return len;  // no match
}

// ─────────────────────────────────────────────────────────────────────────────
//  AVX2 implementation — 32 bytes per loop iteration
//
//  Technique (simdjson / simdcsv standard approach):
//    1. Load 32 bytes: _mm256_loadu_si256
//    2. Compare each byte against delim, quote, '\n', '\r' simultaneously
//    3. OR all comparison results → mask of any match
//    4. _mm256_movemask_epi8 → 32-bit integer (bit i = byte i had a match)
//    5. If mask != 0: first match is at pos + __builtin_ctz(mask)
//    6. If mask == 0: advance pos by 32, repeat
//    Remainder (< 32 bytes): scalar fallback
//
//  CRITICAL: _mm256_loadu_si256 is unaligned — safe on any 32-byte chunk
//  even if the buffer start is not 32-byte aligned (which it usually isn't).
// ─────────────────────────────────────────────────────────────────────────────

#if defined(__AVX2__) || (defined(_MSC_VER) && defined(__AVX2__))

size_t find_next_special_avx2(const char* data, size_t len, size_t pos,
                               char delim, char quote) noexcept {
    // Broadcast the special chars to all 32 lanes of a 256-bit register
    const __m256i v_delim  = _mm256_set1_epi8(delim);
    const __m256i v_quote  = _mm256_set1_epi8(quote);
    const __m256i v_newline= _mm256_set1_epi8('\n');
    const __m256i v_cr     = _mm256_set1_epi8('\r');

    // Process 32 bytes per iteration
    while (pos + 32 <= len) {
        // Prefetch 4 cache lines ahead for next iterations (only if within bounds)
        if (pos + 256 < len) {
#if defined(_MSC_VER)
            _mm_prefetch(reinterpret_cast<const char*>(data + pos + 256), _MM_HINT_T0);
#elif defined(__GNUC__) || defined(__clang__)
            // locality 3 = high temporal locality (fetch into all cache levels, matches _MM_HINT_T0)
            __builtin_prefetch(data + pos + 256, 0, 3);
#endif
        }

        // Load 32 bytes — unaligned load is fine (slight perf penalty vs
        // aligned, but alignment of arbitrary mmap'd file data is unknown)
        __m256i chunk = _mm256_loadu_si256(
            reinterpret_cast<const __m256i*>(data + pos)
        );

        // Compare against each special byte — result is 0xFF where match, 0x00 elsewhere
        __m256i m_delim   = _mm256_cmpeq_epi8(chunk, v_delim);
        __m256i m_quote   = _mm256_cmpeq_epi8(chunk, v_quote);
        __m256i m_newline = _mm256_cmpeq_epi8(chunk, v_newline);
        __m256i m_cr      = _mm256_cmpeq_epi8(chunk, v_cr);

        // OR all four: any byte that is a special char sets its bit
        __m256i m_any = _mm256_or_si256(
            _mm256_or_si256(m_delim, m_quote),
            _mm256_or_si256(m_newline, m_cr)
        );

        // Collapse: one bit per byte — bit i is 1 if data[pos+i] was a match
        int mask = _mm256_movemask_epi8(m_any);

        if (mask != 0) {
            // __builtin_ctz counts trailing zeros = index of lowest set bit
            // = byte offset of first match within this 32-byte chunk
#if defined(_MSC_VER)
            unsigned long idx;
            _BitScanForward(&idx, static_cast<unsigned long>(mask));
            return pos + idx;
#else
            return pos + static_cast<size_t>(__builtin_ctz(static_cast<unsigned>(mask)));
#endif
        }

        pos += 32;
    }

    // Handle remainder (< 32 bytes) with scalar fallback
    return find_next_special_scalar(data, len, pos, delim, quote);
}

#else

// Compiled on a system where AVX2 is not available to the compiler —
// provide a scalar stub.  This should never be called at runtime because
// has_avx2() would return false, but it prevents linker errors.
size_t find_next_special_avx2(const char* data, size_t len, size_t pos,
                               char delim, char quote) noexcept {
    return find_next_special_scalar(data, len, pos, delim, quote);
}

#endif // __AVX2__

// ─────────────────────────────────────────────────────────────────────────────
//  AVX-512 implementation — 64 bytes per loop iteration
//
//  Technique:
//    _mm512_loadu_si512  — load 64 bytes
//    _mm512_cmpeq_epi8_mask — compare + produce 64-bit mask directly (no movemask!)
//    OR the four 64-bit masks
//    _tzcnt_u64  — first match position
//
//  AVX-512 advantage vs AVX2:
//    1. Processes 2x bytes per instruction
//    2. _cmpeq_epi8_mask produces a native k-register bitmask —
//       no need for _mm512_movemask_epi8 (which doesn't exist anyway)
//    3. On Skylake-X / Ice Lake: can execute 2 AVX-512 ops per cycle
//       → theoretical 128 bytes/cycle throughput
//
//  REALITY CHECK: 6.3M rows × 31 cols × ~15 bytes avg field =
//  ~2.9 GB of data.  At 50 GB/s memory bandwidth (DDR5), pure bandwidth
//  limit is ~58ms.  AVX-512 target of 2.5s has plenty of headroom;
//  real bottleneck becomes memory latency and the Welford update loop.
// ─────────────────────────────────────────────────────────────────────────────

#if defined(__AVX512F__) && defined(__AVX512BW__)

size_t find_next_special_avx512(const char* data, size_t len, size_t pos,
                                 char delim, char quote) noexcept {
    const __m512i v_delim   = _mm512_set1_epi8(delim);
    const __m512i v_quote   = _mm512_set1_epi8(quote);
    const __m512i v_newline = _mm512_set1_epi8('\n');
    const __m512i v_cr      = _mm512_set1_epi8('\r');

    while (pos + 64 <= len) {
        // Prefetch 8 cache lines ahead (only if within bounds)
        if (pos + 512 < len) {
#if defined(_MSC_VER)
            _mm_prefetch(reinterpret_cast<const char*>(data + pos + 512), _MM_HINT_T0);
#elif defined(__GNUC__) || defined(__clang__)
            // locality 3 = high temporal locality
            __builtin_prefetch(data + pos + 512, 0, 3);
#endif
        }

        __m512i chunk = _mm512_loadu_si512(
            reinterpret_cast<const __m512i*>(data + pos)
        );

        // Each _mm512_cmpeq_epi8_mask returns a 64-bit integer mask directly
        __mmask64 m_delim   = _mm512_cmpeq_epi8_mask(chunk, v_delim);
        __mmask64 m_quote   = _mm512_cmpeq_epi8_mask(chunk, v_quote);
        __mmask64 m_newline = _mm512_cmpeq_epi8_mask(chunk, v_newline);
        __mmask64 m_cr      = _mm512_cmpeq_epi8_mask(chunk, v_cr);

        __mmask64 mask = m_delim | m_quote | m_newline | m_cr;

        if (mask != 0) {
#if defined(_MSC_VER)
            unsigned long idx;
            _BitScanForward64(&idx, static_cast<unsigned __int64>(mask));
            return pos + idx;
#else
            return pos + static_cast<size_t>(__builtin_ctzll(static_cast<unsigned long long>(mask)));
#endif
        }

        pos += 64;
    }

    // Handle remainder: try AVX2 first (handles 32-byte chunks of remainder),
    // then scalar for the final < 32 bytes.
    // This is safe because find_next_special_avx2 itself falls to scalar.
    return find_next_special_avx2(data, len, pos, delim, quote);
}

#else

size_t find_next_special_avx512(const char* data, size_t len, size_t pos,
                                 char delim, char quote) noexcept {
    // Stub: AVX-512 not available at compile time, fall through to AVX2/scalar
    return find_next_special_avx2(data, len, pos, delim, quote);
}

#endif // __AVX512F__ && __AVX512BW__

// ─────────────────────────────────────────────────────────────────────────────
//  Runtime dispatch — select_best_scanner() and get_active_scanner()
// ─────────────────────────────────────────────────────────────────────────────

ScanFn select_best_scanner() noexcept {
    if (has_avx512f()) return find_next_special_avx512;
    if (has_avx2())    return find_next_special_avx2;
    return find_next_special_scalar;
}

ScanFn get_active_scanner() noexcept {
    // Read ZEDDA_FORCE_SCALAR env var to allow scalar-only testing.
    // We do not cache this result statically so that benchmarking tools
    // can toggle the environment variable between runs.
    const char* force = std::getenv("ZEDDA_FORCE_SCALAR");
    if (force && force[0] == '1') {
        return find_next_special_scalar;
    }
    return select_best_scanner();
}

} // namespace zedda
