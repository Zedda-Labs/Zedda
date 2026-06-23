#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  zedda::MmapFile — Cross-platform memory-mapped file reader
//
//  WHY mmap?
//  fgets() issues one syscall per line.  For 6.3M rows that is 6.3 million
//  kernel transitions (each ~100ns) = ~630ms wasted before any parsing.
//  mmap maps the entire file into the process address space with ONE syscall.
//  The OS then pages data in lazily as we touch it — no extra copies, no
//  repeated syscalls, and the CPU prefetcher works better on a linear scan.
//
//  FALLBACK SAFETY:
//  open() returns false on any failure (network FS, permission error, etc.).
//  CsvStreamReader detects this and falls back to the original fgets path.
//  The caller is never forced to handle a crash — just a graceful degradation.
//
//  PLATFORM SUPPORT:
//  - Windows  : CreateFile → CreateFileMapping → MapViewOfFile
//  - Linux/Mac: open → fstat → mmap(MAP_PRIVATE | MAP_POPULATE)
//
//  USAGE:
//    MmapFile f("data.csv");
//    if (f.open()) {
//        const char* buf = f.data();
//        size_t      len = f.size();
//        // ... parse buf[0..len-1] directly, zero copy
//    } else {
//        // fall back to fgets
//    }
// ─────────────────────────────────────────────────────────────────────────────

#include <string>
#include <cstddef>

#ifdef _WIN32
#  define WIN32_LEAN_AND_MEAN
#  define NOMINMAX
#  include <windows.h>
#else
#  include <sys/mman.h>
#  include <sys/stat.h>
#  include <fcntl.h>
#  include <unistd.h>
#endif

namespace zedda {

class MmapFile {
public:
    // ── Construction / Destruction ────────────────────────────────────────────
    explicit MmapFile(const std::string& path) : path_(path) {}

    // RAII: destructor always unmaps, even on exception paths
    ~MmapFile() { close(); }

    // Non-copyable (owning resource)
    MmapFile(const MmapFile&)            = delete;
    MmapFile& operator=(const MmapFile&) = delete;

    // Movable
    MmapFile(MmapFile&& o) noexcept
        : path_(std::move(o.path_))
        , data_(o.data_)
        , size_(o.size_)
#ifdef _WIN32
        , file_handle_(o.file_handle_)
        , map_handle_ (o.map_handle_)
#else
        , fd_(o.fd_)
#endif
    {
        o.data_  = nullptr;
        o.size_  = 0;
#ifdef _WIN32
        o.file_handle_ = INVALID_HANDLE_VALUE;
        o.map_handle_  = nullptr;
#else
        o.fd_ = -1;
#endif
    }

    // ── open() ────────────────────────────────────────────────────────────────
    // Returns true  → data() and size() are valid, caller may parse directly.
    // Returns false → mmap unavailable; caller should fall back to fgets.
    // Never throws — all errors return false with a diagnostic (debug builds).
    bool open();

    // ── close() ───────────────────────────────────────────────────────────────
    // Idempotent — safe to call multiple times.
    void close();

    // ── Accessors ─────────────────────────────────────────────────────────────
    /// Pointer to the start of the mapped file content.
    /// Valid only while is_open() == true.
    const char* data() const { return data_; }

    /// Number of bytes in the mapped file (== file size).
    size_t size() const { return size_; }

    /// True if the file is currently mapped.
    bool is_open() const { return data_ != nullptr; }

private:
    std::string path_;
    const char* data_ = nullptr;
    size_t      size_ = 0;

#ifdef _WIN32
    // Windows uses two HANDLE objects: one for the file, one for the mapping.
    HANDLE file_handle_ = INVALID_HANDLE_VALUE;
    HANDLE map_handle_  = nullptr;
#else
    // POSIX uses a file descriptor.
    int fd_ = -1;
#endif
};

} // namespace zedda
