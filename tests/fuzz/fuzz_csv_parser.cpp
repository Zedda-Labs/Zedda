// Minimal libFuzzer harness for the CSV streaming parser.
// Feeds arbitrary byte input directly into the parse_line_sv path to find
// crashes, hangs, or sanitizer-detected UB on malformed/adversarial CSV data.
#include <cstdint>
#include <cstddef>
#include <string_view>
#include "zedda/stream_reader.hpp"

extern "C" int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size) {
  std::string_view input(reinterpret_cast<const char*>(data), size);
  // TODO(owner): call the actual parse entry point exposed by
  // CsvStreamReader / parse_line_sv here. This harness intentionally does NOT
  // guess the exact internal API surface — wire it to whatever function
  // parses a raw line/buffer without requiring a full file on disk.
  // Example shape once wired:
  //   zedda::parse_line_sv(input, ',', '"');
  return 0;
}
