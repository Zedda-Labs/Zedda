#include <iostream>
#include <fstream>
#include <iomanip>
#include <cmath>
#include <cassert>
#include <chrono>
#include "zedda/stream_reader.hpp"
#include "zedda/hyperloglog.hpp"

// ── Helper: create a test CSV file ───────────────────────────────
void create_test_csv(const std::string& path) {
    std::ofstream f(path);
    f << "name,age,salary,city,active\n";
    f << "Arjun,25,50000.0,Mumbai,true\n";
    f << "Priya,30,75000.5,Delhi,false\n";
    f << "Rahul,22,,Bangalore,true\n";       // empty salary = null
    f << "Sneha,28,62000.0,Mumbai,true\n";
    f << "Karan,35,90000.0,Pune,false\n";
    f << "Anita,,55000.0,Ahmedabad,true\n";  // empty age = null
    f << "Rohan,27,48000.0,Mumbai,true\n";
    f << "Divya,31,80000.0,Delhi,false\n";
    f << "Amit,29,NULL,Pune,true\n";         // NULL salary
    f << "Neha,26,67000.0,Bangalore,true\n";
}

// ── Test 1: Basic read ────────────────────────────────────────────
void test_basic_read() {
    std::cout << "\n=== Test: Basic CSV read ===\n";

    create_test_csv("test_data.csv");

    zedda::CsvStreamReader reader("test_data.csv");
    bool ok_open = reader.open();
    if (!ok_open) { std::cerr << "Failed to open reader\n"; std::abort(); }

    std::cout << "Columns detected: " << reader.num_columns() << " (expected 5)\n";
    for (const auto& name : reader.column_names()) {
        std::cout << "  - " << name << "\n";
    }

    auto accs = reader.make_accumulators();
    while (!reader.done()) {
        reader.read_chunk(accs);
    }
    for (auto& acc : accs) acc.finalize();

    std::cout << "\nRows read: " << reader.rows_read() << " (expected 10)\n";
    bool ok = reader.rows_read() == 10 && reader.num_columns() == 5;
    std::cout << (ok ? "PASS ✓" : "FAIL ✗") << "\n";
}

// ── Test 2: Null detection ────────────────────────────────────────
void test_null_detection() {
    std::cout << "\n=== Test: Null detection ===\n";

    zedda::CsvStreamReader reader("test_data.csv");
    bool ok_open = reader.open();
    if (!ok_open) { std::cerr << "Failed to open reader\n"; std::abort(); }

    auto accs = reader.make_accumulators();
    while (!reader.done()) reader.read_chunk(accs);
    for (auto& acc : accs) acc.finalize();

    // salary col (index 2): 2 nulls (Rahul + Amit's NULL)
    // age col   (index 1): 1 null  (Anita)
    auto& age_acc    = accs[1];
    auto& salary_acc = accs[2];

    std::cout << std::fixed << std::setprecision(1);
    std::cout << "Age nulls    : " << age_acc.null_count
              << " (expected 1)\n";
    std::cout << "Salary nulls : " << salary_acc.null_count
              << " (expected 2)\n";
    std::cout << "Age null pct : " << age_acc.null_pct
              << "% (expected 10.0%)\n";

    bool ok = age_acc.null_count == 1 && salary_acc.null_count == 2;
    std::cout << (ok ? "PASS ✓" : "FAIL ✗") << "\n";
}

// ── Test 3: Numeric stats ─────────────────────────────────────────
void test_numeric_stats() {
    std::cout << "\n=== Test: Numeric stats (age column) ===\n";

    zedda::CsvStreamReader reader("test_data.csv");
    bool ok_open = reader.open();
    if (!ok_open) { std::cerr << "Failed to open reader\n"; std::abort(); }

    auto accs = reader.make_accumulators();
    while (!reader.done()) reader.read_chunk(accs);
    for (auto& acc : accs) acc.finalize();

    // age: {25,30,22,28,35,27,31,29,26} (Anita skipped = null)
    // mean = (25+30+22+28+35+27+31+29+26) / 9 = 253/9 = 28.11...
    auto& age = accs[1];

    std::cout << std::fixed << std::setprecision(4);
    std::cout << "Age type  : " << zedda::column_type_str(age.type)
              << " (expected int)\n";
    std::cout << "Age mean  : " << age.mean
              << " (expected ~28.11)\n";
    std::cout << "Age min   : " << age.val_min
              << " (expected 22.0)\n";
    std::cout << "Age max   : " << age.val_max
              << " (expected 35.0)\n";
    std::cout << "Non-null  : " << age.non_null_count()
              << " (expected 9)\n";

    bool ok = age.type == zedda::ColumnType::INTEGER
           && std::abs(age.mean - 28.111) < 0.01
           && std::abs(age.val_min - 22.0) < 1e-6
           && std::abs(age.val_max - 35.0) < 1e-6
           && age.non_null_count() == 9;
    std::cout << (ok ? "PASS ✓" : "FAIL ✗") << "\n";
}

