// ─────────────────────────────────────────────────────────────────────────────
//  test_mmap_reader.cpp — MmapFile correctness + edge case tests
//
//  Tests:
//  1. Known small file: mmap content matches std::ifstream byte-for-byte
//  2. Empty file (0 bytes): must not crash, data() == nullptr, size() == 0
//  3. Large file: verifies size reporting is correct
//  4. Non-existent file: open() returns false gracefully
//  5. Double-close: safe to call close() multiple times
//  6. File read after mapping: content accessed correctly at various offsets
// ─────────────────────────────────────────────────────────────────────────────

#include <iostream>
#include <fstream>
#include <string>
#include <vector>
#include <cassert>
#include <cstring>
#include <random>

#include "zedda/mmap_reader.hpp"

// ── Test helpers ─────────────────────────────────────────────────────────────

static int tests_run    = 0;
static int tests_passed = 0;
static int tests_failed = 0;

#define ASSERT_TRUE(cond, msg) do {                                      \
    ++tests_run;                                                          \
    if (cond) {                                                           \
        ++tests_passed;                                                   \
    } else {                                                              \
        ++tests_failed;                                                   \
        std::cerr << "FAIL [" << __FILE__ << ":" << __LINE__ << "] "     \
                  << (msg) << "\n";                                       \
    }                                                                     \
} while(0)

#define ASSERT_EQ(a, b, msg) ASSERT_TRUE((a) == (b), \
    std::string(msg) + " (expected " + std::to_string(b) + \
    ", got " + std::to_string(a) + ")")

// Create a file with known content
static void write_file(const std::string& path, const std::string& content) {
    std::ofstream f(path, std::ios::binary);
    f.write(content.data(), content.size());
}

