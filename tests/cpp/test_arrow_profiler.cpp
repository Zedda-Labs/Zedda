// ─────────────────────────────────────────────────────────────────────────────
//  test_arrow_profiler.cpp — Regression tests for ArrowProfiler
//
//  ISS-001: Column-count mismatch must throw, not OOB.
//  ISS-012: This file's existence closes the "no C++ test" finding.
// ─────────────────────────────────────────────────────────────────────────────

#include "zedda/arrow_profiler.hpp"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

// ── Helpers to build minimal Arrow C Data Interface structs ─────────────────

// Dummy release callback (no-op, we manage memory manually in tests)
static void dummy_release_schema(struct ArrowSchema* schema) {
    (void)schema;
}
static void dummy_release_array(struct ArrowArray* array) {
    (void)array;
}

// Build a minimal ArrowSchema with N int32 children
struct TestSchema {
    ArrowSchema root;
    std::vector<ArrowSchema> children;
    std::vector<ArrowSchema*> child_ptrs;
    std::vector<std::string> child_names;

    TestSchema(int n) : children(n), child_names(n) {
        for (int i = 0; i < n; ++i) {
            child_names[i] = "col" + std::to_string(i);
            children[i].format = "i";  // int32
            children[i].name = child_names[i].c_str();
            children[i].metadata = nullptr;
            children[i].flags = 0;
            children[i].n_children = 0;
            children[i].children = nullptr;
            children[i].dictionary = nullptr;
            children[i].release = dummy_release_schema;
            children[i].private_data = nullptr;
        }
        child_ptrs.resize(n);
        for (int i = 0; i < n; ++i) {
            child_ptrs[i] = &children[i];
        }

        root.format = "+s";  // struct
        root.name = "root";
        root.metadata = nullptr;
        root.flags = 0;
        root.n_children = n;
        root.children = child_ptrs.data();
        root.dictionary = nullptr;
        root.release = dummy_release_schema;
        root.private_data = nullptr;
    }
};

// Build a minimal ArrowArray with N int32 children, each with `num_rows` rows
struct TestArray {
    ArrowArray root;
    std::vector<ArrowArray> children;
    std::vector<ArrowArray*> child_ptrs;
    std::vector<std::vector<int32_t>> data_buffers;
    std::vector<std::vector<const void*>> buffer_ptrs;

    TestArray(int n, int64_t num_rows) : children(n), data_buffers(n), buffer_ptrs(n) {
        for (int i = 0; i < n; ++i) {
            data_buffers[i].resize(num_rows, i + 1);  // fill with column index + 1
            buffer_ptrs[i] = { nullptr, data_buffers[i].data() };

            children[i].length = num_rows;
            children[i].null_count = 0;
            children[i].offset = 0;
            children[i].n_buffers = 2;
            children[i].n_children = 0;
            children[i].buffers = buffer_ptrs[i].data();
            children[i].children = nullptr;
            children[i].dictionary = nullptr;
            children[i].release = dummy_release_array;
            children[i].private_data = nullptr;
        }
        child_ptrs.resize(n);
        for (int i = 0; i < n; ++i) {
            child_ptrs[i] = &children[i];
        }

        root.length = num_rows;
        root.null_count = 0;
        root.offset = 0;
        root.n_buffers = 1;
        root.n_children = n;
        const void* null_buf = nullptr;
        // We need a stable pointer for buffers
        root.buffers = &null_buf;  // will be overwritten below
        root.children = child_ptrs.data();
        root.dictionary = nullptr;
        root.release = dummy_release_array;
        root.private_data = nullptr;
    }
};

// ── Tests ───────────────────────────────────────────────────────────────────

// ISS-001: Consuming a batch with mismatched column count must throw
static void test_column_count_mismatch_throws() {
    printf("  test_column_count_mismatch_throws ... ");

    zedda::ArrowProfiler profiler("test.csv", 10);

    // First batch: 3 columns — should succeed
    TestSchema schema3(3);
    TestArray array3(3, 5);
    profiler.consume_batch(
        reinterpret_cast<uintptr_t>(&schema3.root),
        reinterpret_cast<uintptr_t>(&array3.root)
    );

    // Second batch: 5 columns — should throw runtime_error
    TestSchema schema5(5);
    TestArray array5(5, 5);
    bool threw = false;
    try {
        profiler.consume_batch(
            reinterpret_cast<uintptr_t>(&schema5.root),
            reinterpret_cast<uintptr_t>(&array5.root)
        );
    } catch (const std::runtime_error& e) {
        threw = true;
        // Verify error message mentions the expected/actual counts
        std::string msg = e.what();
        assert(msg.find("3") != std::string::npos);
        assert(msg.find("5") != std::string::npos);
    }
    assert(threw && "Expected runtime_error for column count mismatch");

    printf("PASS\n");
}