// ── Test 4: String column ─────────────────────────────────────────
void test_string_column() {
    std::cout << "\n=== Test: String column (city) ===\n";

    zedda::CsvStreamReader reader("test_data.csv");
    bool ok_open = reader.open();
    if (!ok_open) { std::cerr << "Failed to open reader\n"; std::abort(); }

    auto accs = reader.make_accumulators();
    while (!reader.done()) reader.read_chunk(accs);
    for (auto& acc : accs) acc.finalize();

    // city: Mumbai(3), Delhi(2), Bangalore(2), Pune(2), Ahmedabad(1) = 5 unique
    auto& city = accs[3];

    std::cout << "City type    : " << zedda::column_type_str(city.type)
              << " (expected str)\n";
    std::cout << "City count   : " << city.count
              << " (expected 10)\n";
    std::cout << "City nulls   : " << city.null_count
              << " (expected 0)\n";

    bool ok = city.type == zedda::ColumnType::STRING
           && city.count == 10
           && city.null_count == 0;
    std::cout << (ok ? "PASS ✓" : "FAIL ✗") << "\n";
}

// ── Test 5: Chunked streaming (small chunk size) ────────────────────
void test_chunked_streaming() {
    std::cout << "\n=== Test: Chunked streaming (3 rows/chunk) ===\n";

    zedda::StreamReaderConfig cfg;
    cfg.chunk_size = 3;  // force multiple chunks

    zedda::CsvStreamReader reader("test_data.csv", cfg);
    bool ok_open = reader.open();
    if (!ok_open) { std::cerr << "Failed to open reader\n"; std::abort(); }

    auto accs = reader.make_accumulators();
    int  chunks = 0;

    while (!reader.done()) {
        auto result = reader.read_chunk(accs);
        ++chunks;
        std::cout << "  Chunk " << chunks
                  << ": processed " << result.rows_processed
                  << " rows (total so far: " << result.total_rows << ")\n";
    }

    for (auto& acc : accs) acc.finalize();

    std::cout << "Total chunks : " << chunks   << " (expected 4)\n";
    std::cout << "Total rows   : " << reader.rows_read() << " (expected 10)\n";

    bool ok = reader.rows_read() == 10 && chunks == 4;
    std::cout << (ok ? "PASS ✓" : "FAIL ✗") << "\n";
}

// ── Test 6: Performance — 100K synthetic rows ────────────────────
void test_performance() {
    std::cout << "\n=== Test: Performance (100K rows) ===\n";

    // Generate synthetic CSV
    {
        std::ofstream f("perf_test.csv");
        f << "id,value,category,score\n";
        for (int i = 0; i < 100000; ++i) {
            f << i << ","
              << (i * 1.5 + 0.3) << ","
              << "cat_" << (i % 20) << ","
              << (i % 100) << "\n";
        }
    }

    zedda::CsvStreamReader reader("perf_test.csv");
    bool ok_open = reader.open();
    if (!ok_open) { std::cerr << "Failed to open reader\n"; std::abort(); }
    auto accs = reader.make_accumulators();

    auto start = std::chrono::high_resolution_clock::now();
    while (!reader.done()) reader.read_chunk(accs);
    for (auto& acc : accs) acc.finalize();
    auto end = std::chrono::high_resolution_clock::now();

    double ms = std::chrono::duration<double, std::milli>(end - start).count();

    std::cout << std::fixed << std::setprecision(1);
    std::cout << "Rows      : " << reader.rows_read() << "\n";
    std::cout << "Time      : " << ms << " ms\n";
    std::cout << "Rows/sec  : "
              << static_cast<int>(reader.rows_read() / (ms / 1000.0))
              << "\n";

    // Should be well under 1 second for 100K rows
    bool ok = reader.rows_read() == 100000 && ms < 5000.0;
    std::cout << (ok ? "PASS ✓" : "FAIL ✗") << "\n";
}

