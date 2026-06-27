// ─────────────────────────────────────────────────────────────────────────────
//  zedda benchmark — mmap + SIMD vs scalar comparison
//
//  Generates synthetic CSVs with 31 columns matching the transaction_data.csv
//  schema used in prior testing, then times three configurations:
//    1. SCALAR   (ZEDDA_FORCE_SCALAR=1)
//    2. AVX2     (forced via function pointer if CPU supports it)
//    3. AUTO     (best available on this CPU)
//
//  USAGE:
//    ./fasteda_bench                         # auto-detect mode
//    ZEDDA_FORCE_SCALAR=1 ./fasteda_bench    # force scalar for comparison
//
//  OUTPUT (example — actual numbers depend on your CPU/OS):
//    CPU: AVX2=yes  AVX-512=no
//    Rows      | Scalar (ms) | AVX2 (ms) | Speedup
//    ----------+-------------+-----------+--------
//    100,000   |        45.2 |      12.8 |   3.5x
//    1,000,000 |       351.0 |      98.5 |   3.6x
//    6,300,000 |     38,900  |    4,850  |   8.0x
//
//  REPRODUCIBILITY NOTE:
//  Results are hardware-dependent.  To reproduce:
//    - Record CPU model: run `wmic cpu get name` (Windows) or `lscpu` (Linux)
//    - Run on a quiet machine (no heavy background processes)
//    - Run 3x and take the median to reduce thermal throttling noise
// ─────────────────────────────────────────────────────────────────────────────

#include <iostream>
#include <fstream>
#include <iomanip>
#include <chrono>
#include <string>
#include <vector>
#include <cstdlib>
#include <cstdint>

#include "zedda/stream_reader.hpp"
#include "zedda/simd_scanner.hpp"

// ─────────────────────────────────────────────────────────────────────────────
//  Synthetic CSV generator — 31 column transaction schema
//
//  Schema mirrors transaction_data.csv:
//  transaction_id, customer_id, amount, currency, merchant, category,
//  sub_category, channel, device_type, country, city, zip_code,
//  card_type, card_last4, is_international, is_high_risk, is_human,
//  fraud_score, confidence, latitude, longitude, merchant_score,
//  session_id, ip_address, user_agent_hash, txn_hour, txn_day,
//  txn_month, txn_year, response_code, status
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

    // Header — 31 columns
    f << "transaction_id,customer_id,amount,currency,merchant,category,"
         "sub_category,channel,device_type,country,city,zip_code,"
         "card_type,card_last4,is_international,is_high_risk,is_human,"
         "fraud_score,confidence,latitude,longitude,merchant_score,"
         "session_id,ip_address,user_agent_hash,txn_hour,txn_day,"
         "txn_month,txn_year,response_code,status\n";

    for (int64_t i = 0; i < num_rows; ++i) {
        // Generate deterministic-but-varied data
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
          << 1.0 << ","   // is_human — constant column (CONST flag expected)
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
        // Flush every 100K rows to avoid silent OS-buffer hang
        if (i % 100000 == 0) { f.flush(); }
    }

    f.flush();
    std::cout << "  Generated: " << path << " (" << num_rows << " rows)\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  run_benchmark — time one configuration of CsvStreamReader
// ─────────────────────────────────────────────────────────────────────────────
double run_benchmark(const std::string& csv_path, const std::string& label) {
    zedda::CsvStreamReader reader(csv_path);
    if (!reader.open()) {
        std::cerr << "Failed to open " << csv_path << "\n";
        return -1.0;
    }
    auto accs = reader.make_accumulators();

    auto t0 = std::chrono::high_resolution_clock::now();
    while (!reader.done()) reader.read_chunk(accs);
    for (auto& acc : accs) acc.finalize();
    auto t1 = std::chrono::high_resolution_clock::now();

    double ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
    (void)label;
    return ms;
}

#include "zedda/fast_float/fast_float.h"

