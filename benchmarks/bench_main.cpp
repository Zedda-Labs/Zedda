// ─────────────────────────────────────────────────────────────────────────────
//  zedda benchmark — Production ProfileBuilder & SIMD Pipeline Breakdown
//
//  Measures:
//    1. Production ProfileBuilder: multi-threaded parallel CSV profiling path
//       matching zd.scan() and zd.profile().
//    2. Isolated SIMD scan: scalar vs AVX2/AVX-512 comparison.
//    3. Isolated Number parsing: fast_float from_chars throughput.
// ─────────────────────────────────────────────────────────────────────────────

#include <iostream>
#include <fstream>
#include <iomanip>
#include <chrono>
#include <string>
#include <vector>
#include <cstdlib>
#include <cstdint>
#include <cstdio>

#include "zedda/profile_builder.hpp"
#include "zedda/stream_reader.hpp"
#include "zedda/simd_scanner.hpp"
#include "zedda/fast_float/fast_float.h"

// ─────────────────────────────────────────────────────────────────────────────
//  Synthetic CSV generator — 31 column transaction schema
// ─────────────────────────────────────────────────────────────────────────────
static const char* CATEGORIES[] = {
    "retail", "food", "travel", "entertainment", "utilities",
    "healthcare", "education", "automotive", "real_estate", "financial"
};
static const char* CURRENCIES[] = {"USD", "EUR", "GBP", "JPY", "INR", "CAD"};
static const char* CHANNELS[]   = {"online", "in_store", "mobile", "ATM", "phone"};
static const char* STATUSES[]   = {"approved", "declined", "pending", "flagged"};

