// Minimal libFuzzer harness for the CSV streaming parser.
// Feeds arbitrary byte input directly into the parse_line_sv path to find
// crashes, hangs, or sanitizer-detected UB on malformed/adversarial CSV data.
#include <cstdint>
#include <cstddef>
#include <string_view>
#include "zedda/stream_reader.hpp"

extern "C" int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size) {
  if (size == 0) return 0;
  
  const char* chars = reinterpret_cast<const char*>(data);
  zedda::ScanFn scanner = zedda::get_active_scanner();
  
  size_t pos = 0;
  while (pos < size) {
      size_t next_pos = scanner(chars, size, pos, ',', '"');
      if (next_pos == size || next_pos >= size) {
          break;
      }
      pos = next_pos + 1;
  }
  return 0;
}
