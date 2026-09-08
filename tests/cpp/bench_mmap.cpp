#include <iostream>
#include <chrono>
#include <fstream>
#include <string>
#include "zedda/mmap_reader.hpp"

void run_benchmarks(const std::string& filepath) {
    // 1. fgets / fgetc raw count lines
    {
        auto start = std::chrono::high_resolution_clock::now();
        FILE* f = fopen(filepath.c_str(), "rb");
        if (!f) return;
        
        size_t newlines = 0;
        int c;
        while ((c = fgetc(f)) != EOF) {
            if (c == '\n') newlines++;
        }
        fclose(f);
        auto end = std::chrono::high_resolution_clock::now();
        std::chrono::duration<double> diff = end - start;
        std::cout << "[fgets/fgetc] Newlines: " << newlines << ", Time: " << diff.count() * 1000.0 << " ms\n";
    }

    // 2. Mmap count lines
    {
        auto start = std::chrono::high_resolution_clock::now();
        zedda::MmapFile f(filepath);
        if (!f.open()) return;
        
        size_t newlines = 0;
        const char* data = f.data();
        size_t size = f.size();
        for (size_t i = 0; i < size; ++i) {
            if (data[i] == '\n') newlines++;
        }
        
        auto end = std::chrono::high_resolution_clock::now();
        std::chrono::duration<double> diff = end - start;
        std::cout << "[MmapFile]    Newlines: " << newlines << ", Time: " << diff.count() * 1000.0 << " ms\n";
    }
}

int main(int argc, char** argv) {
    std::string filepath = "transaction_data.csv";
    if (argc > 1) {
        filepath = argv[1];
    }
    for (int i=1; i<=3; i++) {
        std::cout << "--- Run " << i << " ---\n";
        run_benchmarks(filepath);
    }
    return 0;
}
