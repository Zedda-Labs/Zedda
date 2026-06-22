// Quick crash debug — isolate where the crash occurs
#include <iostream>
#include "zedda/stream_reader.hpp"

int main() {
    std::cout << "Step 1: Creating reader\n"; std::cout.flush();
    zedda::CsvStreamReader reader("mini_test.csv");

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