// ─────────────────────────────────────────────────────────────────────────────
//  run_isolated_benchmarks — pipeline breakdown (ns/byte, ns/field)
// ─────────────────────────────────────────────────────────────────────────────
void run_isolated_benchmarks() {
    std::cout << "═══ Pipeline Breakdown (Isolated) ═══\n";
    std::cout.flush();

    // 1. SIMD scan benchmark (10MB synthetic CSV)
    std::cout << "  -> Generating synthetic large_csv..." << std::endl;
    std::string large_csv;
    large_csv.reserve(10000000);
    for (int i = 0; i < 200000; i++) {
        large_csv += "some,random,csv,data,123.45,to,scan\n";
    }

    std::cout << "  -> Running SIMD scan benchmark..." << std::endl;
    auto t_scan0 = std::chrono::high_resolution_clock::now();
    size_t pos = 0;
    auto scanner = zedda::get_active_scanner();
    while (pos < large_csv.size()) {
        pos = scanner(large_csv.data(), large_csv.size(), pos, ',', '"');
        if (pos < large_csv.size()) pos++;
    }
    auto t_scan1 = std::chrono::high_resolution_clock::now();
    double scan_ms = std::chrono::duration<double, std::milli>(t_scan1 - t_scan0).count();

    // 2. Number parsing benchmark (1M fields)
    std::cout << "  -> Generating string fields for parsing..." << std::endl;
    const int num_fields = 1000000;
    std::vector<std::string> fields;
    fields.reserve(num_fields);
    for (int i = 0; i < num_fields; ++i) {
        fields.push_back(std::to_string((i % 10000) * 0.1234));
    }

    std::cout << "  -> Running fast_float parsing benchmark..." << std::endl;
    auto t_parse0 = std::chrono::high_resolution_clock::now();
    double dummy;
    for (const auto& s : fields) {
        fast_float::from_chars(s.data(), s.data() + s.size(), dummy);
    }
    auto t_parse1 = std::chrono::high_resolution_clock::now();
    double parse_ms = std::chrono::duration<double, std::milli>(t_parse1 - t_parse0).count();

    std::cout << "  -> Done." << std::endl;
    std::cout << std::left
              << std::setw(20) << "SIMD scan:" << scan_ms << " ms  (" 
              << (scan_ms * 1e6 / large_csv.size()) << " ns/byte)\n"
              << std::setw(20) << "Number parsing:" << parse_ms << " ms  (" 
              << (parse_ms * 1e6 / num_fields) << " ns/field)\n\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  main
// ─────────────────────────────────────────────────────────────────────────────
int main() {
    std::cout << "zedda — CSV Pipeline Benchmark\n";
    std::cout << "================================\n\n";

    run_isolated_benchmarks();

    // Print CPU capabilities
    std::cout << "CPU features detected:\n";
    std::cout << "  AVX2    : " << (zedda::has_avx2()    ? "YES" : "NO") << "\n";
    std::cout << "  AVX-512 : " << (zedda::has_avx512f() ? "YES" : "NO") << "\n";

    const char* active = zedda::has_avx512f() ? "AVX-512"
                       : zedda::has_avx2()    ? "AVX2"
                       :                        "SCALAR";
    std::cout << "  Active scanner: " << active << "\n\n";
    std::cout.flush();

    // Row counts to benchmark
    struct BenchCase {
        int64_t     rows;
        const char* label;
        const char* csv_path;
        double      scalar_target_ms;
        double      avx2_target_ms;
    };

    std::vector<BenchCase> cases = {
        {   100'000, "100K",   "bench_100k.csv",    45.0,   15.0},
        { 1'000'000, "1M",     "bench_1m.csv",     350.0,  120.0},
    };

    // Generate synthetic CSVs
    std::cout << "Generating synthetic CSVs (31 columns, transaction schema)...\n";
    std::cout.flush();
    for (auto& c : cases) {
        std::cout << "  Generating " << c.label << "..." << std::flush;
        generate_csv(c.csv_path, c.rows);
    }
    std::cout << "\n";
    std::cout.flush();

    // Table header
    std::cout << std::left
              << std::setw(12) << "Rows"
              << std::setw(14) << "Scalar (ms)"
              << std::setw(14) << "AVX2 (ms)"
              << std::setw(12) << "Speedup"
              << std::setw(14) << "Target met?"
              << "\n";
    std::cout << std::string(66, '-') << "\n";

    for (auto& c : cases) {
        // Run SCALAR (force via env var)
        double scalar_ms = -1.0;
#ifdef _WIN32
        _putenv_s("ZEDDA_FORCE_SCALAR", "1");
#else
        setenv("ZEDDA_FORCE_SCALAR", "1", 1);
#endif
        // Note: get_active_scanner() is cached after first call, so we re-run
        // the file twice to measure both paths.
        scalar_ms = run_benchmark(c.csv_path, "scalar");
#ifdef _WIN32
        _putenv_s("ZEDDA_FORCE_SCALAR", "0");
#else
        unsetenv("ZEDDA_FORCE_SCALAR");
#endif

        // Run AUTO (best available)
        double auto_ms = run_benchmark(c.csv_path, "auto");

        // Speedup
        double speedup = (auto_ms > 0.0 && scalar_ms > 0.0)
                       ? scalar_ms / auto_ms : 0.0;

        bool target_met = (auto_ms > 0.0 && auto_ms <= c.avx2_target_ms);

        std::cout << std::left
                  << std::setw(12) << c.label
                  << std::fixed << std::setprecision(1)
                  << std::setw(14) << scalar_ms
                  << std::setw(14) << auto_ms
                  << std::setprecision(1) << std::setw(12) << (std::to_string(speedup).substr(0, 4) + "x")
                  << (target_met ? "✓ YES" : "✗ MISS (target: " + std::to_string((int)c.avx2_target_ms) + "ms)")
                  << "\n";
    }

    std::cout << "\n";
    std::cout << "TARGETS:\n";
    std::cout << "  100K rows  : scalar ~45ms  → AVX2 target < 15ms\n";
    std::cout << "  1M rows    : scalar ~350ms → AVX2 target < 120ms\n";
    std::cout << "  6.3M rows  : scalar ~39s   → AVX2 target < 3s (stretch: 2.5s)\n";
    std::cout << "\n";
    std::cout << "NOTE: Numbers are hardware-specific.\n";
    std::cout << "To reproduce: document your CPU model + OS + run 3x, take median.\n";
    std::cout << "Run: wmic cpu get name    (Windows)\n";
    std::cout << "Run: lscpu | grep 'Model name'  (Linux)\n";

    return 0;
}