void generate_csv(const std::string& path, int64_t num_rows) {
    std::ofstream f(path);
    if (!f) { std::cerr << "Cannot create " << path << "\n"; return; }

    f << "transaction_id,customer_id,amount,currency,merchant,category,"
         "sub_category,channel,device_type,country,city,zip_code,"
         "card_type,card_last4,is_international,is_high_risk,is_human,"
         "fraud_score,confidence,latitude,longitude,merchant_score,"
         "session_id,ip_address,user_agent_hash,txn_hour,txn_day,"
         "txn_month,txn_year,response_code,status\n";

    for (int64_t i = 0; i < num_rows; ++i) {
        int64_t cust_id  = (i % 50000) + 1;
        double  amount   = 10.0 + (i % 9990);
        int     cat_idx  = i % 10;
        int     cur_idx  = i % 6;
        int     chan_idx = i % 5;
        int     status_i = i % 4;
        double  lat      = -90.0  + (i % 18000) * 0.01;
        double  lon      = -180.0 + (i % 36000) * 0.01;
        int     hour     = i % 24;
        int     day      = (i % 28) + 1;
        int     month    = (i % 12) + 1;
        int     year     = 2023 + (i % 2);

        f << "TXN" << std::setw(10) << std::setfill('0') << i << ","
          << "CUST" << cust_id << ","
          << std::fixed << std::setprecision(2) << amount << ","
          << CURRENCIES[cur_idx] << ","
          << "Merchant_" << (i % 1000) << ","
          << CATEGORIES[cat_idx] << ","
          << "sub_" << (i % 50) << ","
          << CHANNELS[chan_idx] << ","
          << "mobile" << ","
          << "US" << ","
          << "City_" << (i % 200) << ","
          << std::setw(5) << std::setfill('0') << (i % 99999) << ","
          << "VISA" << ","
          << std::setw(4) << std::setfill('0') << (i % 9999) << ","
          << (i % 5 == 0 ? 1 : 0) << ","
          << (i % 10 == 0 ? 1 : 0) << ","
          << 1.0 << ","
          << std::setprecision(4) << (i % 1000) * 0.001 << ","
          << std::setprecision(4) << 0.5 + (i % 500) * 0.001 << ","
          << std::setprecision(6) << lat << ","
          << std::setprecision(6) << lon << ","
          << std::setprecision(2) << (i % 100) * 1.0 << ","
          << "SESS" << i << ","
          << (10 + i % 245) << "." << (i % 255) << "." << (i % 255) << ".1,"
          << "hash_" << (i % 100000) << ","
          << hour << ","
          << day  << ","
          << month << ","
          << year << ","
          << "00" << ","
          << STATUSES[status_i] << "\n";
        if (i % 100000 == 0) { f.flush(); }
    }

    f.flush();
    std::cout << "  Generated: " << path << " (" << num_rows << " rows)\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  run_production_benchmark — benchmark actual ProfileBuilder production engine
// ─────────────────────────────────────────────────────────────────────────────
double run_production_benchmark(const std::string& csv_path) {
    zedda::StreamReaderConfig cfg;
    zedda::ProfileBuilder builder(csv_path, cfg);

    auto t0 = std::chrono::high_resolution_clock::now();
    zedda::DatasetProfile profile = builder.build();
    auto t1 = std::chrono::high_resolution_clock::now();

    (void)profile;
    return std::chrono::duration<double, std::milli>(t1 - t0).count();
}

// ─────────────────────────────────────────────────────────────────────────────
//  run_isolated_benchmarks — pipeline breakdown (ns/byte, ns/field)
// ─────────────────────────────────────────────────────────────────────────────
void run_isolated_benchmarks() {
    std::cout << "═══ Pipeline Breakdown (Isolated) ═══\n";
    std::cout.flush();

    // 1. SIMD scan benchmark (10MB synthetic CSV)
    std::string large_csv;
    large_csv.reserve(10000000);
    for (int i = 0; i < 200000; i++) {
        large_csv += "some,random,csv,data,123.45,to,scan\n";
    }

    // Scalar scan
    auto t_scalar0 = std::chrono::high_resolution_clock::now();
    size_t pos_s = 0;
    while (pos_s < large_csv.size()) {
        pos_s = zedda::find_next_special_scalar(large_csv.data(), large_csv.size(), pos_s, ',', '"');
        if (pos_s < large_csv.size()) pos_s++;
    }
    auto t_scalar1 = std::chrono::high_resolution_clock::now();
    double scalar_ms = std::chrono::duration<double, std::milli>(t_scalar1 - t_scalar0).count();

    // AVX2 / active scan
    auto t_simd0 = std::chrono::high_resolution_clock::now();
    size_t pos_simd = 0;
    auto scanner = zedda::get_active_scanner();
    while (pos_simd < large_csv.size()) {
        pos_simd = scanner(large_csv.data(), large_csv.size(), pos_simd, ',', '"');
        if (pos_simd < large_csv.size()) pos_simd++;
    }
    auto t_simd1 = std::chrono::high_resolution_clock::now();
    double simd_ms = std::chrono::duration<double, std::milli>(t_simd1 - t_simd0).count();

    // 2. Number parsing benchmark (1M fields)
    const int num_fields = 1000000;
    std::vector<std::string> fields;
    fields.reserve(num_fields);
    for (int i = 0; i < num_fields; ++i) {
        fields.push_back(std::to_string((i % 10000) * 0.1234));
    }

    auto t_parse0 = std::chrono::high_resolution_clock::now();
    double dummy;
    for (const auto& s : fields) {
        fast_float::from_chars(s.data(), s.data() + s.size(), dummy);
    }
    auto t_parse1 = std::chrono::high_resolution_clock::now();
    double parse_ms = std::chrono::duration<double, std::milli>(t_parse1 - t_parse0).count();

    std::cout << std::left
              << std::setw(24) << "Scalar scan:" << scalar_ms << " ms  ("
              << (scalar_ms * 1e6 / large_csv.size()) << " ns/byte)\n"
              << std::setw(24) << "Active SIMD scan:" << simd_ms << " ms  ("
              << (simd_ms * 1e6 / large_csv.size()) << " ns/byte)\n"
              << std::setw(24) << "SIMD scan speedup:" << (scalar_ms / (simd_ms > 0 ? simd_ms : 1.0)) << "x\n"
              << std::setw(24) << "Number parsing:" << parse_ms << " ms  ("
              << (parse_ms * 1e6 / num_fields) << " ns/field)\n\n";
}

int main() {
    std::cout << "zedda — Production Pipeline Benchmark\n";
    std::cout << "====================================\n\n";

    run_isolated_benchmarks();

    std::cout << "CPU features detected:\n";
    std::cout << "  AVX2    : " << (zedda::has_avx2()    ? "YES" : "NO") << "\n";
    std::cout << "  AVX-512 : " << (zedda::has_avx512f() ? "YES" : "NO") << "\n";

    const char* active = zedda::has_avx512f() ? "AVX-512"
                       : zedda::has_avx2()    ? "AVX2"
                       :                        "SCALAR";
    std::cout << "  Active scanner: " << active << "\n\n";
    std::cout.flush();

    struct BenchCase {
        int64_t     rows;
        const char* label;
        const char* csv_path;
        double      target_ms;
    };

    std::vector<BenchCase> cases = {
        {   100'000, "100K", "bench_100k.csv",  100.0},
        { 1'000'000, "1M",   "bench_1m.csv",    800.0},
    };

    std::cout << "Generating synthetic CSVs (31 columns, transaction schema)...\n";
    for (auto& c : cases) {
        generate_csv(c.csv_path, c.rows);
    }
    std::cout << "\n";

    std::cout << std::left
              << std::setw(12) << "Rows"
              << std::setw(20) << "Production (ms)"
              << std::setw(16) << "Target (ms)"
              << std::setw(14) << "Target met?"
              << "\n";
    std::cout << std::string(62, '-') << "\n";

    for (auto& c : cases) {
        double prod_ms = run_production_benchmark(c.csv_path);
        bool target_met = (prod_ms > 0.0 && prod_ms <= c.target_ms);

        std::cout << std::left
                  << std::setw(12) << c.label
                  << std::fixed << std::setprecision(1)
                  << std::setw(20) << prod_ms
                  << std::setw(16) << c.target_ms
                  << (target_met ? "✓ YES" : "✗ MISS")
                  << "\n";

        // Clean up temporary bench fixture
        std::remove(c.csv_path);
    }

    std::cout << "\nBenchmark complete.\n";
    return 0;
}