// Read entire file via std::ifstream
static std::string read_file_ifstream(const std::string& path) {
    std::ifstream f(path, std::ios::binary);
    return std::string(std::istreambuf_iterator<char>(f),
                       std::istreambuf_iterator<char>());
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 1: Known content — byte-for-byte match with ifstream
// ─────────────────────────────────────────────────────────────────────────────
void test_known_content() {
    std::cout << "\n=== Test 1: Known content (byte-for-byte match) ===\n";

    const std::string CONTENT =
        "id,name,score\n"
        "1,Alice,95.5\n"
        "2,Bob,87.3\n"
        "3,Charlie,92.1\n";

    write_file("test_mmap_known.csv", CONTENT);

    zedda::MmapFile f("test_mmap_known.csv");
    bool opened = f.open();
    ASSERT_TRUE(opened, "open() returns true for existing file");

    if (opened) {
        ASSERT_EQ(f.size(), CONTENT.size(), "size() matches file size");
        ASSERT_TRUE(f.is_open(), "is_open() is true after open()");
        ASSERT_TRUE(f.data() != nullptr, "data() is not null");

        // Byte-for-byte compare
        bool match = (memcmp(f.data(), CONTENT.data(), CONTENT.size()) == 0);
        ASSERT_TRUE(match, "mmap content matches ifstream content byte-for-byte");

        // Also verify via ifstream comparison
        std::string ifstream_content = read_file_ifstream("test_mmap_known.csv");
        match = (f.size() == ifstream_content.size() &&
                 memcmp(f.data(), ifstream_content.data(), f.size()) == 0);
        ASSERT_TRUE(match, "mmap content matches ifstream exactly");
    }

    std::cout << "  PASS\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 2: Empty file — must not crash
// ─────────────────────────────────────────────────────────────────────────────
void test_empty_file() {
    std::cout << "\n=== Test 2: Empty file (0 bytes) ===\n";

    write_file("test_mmap_empty.csv", "");

    zedda::MmapFile f("test_mmap_empty.csv");
    bool opened = f.open();  // Must NOT crash

    // open() should succeed (file exists)
    ASSERT_TRUE(opened, "open() returns true for empty file");
    if (opened) {
        ASSERT_EQ(f.size(), size_t(0), "size() == 0 for empty file");
        // data() may be nullptr for an empty file — that is OK
        std::cout << "  data() = " << (void*)f.data()
                  << " (null is acceptable for empty file)\n";
    }

    f.close();  // Must not crash
    ASSERT_TRUE(!f.is_open(), "is_open() is false after close()");
    std::cout << "  PASS\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 3: Non-existent file — open() returns false, no crash
// ─────────────────────────────────────────────────────────────────────────────
void test_nonexistent_file() {
    std::cout << "\n=== Test 3: Non-existent file ===\n";

    zedda::MmapFile f("this_file_absolutely_does_not_exist_xyz123.csv");
    bool opened = f.open();

    ASSERT_TRUE(!opened, "open() returns false for non-existent file");
    ASSERT_TRUE(!f.is_open(), "is_open() is false");
    ASSERT_TRUE(f.data() == nullptr, "data() is null");
    ASSERT_EQ(f.size(), size_t(0), "size() is 0");

    // close() on a file that was never opened — must not crash
    f.close();
    f.close();  // Double close — also must not crash
    std::cout << "  PASS\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 4: Double close — idempotent
// ─────────────────────────────────────────────────────────────────────────────
void test_double_close() {
    std::cout << "\n=== Test 4: Double close (idempotent) ===\n";

    write_file("test_mmap_double.csv", "hello,world\n");

    zedda::MmapFile f("test_mmap_double.csv");
    f.open();
    f.close();
    f.close();  // Second close — must not crash or double-unmap
    f.close();  // Third — still must not crash

    ASSERT_TRUE(!f.is_open(), "is_open() is false after multiple close()");
    std::cout << "  PASS\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 5: Large file — size reported correctly
// ─────────────────────────────────────────────────────────────────────────────
void test_large_file() {
    std::cout << "\n=== Test 5: Large file (1MB) ===\n";

    size_t target_size = 1024 * 1024;  // 1MB
    std::string content(target_size, 'A');
    // Sprinkle newlines to make it look like a CSV
    for (size_t i = 80; i < target_size; i += 81) content[i] = '\n';

    write_file("test_mmap_large.csv", content);

    zedda::MmapFile f("test_mmap_large.csv");
    bool opened = f.open();
    ASSERT_TRUE(opened, "open() returns true for 1MB file");
    if (opened) {
        ASSERT_EQ(f.size(), target_size, "size() matches 1MB");
        ASSERT_TRUE(f.data() != nullptr, "data() non-null for 1MB file");

        // Spot-check: first and last bytes
        ASSERT_TRUE(f.data()[0] == 'A', "first byte is 'A'");
        ASSERT_TRUE(f.data()[target_size - 1] == 'A', "last byte is 'A'");
    }

    std::cout << "  PASS\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 6: Content accessible at various offsets
// ─────────────────────────────────────────────────────────────────────────────
void test_random_access() {
    std::cout << "\n=== Test 6: Random access into mmap'd content ===\n";

    // Write content with known pattern
    std::string content;
    for (int i = 0; i < 10000; ++i) {
        content += static_cast<char>('A' + (i % 26));
    }
    write_file("test_mmap_random.csv", content);

    zedda::MmapFile f("test_mmap_random.csv");
    bool opened = f.open();
    ASSERT_TRUE(opened, "open() returned true");

    if (opened) {
        std::mt19937 rng(123);
        bool all_ok = true;
        for (int trial = 0; trial < 100; ++trial) {
            size_t idx = rng() % content.size();
            if (f.data()[idx] != content[idx]) {
                all_ok = false;
                std::cerr << "MISMATCH at offset " << idx << "\n";
                break;
            }
        }
        ASSERT_TRUE(all_ok, "100 random offsets match expected content");
    }

    std::cout << "  PASS\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 7: RAII — destructor closes without explicit close()
// ─────────────────────────────────────────────────────────────────────────────
void test_raii_destructor() {
    std::cout << "\n=== Test 7: RAII — destructor auto-closes ===\n";

    write_file("test_mmap_raii.csv", "a,b,c\n1,2,3\n");

    {
        zedda::MmapFile f("test_mmap_raii.csv");
        f.open();
        ASSERT_TRUE(f.is_open(), "is_open() true inside scope");
        // Let destructor run when scope exits
    }
    // If we get here without crashing, the destructor worked correctly
    ++tests_run;
    ++tests_passed;
    std::cout << "  PASS (destructor did not crash)\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  Test 8: Binary content validation (mmap should still map binary files,
//          the NULL-byte check is done at a higher level in CsvStreamReader)
// ─────────────────────────────────────────────────────────────────────────────
void test_binary_content() {
    std::cout << "\n=== Test 8: Binary content (MmapFile itself doesn't reject) ===\n";

    std::string binary_content(256, '\0');
    for (int i = 0; i < 256; ++i) binary_content[i] = static_cast<char>(i);
    write_file("test_mmap_binary.bin", binary_content);

    zedda::MmapFile f("test_mmap_binary.bin");
    bool opened = f.open();
    ASSERT_TRUE(opened, "MmapFile opens binary files (CsvStreamReader rejects them later)");
    if (opened) {
        ASSERT_EQ(f.size(), size_t(256), "size correct for binary file");
        // Verify byte 0x00 is accessible (mmap itself doesn't care)
        ASSERT_TRUE(f.data()[0] == '\0', "first byte is 0x00");
        ASSERT_TRUE(static_cast<unsigned char>(f.data()[255]) == 255, "last byte is 0xFF");
    }
    std::cout << "  PASS\n";
}

// ─────────────────────────────────────────────────────────────────────────────
//  main
// ─────────────────────────────────────────────────────────────────────────────
int main() {
    std::cout << "zedda — MmapFile Correctness Tests\n";
    std::cout << "====================================\n";

    test_known_content();
    test_empty_file();
    test_nonexistent_file();
    test_double_close();
    test_large_file();
    test_random_access();
    test_raii_destructor();
    test_binary_content();

    std::cout << "\n====================================\n";
    std::cout << "Results: " << tests_passed << "/" << tests_run << " passed";
    if (tests_failed > 0) {
        std::cout << "  (" << tests_failed << " FAILED)\n";
        return 1;
    }
    std::cout << "  ✓ ALL PASS\n";
    return 0;
}