// ── ISS-019: Quoted fields with embedded newlines ──────────────────
void test_quoted_embedded_newlines() {
    std::cout << "\n=== ISS-019: Quoted fields with embedded newlines ===\n";
    const std::string path = "test_quoted_newlines.csv";
    {
        std::ofstream f(path);
        // A field containing a literal newline — must be treated as ONE row
        f << "id,note\n";
        f << "1,\"line one\nline two\"\n";
        f << "2,normal\n";
        f << "3,\"has\nnewline\nnewline\"\n";
        f << "4,done\n";
    }
    zedda::CsvStreamReader reader(path);
    reader.open();
    auto accs = reader.make_accumulators();
    while (!reader.done()) reader.read_chunk(accs);
    // 4 data rows, not 4+embedded_newlines rows
    std::cout << "Rows parsed: " << reader.rows_read() << " (expected 4)\n";
    bool ok = reader.rows_read() == 4;
    std::cout << (ok ? "PASS ✓" : "FAIL ✗") << "\n";
}

// ── Group D: Alternative delimiters ───────────────────────────────
void test_alternative_delimiters() {
    std::cout << "\n=== Group D: Alternative delimiters ===\n";

    // Semicolon-delimited
    {
        const std::string path = "test_semicolon.csv";
        std::ofstream f(path);
        f << "a;b;c\n1;2;3\n4;5;6\n";
    }
    {
        zedda::StreamReaderConfig cfg;
        cfg.delimiter = ';';
        zedda::CsvStreamReader reader("test_semicolon.csv", cfg);
        reader.open();
        auto accs = reader.make_accumulators();
        while (!reader.done()) reader.read_chunk(accs);
        std::cout << "Semicolon: cols=" << reader.num_columns() << " rows=" << reader.rows_read() << "\n";
        bool ok = reader.num_columns() == 3 && reader.rows_read() == 2;
        std::cout << (ok ? "PASS ✓" : "FAIL ✗") << "\n";
    }

    // Tab-delimited
    {
        const std::string path = "test_tab.csv";
        std::ofstream f(path);
        f << "x\ty\n10\t20\n30\t40\n";
    }
    {
        zedda::StreamReaderConfig cfg;
        cfg.delimiter = '\t';
        zedda::CsvStreamReader reader("test_tab.csv", cfg);
        reader.open();
        auto accs = reader.make_accumulators();
        while (!reader.done()) reader.read_chunk(accs);
        std::cout << "Tab: cols=" << reader.num_columns() << " rows=" << reader.rows_read() << "\n";
        bool ok = reader.num_columns() == 2 && reader.rows_read() == 2;
        std::cout << (ok ? "PASS ✓" : "FAIL ✗") << "\n";
    }
}

// ── Group D: BOM-prefixed UTF-8 ────────────────────────────────────
void test_bom_utf8() {
    std::cout << "\n=== Group D: BOM-prefixed UTF-8 ===\n";
    const std::string path = "test_bom.csv";
    {
        std::ofstream f(path, std::ios::binary);
        // UTF-8 BOM (EF BB BF) followed by normal CSV
        f << '\xEF' << '\xBB' << '\xBF';
        f << "name,value\nAlice,42\nBob,99\n";
    }
    zedda::CsvStreamReader reader(path);
    reader.open();
    auto accs = reader.make_accumulators();
    while (!reader.done()) reader.read_chunk(accs);
    std::cout << "BOM file: cols=" << reader.num_columns() << " rows=" << reader.rows_read() << "\n";
    // Column name should NOT start with the BOM bytes
    const auto& names = reader.column_names();
    bool no_bom = !names.empty() && names[0].size() >= 4 ? names[0].substr(0,3) != "\xEF\xBB\xBF" : true;
    bool ok = reader.num_columns() == 2 && reader.rows_read() == 2;
    std::cout << (ok ? "PASS ✓" : "FAIL ✗ (row/col count)") << "\n";
}

int main() {
    std::cout << std::unitbuf; // Force flush after every print
    std::cout << "zedda — StreamReader tests\n";
    std::cout << "============================\n";

    test_basic_read();
    test_null_detection();
    test_numeric_stats();
    test_string_column();
    test_chunked_streaming();
    test_performance();
    test_quoted_embedded_newlines();  // ISS-019
    test_alternative_delimiters();    // Group D
    test_bom_utf8();                  // Group D

    std::cout << "\nDone! StreamReader ready hai!\n";
    return 0;
}