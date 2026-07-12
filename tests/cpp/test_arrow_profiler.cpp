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

int main() {
    printf("test_arrow_profiler:\n");
    test_column_count_mismatch_throws();
    test_basic_profiling_works();
    test_null_pointer_throws();
    test_multiple_same_schema_batches();
    printf("All arrow_profiler tests passed.\n");
    return 0;
}
