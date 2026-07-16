// Quick crash debug — isolate where the crash occurs
#include <iostream>
#include <fstream>
#include "zedda/stream_reader.hpp"

int main() {
    std::cout << "Step 1: Creating reader\n"; std::cout.flush();
    
    // Try current dir first, then fallback to parent dir (for ctest in build/)
    std::string path = "tests/data/titanic.csv";
    std::ifstream test_f(path);
    if (!test_f.good()) {
        path = "../tests/data/titanic.csv";
    }
    test_f.close();

    zedda::CsvStreamReader reader(path);

    std::cout << "Step 2: Calling open()\n"; std::cout.flush();
    bool ok = reader.open();
    std::cout << "Step 3: open() returned " << ok << "\n"; std::cout.flush();

    auto accs = reader.make_accumulators();
    std::cout << "Step 4: accs size = " << accs.size() << "\n"; std::cout.flush();

    std::cout << "Step 5: Calling read_chunk\n"; std::cout.flush();
    auto res = reader.read_chunk(accs);
    std::cout << "Step 6: rows = " << res.rows_processed << "\n"; std::cout.flush();

    return 0;
}
