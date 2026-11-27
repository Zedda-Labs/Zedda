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

#include <cstddef>
#include <cstdio>
#include <string>

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

#ifdef _WIN32
inline std::wstring utf8_to_wstring(const std::string& utf8) {
    if (utf8.empty()) return {};
    int wlen = MultiByteToWideChar(
        CP_UTF8, MB_ERR_INVALID_CHARS, utf8.data(), static_cast<int>(utf8.size()), nullptr, 0
    );
    UINT cp = CP_UTF8;
    DWORD flags = MB_ERR_INVALID_CHARS;
    if (wlen <= 0) {
        // Fallback to active ANSI codepage if caller passed non-UTF-8 legacy path
        cp = CP_ACP;
        flags = 0;
        wlen = MultiByteToWideChar(cp, flags, utf8.data(), static_cast<int>(utf8.size()), nullptr, 0);
        if (wlen <= 0) return {};
    }
    std::wstring out(static_cast<size_t>(wlen), L'\0');
    MultiByteToWideChar(cp, flags, utf8.data(), static_cast<int>(utf8.size()), &out[0], wlen);
    return out;
}

inline FILE* open_file_rb(const std::string& path) {
    std::wstring wpath = utf8_to_wstring(path);
    return wpath.empty() ? nullptr : _wfopen(wpath.c_str(), L"rb");
}
#else
inline FILE* open_file_rb(const std::string& path) {
    return std::fopen(path.c_str(), "rb");
}
#endif

struct ScopedFile {
    FILE* fp = nullptr;
    explicit ScopedFile(const std::string& path) : fp(open_file_rb(path)) {}
    ~ScopedFile() {
        if (fp) {
            std::fclose(fp);
            fp = nullptr;
        }
    }
    ScopedFile(const ScopedFile&) = delete;
    ScopedFile& operator=(const ScopedFile&) = delete;
    operator FILE*() const { return fp; }
    explicit operator bool() const { return fp != nullptr; }
};

} // namespace zedda
