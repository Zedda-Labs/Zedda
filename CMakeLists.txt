cmake_minimum_required(VERSION 3.21)

if(APPLE)
  # Force macOS deployment target to 10.14 (Mojave) to support C++17 aligned allocation
  # required by nanobind. This overrides cibuildwheel's default 10.9 target.
  set(CMAKE_OSX_DEPLOYMENT_TARGET "10.14" CACHE STRING "Minimum OS X deployment version" FORCE)
endif()

project(fasteda VERSION 0.1.0 LANGUAGES CXX C)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# ── Release flags ────────────────────────────────────────────────────────────
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

if(MSVC)
  add_compile_options(
    /O2          # Speed optimize
    /W3          # Warning level 3 (not overly pedantic)
    /wd4996      # Silence: 'fopen' unsafe — we handle file safety ourselves
    /wd4834      # Silence: discarding [[nodiscard]] return — intentional
    /D_CRT_SECURE_NO_WARNINGS
  )
else()
  add_compile_options(
    -O3 -Wall -Wextra -Wno-unused-parameter
    -D_FORTIFY_SOURCE=2        # SEC-08: buffer overflow detection
    -fstack-protector-strong   # SEC-08: stack smashing protection
    -fPIC                      # SEC-08: position-independent code (safe for shared libs)
  )
endif()

# ── Python ───────────────────────────────────────────────────────────────────
find_package(Python 3.9 REQUIRED COMPONENTS Interpreter Development.Module)
find_package(Threads REQUIRED)

# ── nanobind ─────────────────────────────────────────────────────────────────
# Try system nanobind first (installed via pip in CI)
# Fall back to submodule
find_package(nanobind CONFIG QUIET)

if(NOT nanobind_FOUND)
  message(STATUS "nanobind not found via find_package, using submodule")
  add_subdirectory(extern/nanobind)
endif()

# ── fasteda C++ sources ──────────────────────────────────────────────────────
# IMPORTANT: simd_scanner.cpp is listed here but gets its own special
# compile flags below — do NOT add -mavx2 globally.
set(FASTEDA_SOURCES
    src/core/stats_engine.cpp
    src/core/stream_reader.cpp
    src/core/mmap_reader.cpp          # NEW: memory-mapped file reader
    src/core/simd_scanner.cpp         # NEW: SIMD scanner (special flags applied below)
    src/core/profile_builder.cpp
    src/core/report_serializer.cpp
    src/core/arrow_profiler.cpp
    src/bindings/bindings.cpp
)

# ── Per-file SIMD compile flags ──────────────────────────────────────────────
# CRITICAL: These flags are applied ONLY to simd_scanner.cpp.
# Applying -mavx2 globally would generate AVX2 instructions in all files
# (including auto-vectorized loops), which would CRASH on CPUs without AVX2.
# The per-file approach means only the explicitly dispatched SIMD functions
# use AVX2/AVX-512 instructions.  Runtime dispatch (select_best_scanner)
# ensures they are only CALLED when the CPU supports them.
if(MSVC)
  # MSVC: /arch:AVX2 enables AVX2 + FMA3 intrinsics.
  # AVX-512 intrinsics are available via <immintrin.h> without a separate flag.
  set(SIMD_COMPILE_FLAGS "/arch:AVX2")
else()
  # GCC/Clang: -mavx2 enables AVX2, -mavx512f + -mavx512bw enables AVX-512
  # -mpopcnt ensures _mm_popcnt_u32 is available (used by some SIMD patterns)
  set(SIMD_COMPILE_FLAGS "-mavx2 -mavx512f -mavx512bw -mpopcnt")
  if(CMAKE_OSX_ARCHITECTURES MATCHES "arm64" OR CMAKE_SYSTEM_PROCESSOR MATCHES "arm64|aarch64")
    set(SIMD_COMPILE_FLAGS "")
  endif()
endif()

if(SIMD_COMPILE_FLAGS)
  set_source_files_properties(src/core/simd_scanner.cpp
    PROPERTIES COMPILE_FLAGS "${SIMD_COMPILE_FLAGS}"
  )
endif()

# ── nanobind Python extension ────────────────────────────────────────────────
nanobind_add_module(fasteda_core
    STABLE_ABI    # builds one wheel for all Python 3.x
    NB_STATIC     # static link nanobind runtime
    ${FASTEDA_SOURCES}
)

target_include_directories(fasteda_core PRIVATE
    ${CMAKE_SOURCE_DIR}/include
)

# ── Install ──────────────────────────────────────────────────────────────────
install(TARGETS fasteda_core
    LIBRARY DESTINATION .
)

target_link_libraries(fasteda_core PRIVATE Threads::Threads)

