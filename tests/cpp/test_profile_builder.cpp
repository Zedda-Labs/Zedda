#include <iostream>
#include <fstream>
#include <iomanip>
#include <cmath>
#include <cassert>
#include "zedda/profile_builder.hpp"

// ── Create test CSV ───────────────────────────────────────────────
void create_csv(const std::string& path) {
    std::ofstream f(path);
    f << "name,age,salary,city,active\n";
    f << "Arjun,25,50000.0,Mumbai,true\n";
    f << "Priya,30,75000.5,Delhi,false\n";
    f << "Rahul,22,,Bangalore,true\n";
    f << "Sneha,28,62000.0,Mumbai,true\n";
    f << "Karan,35,90000.0,Pune,false\n";
    f << "Anita,,55000.0,Ahmedabad,true\n";
    f << "Rohan,27,48000.0,Mumbai,true\n";
    f << "Divya,31,80000.0,Delhi,false\n";
    f << "Amit,29,NULL,Pune,true\n";
    f << "Neha,26,67000.0,Bangalore,true\n";
}

void test_full_profile() {
    std::cout << "\n=== Test: Full pipeline ===\n";
    create_csv("profile_test.csv");

    zedda::ProfileBuilder builder("profile_test.csv");
    builder.set_progress([](int64_t rows) {
        std::cout << "\r  Scanning... " << rows << " rows";
    });

    auto profile = builder.build();

    std::cout << std::fixed << std::setprecision(2);
    std::cout << "\n--- Dataset Summary ---\n";
    std::cout << "File       : " << profile.file_name    << "\n";
    std::cout << "Rows       : " << profile.num_rows     << " (expected 10)\n";
    std::cout << "Cols       : " << profile.num_cols     << " (expected 5)\n";
    std::cout << "Numeric    : " << profile.num_numeric  << " (expected 2)\n";
    std::cout << "String     : " << profile.num_string   << " (expected 3)\n";
    std::cout << "Null cells : " << profile.total_null_cells << " (expected 3)\n";
    std::cout << "Null pct   : " << profile.overall_null_pct << "% (expected 6.0%)\n";
    std::cout << "Scan time  : " << profile.scan_time_ms << " ms\n";

    std::cout << "\n--- Column Profiles ---\n";
    for (const auto& col : profile.columns) {
        std::cout << "\n[" << col.name << "] type=" << col.type_str
                  << " nulls=" << col.null_count
                  << " (" << col.null_pct << "%)"
                  << " unique~" << col.unique_approx;

        if (col.type_str == "int" || col.type_str == "float") {
            std::cout << "\n  mean=" << col.mean
                      << " stddev=" << col.stddev
                      << " min=" << col.val_min
                      << " max=" << col.val_max;
        }
        if (col.has_high_nulls)        std::cout << " [HIGH NULLS]";
        if (col.is_constant)           std::cout << " [CONSTANT]";
        if (col.is_high_cardinality)   std::cout << " [HIGH CARD]";
        std::cout << "\n";
    }

    bool ok = profile.num_rows == 10
           && profile.num_cols == 5
           && profile.total_null_cells == 3;
    std::cout << "\n" << (ok ? "PASS ✓" : "FAIL ✗") << "\n";
}

void test_performance_profile() {
    std::cout << "\n=== Test: Performance (500K rows) ===\n";

    {
        std::ofstream f("big_test.csv");
        f << "id,revenue,region,score,active\n";
        for (int i = 0; i < 500000; ++i) {
            f << i << ","
              << (i * 2.5 + 1.1) << ","
              << "region_" << (i % 10) << ","
              << (i % 100) << ","
              << (i % 2 == 0 ? "true" : "false") << "\n";
        }
    }

    zedda::ProfileBuilder builder("big_test.csv");
    auto profile = builder.build();

    std::cout << "Rows      : " << profile.num_rows << "\n";
    std::cout << "Time      : " << profile.scan_time_ms << " ms\n";
    std::cout << "Rows/sec  : "
              << static_cast<int>(profile.num_rows / (profile.scan_time_ms / 1000.0))
              << "\n";

    bool ok = profile.num_rows == 500000 && profile.scan_time_ms < 10000;
    std::cout << (ok ? "PASS ✓" : "FAIL ✗") << "\n";
}

int main() {
    std::cout << "zedda — ProfileBuilder tests\n";
    std::cout << "==============================\n";
    test_full_profile();
    test_performance_profile();
    std::cout << "\nDone! Full pipeline ready! 🚀\n";
    return 0;
}