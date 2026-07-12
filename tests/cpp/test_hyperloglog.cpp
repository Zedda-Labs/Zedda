#include <iostream>
#include <string>
#include <vector>
#include <cmath>
#include "zedda/hyperloglog.hpp"

// ── Group D: HyperLogLog Tests ────────────────────────────────────

void test_large_cardinality() {
    std::cout << "\n=== Test: HyperLogLog Large Cardinality ===\n";
    zedda::HyperLogLog hll;
    
    // Add 100,000 unique items
    const int NUM_ITEMS = 100000;
    for (int i = 0; i < NUM_ITEMS; ++i) {
        hll.add(std::to_string(i));
    }
    
    double estimate = hll.estimate();
    std::cout << "Added " << NUM_ITEMS << " unique items.\n";
    std::cout << "Estimated cardinality: " << estimate << "\n";
    
    // HLL with 14 bits (16384 registers) has a standard error of ~1.04 / sqrt(16384) = ~0.81%
    // We allow a generous 5% error margin for this test
    double error_margin = NUM_ITEMS * 0.05;
    bool ok = std::abs(estimate - NUM_ITEMS) < error_margin;
    std::cout << (ok ? "PASS ✓" : "FAIL ✗") << "\n";
}

void test_merge_correctness() {
    std::cout << "\n=== Test: HyperLogLog Merge Correctness ===\n";
    zedda::HyperLogLog hll1;
    zedda::HyperLogLog hll2;
    zedda::HyperLogLog hll_combined;
    
    const int NUM_ITEMS = 50000;
    // hll1: 0 to 49999
    for (int i = 0; i < NUM_ITEMS; ++i) {
        std::string s = std::to_string(i);
        hll1.add(s);
        hll_combined.add(s);
    }
    // hll2: 25000 to 74999 (overlap of 25000)
    for (int i = 25000; i < 75000; ++i) {
        std::string s = std::to_string(i);
        hll2.add(s);
        hll_combined.add(s);
    }
    
    // Merge hll2 into hll1
    hll1.merge(hll2);
    
    double estimate_merged = hll1.estimate();
    double estimate_combined = hll_combined.estimate();
    
    std::cout << "Merged estimate (expected ~75000): " << estimate_merged << "\n";
    std::cout << "Combined estimate (expected ~75000): " << estimate_combined << "\n";
    
    // The merged HLL should have the EXACT same state as an HLL that saw all elements directly
    bool ok_exact_match = (estimate_merged == estimate_combined);
    // And it should be close to 75000
    bool ok_val = std::abs(estimate_merged - 75000) < (75000 * 0.05);
    
    std::cout << "Exact match with combined: " << (ok_exact_match ? "PASS ✓" : "FAIL ✗") << "\n";
    std::cout << "Estimate accuracy: " << (ok_val ? "PASS ✓" : "FAIL ✗") << "\n";
}

int main() {
    std::cout << "zedda — HyperLogLog tests\n";
    std::cout << "===========================\n";
    
    test_large_cardinality();
    test_merge_correctness();
    
    std::cout << "\nDone! HyperLogLog ready! 🚀\n";
    return 0;
}