# ── Standalone binaries (local dev / CI testing only, not installed) ─────────
if(NOT SKBUILD)

  # ── Benchmark binary ───────────────────────────────────────────────────────
  add_executable(fasteda_bench
      src/core/stats_engine.cpp
      src/core/stream_reader.cpp
      src/core/mmap_reader.cpp
      src/core/simd_scanner.cpp
      src/core/profile_builder.cpp
      benchmarks/bench_main.cpp
  )
  target_include_directories(fasteda_bench PRIVATE ${CMAKE_SOURCE_DIR}/include)
  target_compile_definitions(fasteda_bench PRIVATE FASTEDA_STANDALONE)
  target_link_libraries(fasteda_bench PRIVATE Threads::Threads)
  # Apply SIMD flags to simd_scanner.cpp inside the bench target too
  if(SIMD_COMPILE_FLAGS)
    set_source_files_properties(src/core/simd_scanner.cpp
      TARGET_DIRECTORY fasteda_bench
      PROPERTIES COMPILE_FLAGS "${SIMD_COMPILE_FLAGS}"
    )
  endif()

  # ── SIMD parity tests ──────────────────────────────────────────────────────
  add_executable(test_simd_scanner
      src/core/simd_scanner.cpp
      tests/cpp/test_simd_scanner.cpp
  )
  target_include_directories(test_simd_scanner PRIVATE ${CMAKE_SOURCE_DIR}/include)
  if(SIMD_COMPILE_FLAGS)
    set_source_files_properties(src/core/simd_scanner.cpp
      TARGET_DIRECTORY test_simd_scanner
      PROPERTIES COMPILE_FLAGS "${SIMD_COMPILE_FLAGS}"
    )
  endif()

  # ── mmap correctness tests ─────────────────────────────────────────────────
  add_executable(test_mmap_reader
      src/core/mmap_reader.cpp
      tests/cpp/test_mmap_reader.cpp
  )
  target_include_directories(test_mmap_reader PRIVATE ${CMAKE_SOURCE_DIR}/include)

  # ── fast_float parity tests ────────────────────────────────────────────────
  add_executable(test_fast_float_parity
      tests/cpp/test_fast_float_parity.cpp
  )
  target_include_directories(test_fast_float_parity PRIVATE ${CMAKE_SOURCE_DIR}/include)

  # ── Existing tests (must still compile + pass unchanged) ──────────────────
  add_executable(test_stream_reader
      src/core/stats_engine.cpp
      src/core/stream_reader.cpp
      src/core/mmap_reader.cpp
      src/core/simd_scanner.cpp
      tests/cpp/test_stream_reader.cpp
  )
  target_include_directories(test_stream_reader PRIVATE ${CMAKE_SOURCE_DIR}/include)
  target_link_libraries(test_stream_reader PRIVATE Threads::Threads)
  if(SIMD_COMPILE_FLAGS)
    set_source_files_properties(src/core/simd_scanner.cpp
      TARGET_DIRECTORY test_stream_reader
      PROPERTIES COMPILE_FLAGS "${SIMD_COMPILE_FLAGS}"
    )
  endif()

  add_executable(test_debug_crash
      src/core/stats_engine.cpp
      src/core/stream_reader.cpp
      src/core/mmap_reader.cpp
      src/core/simd_scanner.cpp
      tests/cpp/test_debug_crash.cpp
  )
  target_include_directories(test_debug_crash PRIVATE ${CMAKE_SOURCE_DIR}/include)
  target_link_libraries(test_debug_crash PRIVATE Threads::Threads)
  if(SIMD_COMPILE_FLAGS)
    set_source_files_properties(src/core/simd_scanner.cpp
      TARGET_DIRECTORY test_debug_crash
      PROPERTIES COMPILE_FLAGS "${SIMD_COMPILE_FLAGS}"
    )
  endif()


  add_executable(test_day1
      src/core/stats_engine.cpp
      tests/cpp/test_day1.cpp
  )
  target_include_directories(test_day1 PRIVATE ${CMAKE_SOURCE_DIR}/include)
  target_link_libraries(test_day1 PRIVATE Threads::Threads)

  add_executable(test_profile_builder
      src/core/stats_engine.cpp
      src/core/stream_reader.cpp
      src/core/mmap_reader.cpp
      src/core/simd_scanner.cpp
      src/core/profile_builder.cpp
      src/core/report_serializer.cpp
      src/core/arrow_profiler.cpp
      tests/cpp/test_profile_builder.cpp
  )
  target_include_directories(test_profile_builder PRIVATE ${CMAKE_SOURCE_DIR}/include)
  target_link_libraries(test_profile_builder PRIVATE Threads::Threads)
  if(SIMD_COMPILE_FLAGS)
    set_source_files_properties(src/core/simd_scanner.cpp
      TARGET_DIRECTORY test_profile_builder
      PROPERTIES COMPILE_FLAGS "${SIMD_COMPILE_FLAGS}"
    )
  endif()

  # ── Arrow profiler tests (ISS-001, ISS-012) ────────────────────────────────
  add_executable(test_arrow_profiler
      src/core/arrow_profiler.cpp
      tests/cpp/test_arrow_profiler.cpp
  )
  target_include_directories(test_arrow_profiler PRIVATE ${CMAKE_SOURCE_DIR}/include)
  target_link_libraries(test_arrow_profiler PRIVATE Threads::Threads)

  # ── Fuzzing harnesses ──────────────────────────────────────────────────────
  option(ZEDDA_BUILD_FUZZERS "Build libFuzzer harnesses" OFF)
  if(ZEDDA_BUILD_FUZZERS)
    add_executable(fuzz_csv_parser 
      src/core/stats_engine.cpp
      src/core/stream_reader.cpp
      src/core/mmap_reader.cpp
      src/core/simd_scanner.cpp
      tests/fuzz/fuzz_csv_parser.cpp
    )
    target_include_directories(fuzz_csv_parser PRIVATE ${CMAKE_SOURCE_DIR}/include)
    target_link_libraries(fuzz_csv_parser PRIVATE Threads::Threads)
    if(SIMD_COMPILE_FLAGS)
      set_source_files_properties(src/core/simd_scanner.cpp
        TARGET_DIRECTORY fuzz_csv_parser
        PROPERTIES COMPILE_FLAGS "${SIMD_COMPILE_FLAGS}"
      )
    endif()
    target_compile_options(fuzz_csv_parser PRIVATE -fsanitize=fuzzer,address)
    target_link_options(fuzz_csv_parser PRIVATE -fsanitize=fuzzer,address)
  endif()

endif() # NOT SKBUILD