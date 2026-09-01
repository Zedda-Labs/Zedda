import sys
import os
import time
import psutil
import threading
import zedda as zd


class MemoryTracker:
    def __init__(self):
        self.keep_running = True
        self.peak_mb = 0
        self.thread = None
        self.process = psutil.Process(os.getpid())
        self.base_mb = self.process.memory_info().rss / (1024 * 1024)

    def _track(self):
        while self.keep_running:
            try:
                mem_mb = self.process.memory_info().rss / (1024 * 1024)
                if mem_mb > self.peak_mb:
                    self.peak_mb = mem_mb
            except Exception:
                pass
            time.sleep(0.01)

    def start(self):
        self.thread = threading.Thread(target=self._track)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        self.keep_running = False
        if self.thread:
            self.thread.join(timeout=1.0)
        return self.peak_mb


if __name__ == "__main__":
    csv_path = sys.argv[1]
    threads = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    tracker = MemoryTracker()
    tracker.start()

    t0 = time.time()
    if threads > 0:
        p = zd.scan(csv_path, num_threads=threads)
    else:
        p = zd.scan(csv_path)
    t1 = time.time()

    peak_mb = tracker.stop()

    print(f"__BENCH_TOTAL_TIME__:{t1 - t0:.4f}")
    print(f"__BENCH_PEAK_MB__:{peak_mb:.2f}")
    print(f"__BENCH_BASE_MB__:{tracker.base_mb:.2f}")
