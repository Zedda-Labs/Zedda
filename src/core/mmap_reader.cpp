// ─────────────────────────────────────────────────────────────────────────────
//  zedda::MmapFile — implementation
//
//  Two platform paths:
//    _WIN32  : CreateFile + CreateFileMapping + MapViewOfFile
//    POSIX   : open + fstat + mmap(MAP_PRIVATE | MAP_POPULATE)
//
//  MAP_POPULATE (Linux only) tells the kernel to pre-fault pages immediately.
//  This turns random-access latency into sequential prefetch throughput —
//  critical for CSV parsing which reads every byte exactly once, front to back.
//
//  On macOS, MAP_POPULATE is not available but madvise(MADV_SEQUENTIAL) has
//  the same effect; we call it automatically on non-Linux POSIX systems.
// ─────────────────────────────────────────────────────────────────────────────

#include "zedda/mmap_reader.hpp"
#include <cstdio>   // for stderr diagnostic in debug builds

namespace zedda {

// ─────────────────────────────────────────────────────────────────────────────
#ifdef _WIN32
// ── Windows implementation ────────────────────────────────────────────────────

bool MmapFile::open() {
    // Step 1: Open file for reading
    file_handle_ = CreateFileA(
        path_.c_str(),
        GENERIC_READ,
        FILE_SHARE_READ,       // allow concurrent readers
        nullptr,               // default security
        OPEN_EXISTING,
        FILE_FLAG_SEQUENTIAL_SCAN,  // hint: we will read front-to-back
        nullptr
    );

    if (file_handle_ == INVALID_HANDLE_VALUE) {
#ifdef ZEDDA_DEBUG
        fprintf(stderr, "[zedda:mmap] CreateFile failed for '%s', falling back to fgets\n",
                path_.c_str());
#endif
        return false;
    }

    // Step 2: Get file size
    LARGE_INTEGER file_size{};
    if (!GetFileSizeEx(file_handle_, &file_size)) {
#ifdef ZEDDA_DEBUG
        fprintf(stderr, "[zedda:mmap] GetFileSizeEx failed, falling back to fgets\n");
#endif
        CloseHandle(file_handle_);
        file_handle_ = INVALID_HANDLE_VALUE;
        return false;
    }

    // Empty file — valid but nothing to map
    if (file_size.QuadPart == 0) {
        size_ = 0;
        data_ = nullptr;
        // Keep file_handle_ open but signal no mapping
        // close() handles the cleanup
        return true;
    }

    size_ = static_cast<size_t>(file_size.QuadPart);

    // Step 3: Create file mapping object
    map_handle_ = CreateFileMappingA(
        file_handle_,
        nullptr,          // default security
        PAGE_READONLY,
        0, 0,             // max size = file size
        nullptr           // unnamed mapping
    );

    if (map_handle_ == nullptr) {
#ifdef ZEDDA_DEBUG
        fprintf(stderr, "[zedda:mmap] CreateFileMapping failed (error %lu), falling back to fgets\n",
                GetLastError());
#endif
        CloseHandle(file_handle_);
        file_handle_ = INVALID_HANDLE_VALUE;
        size_ = 0;
        return false;
    }

    // Step 4: Map view into address space
    void* ptr = MapViewOfFile(
        map_handle_,
        FILE_MAP_READ,
        0, 0,    // offset = 0
        0        // map entire file
    );

    if (ptr == nullptr) {
#ifdef ZEDDA_DEBUG
        fprintf(stderr, "[zedda:mmap] MapViewOfFile failed (error %lu), falling back to fgets\n",
                GetLastError());
#endif
        CloseHandle(map_handle_);
        CloseHandle(file_handle_);
        map_handle_  = nullptr;
        file_handle_ = INVALID_HANDLE_VALUE;
        size_ = 0;
        return false;
    }

    data_ = static_cast<const char*>(ptr);
    return true;
}

void MmapFile::close() {
    if (data_ != nullptr && size_ > 0) {
        UnmapViewOfFile(const_cast<char*>(data_));
        data_ = nullptr;
    }
    if (map_handle_ != nullptr) {
        CloseHandle(map_handle_);
        map_handle_ = nullptr;
    }
    if (file_handle_ != INVALID_HANDLE_VALUE) {
        CloseHandle(file_handle_);
        file_handle_ = INVALID_HANDLE_VALUE;
    }
    size_ = 0;
}

// ─────────────────────────────────────────────────────────────────────────────
#else
// ── POSIX (Linux / macOS) implementation ─────────────────────────────────────

bool MmapFile::open() {
    // Step 1: Open file descriptor
    fd_ = ::open(path_.c_str(), O_RDONLY | O_CLOEXEC);
    if (fd_ < 0) {
#ifdef ZEDDA_DEBUG
        fprintf(stderr, "[zedda:mmap] open() failed for '%s', falling back to fgets\n",
                path_.c_str());
#endif
        return false;
    }

    // Step 2: Get file size via fstat (avoids seeking)
    struct stat st{};
    if (fstat(fd_, &st) < 0) {
#ifdef ZEDDA_DEBUG
        fprintf(stderr, "[zedda:mmap] fstat failed, falling back to fgets\n");
#endif
        ::close(fd_);
        fd_ = -1;
        return false;
    }

    // Empty file — valid, nothing to mmap
    if (st.st_size == 0) {
        size_ = 0;
        data_ = nullptr;
        ::close(fd_);
        fd_ = -1;
        return true;
    }

    size_ = static_cast<size_t>(st.st_size);

    // Step 3: mmap the file
    // MAP_PRIVATE: copy-on-write (we never write, so no copies occur)
    // MAP_POPULATE (Linux): pre-fault all pages = sequential read throughput
    int flags = MAP_PRIVATE;
#ifdef MAP_POPULATE
    flags |= MAP_POPULATE;   // Linux: prefault pages = max throughput
#endif

    void* ptr = mmap(nullptr, size_, PROT_READ, flags, fd_, 0);

    if (ptr == MAP_FAILED) {
#ifdef ZEDDA_DEBUG
        fprintf(stderr, "[zedda:mmap] mmap failed, falling back to fgets\n");
#endif
        ::close(fd_);
        fd_   = -1;
        size_ = 0;
        return false;
    }

    data_ = static_cast<const char*>(ptr);

#ifdef MADV_HUGEPAGE
    // Hint to kernel to use 2MB transparent huge pages (reduces TLB misses)
    madvise(const_cast<char*>(data_), size_, MADV_HUGEPAGE);
#endif

#if !defined(MAP_POPULATE) && defined(MADV_SEQUENTIAL)
    // macOS / BSD: no MAP_POPULATE, but madvise achieves same effect
    madvise(const_cast<char*>(data_), size_, MADV_SEQUENTIAL);
#endif

    // File descriptor can be closed after mmap — the mapping stays alive
    ::close(fd_);
    fd_ = -1;

    return true;
}

void MmapFile::close() {
    if (data_ != nullptr && size_ > 0) {
        munmap(const_cast<char*>(data_), size_);
        data_ = nullptr;
    }
    if (fd_ >= 0) {
        ::close(fd_);
        fd_ = -1;
    }
    size_ = 0;
}

#endif // _WIN32

} // namespace zedda