// ISS-001: Array with different n_children than Schema must throw (Issue 80)
static void test_mismatched_schema_and_array_throws() {
    printf("  test_mismatched_schema_and_array_throws ... ");

    zedda::ArrowProfiler profiler("test.csv", 10);
    
    // First batch: 3 columns (matches)
    TestSchema schema3(3);
    TestArray array3(3, 5);
    profiler.consume_batch(
        reinterpret_cast<uintptr_t>(&schema3.root),
        reinterpret_cast<uintptr_t>(&array3.root)
    );

    // Second batch: schema says 3, but array has 4 columns (too many)
    TestArray array4(4, 5);
    bool threw1 = false;
    try {
        profiler.consume_batch(
            reinterpret_cast<uintptr_t>(&schema3.root),
            reinterpret_cast<uintptr_t>(&array4.root)
        );
    } catch (const std::runtime_error&) { threw1 = true; }
    assert(threw1 && "Expected runtime_error for array having too many columns");

    // Third batch: schema says 3, but array has 2 columns (too few)
    TestArray array2(2, 5);
    bool threw2 = false;
    try {
        profiler.consume_batch(
            reinterpret_cast<uintptr_t>(&schema3.root),
            reinterpret_cast<uintptr_t>(&array2.root)
        );
    } catch (const std::runtime_error&) { threw2 = true; }
    assert(threw2 && "Expected runtime_error for array having too few columns");

    printf("PASS\n");
}

// Basic smoke test: consume a valid batch and finalize
static void test_basic_profiling_works() {
    printf("  test_basic_profiling_works ... ");

    zedda::ArrowProfiler profiler("test.csv", 5);

    TestSchema schema(2);
    TestArray array(2, 5);
    profiler.consume_batch(
        reinterpret_cast<uintptr_t>(&schema.root),
        reinterpret_cast<uintptr_t>(&array.root)
    );

    auto profile = profiler.finalize();
    assert(profile.num_cols == 2);
    assert(profile.columns.size() == 2);

    printf("PASS\n");
}

// Null pointer validation
static void test_null_pointer_throws() {
    printf("  test_null_pointer_throws ... ");

    zedda::ArrowProfiler profiler("test.csv", 5);

    bool threw = false;
    try {
        profiler.consume_batch(0, 0);
    } catch (const std::runtime_error&) {
        threw = true;
    }
    assert(threw && "Expected runtime_error for null pointers");

    printf("PASS\n");
}

// Multiple valid batches with same schema should succeed
static void test_multiple_same_schema_batches() {
    printf("  test_multiple_same_schema_batches ... ");

    zedda::ArrowProfiler profiler("test.csv", 20);

    TestSchema schema(3);
    TestArray array1(3, 5);
    TestArray array2(3, 5);

    profiler.consume_batch(
        reinterpret_cast<uintptr_t>(&schema.root),
        reinterpret_cast<uintptr_t>(&array1.root)
    );
    profiler.consume_batch(
        reinterpret_cast<uintptr_t>(&schema.root),
        reinterpret_cast<uintptr_t>(&array2.root)
    );

    auto profile = profiler.finalize();
    assert(profile.num_cols == 3);

    printf("PASS\n");
}

static void test_genuine_null_remains_null() {
    printf("  test_genuine_null_remains_null ... ");

    zedda::ArrowProfiler profiler("test.csv", 2);
    TestSchema schema(1);
    TestArray array(1, 2);
    uint8_t validity[] = {0x01};  // first row valid, second row null
    array.buffer_ptrs[0][0] = validity;
    array.children[0].null_count = 1;
    profiler.consume_batch(
        reinterpret_cast<uintptr_t>(&schema.root),
        reinterpret_cast<uintptr_t>(&array.root)
    );

    auto profile = profiler.finalize();
    assert(profile.columns[0].null_count == 1);
    assert(profile.columns[0].non_null_count == 1);
    assert(profile.columns[0].unsupported_types.empty());

    printf("PASS\n");
}

static void test_unsupported_format_is_reported() {
    printf("  test_unsupported_format_is_reported ... ");

    for (const char* format : {"+m", "+w"}) {
        zedda::ArrowProfiler profiler("test.arrow", 5);
        TestSchema schema(1);
        schema.children[0].format = format;  // map and union-like unsupported formats
        TestArray array(1, 5);
        profiler.consume_batch(
            reinterpret_cast<uintptr_t>(&schema.root),
            reinterpret_cast<uintptr_t>(&array.root)
        );

        auto profile = profiler.finalize();
        assert(profile.columns[0].unsupported_types.size() == 1);
        assert(profile.columns[0].unsupported_types[0] == format);
        assert(profile.columns[0].null_count == 5);
    }

    printf("PASS\n");
}

static void test_large_integer_identity_is_exact() {
    printf("  test_large_integer_identity_is_exact ... ");

    zedda::ColumnAccumulator accumulator;
    accumulator.type = zedda::ColumnType::INTEGER;
    accumulator.update_int64(9007199254740992LL);
    accumulator.update_int64(9007199254740993LL);
    accumulator.update_int64(9007199254740994LL);
    accumulator.update_uint64(9007199254740992ULL);
    accumulator.update_uint64(9007199254740993ULL);
    accumulator.update_uint64(18446744073709551615ULL);
    accumulator.finalize();

    assert(accumulator.exact_integer_values.size() == 6);
    assert(!accumulator.exact_integer_overflowed);

    printf("PASS\n");
}

int main() {
    printf("test_arrow_profiler:\n");
    test_column_count_mismatch_throws();
    test_mismatched_schema_and_array_throws();
    test_basic_profiling_works();
    test_null_pointer_throws();
    test_genuine_null_remains_null();
    test_multiple_same_schema_batches();
    test_unsupported_format_is_reported();
    test_large_integer_identity_is_exact();
    printf("All arrow_profiler tests passed.\n");
    return 0;
}
