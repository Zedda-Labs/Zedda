# How Zedda works

Zedda's engine is a C++17 streaming core connected to Python via
[nanobind](https://github.com/wjakob/nanobind), a zero-copy binding layer.

```
Python API  (zd.profile, zd.scan, zd.compare, ...)
     │
     │  nanobind — zero-copy Python/C++ bridge
     ▼
C++17 streaming engine
     │
     ├─ Welford's online algorithm    → mean / stddev / skewness / kurtosis, single pass
     ├─ HyperLogLog                   → cardinality estimate, ~16 KB per column
     ├─ Pearson correlation engine    → exact r for every column pair, O(1) memory
     ├─ SIMD (AVX2 / AVX-512) scanner → memory-mapped CSV parsing, runtime CPU dispatch
     └─ Parquet footer reader         → exact null/min/max from file metadata, no row scan
     │
     │  Arrow C Data Interface — zero-copy
     ▼
PyArrow  (Parquet / Arrow IPC file reading)
```

## Core techniques

**Welford's online algorithm** computes mean, variance, standard deviation,
skewness, and kurtosis in a single pass over the data, without the
catastrophic cancellation that naive two-pass formulas suffer from on
large-magnitude values.

**HyperLogLog** estimates the number of distinct values in a column using a
fixed ~16 KB sketch per column, regardless of how many rows the dataset has
or how many distinct values actually exist.

**The Pearson correlation engine** maintains five running sums per column
pair (`Σx`, `Σy`, `Σxy`, `Σx²`, `Σy²`) and computes an exact correlation
coefficient at the end of the scan — no second read of the file, no
materialized column pairs, O(1) memory per pair.

**The SIMD scanner** finds CSV field and row boundaries using AVX2 or
AVX-512 instructions, 32 or 64 bytes at a time. CPU feature detection runs
once at startup and selects the fastest instruction set the runtime CPU
actually supports, falling back to a scalar implementation when neither is
available. The file itself is memory-mapped rather than read line-by-line,
so parsing works directly on the OS page cache.

**The Parquet footer reader** reads exact null counts, minimums, and
maximums directly from a Parquet file's footer metadata — a compact binary
summary every Parquet file already contains — without scanning a single
data row. This is why profiling a 1 TB Parquet file takes seconds rather
than minutes.

## Memory model

Zedda's memory use is determined by the number of columns in a dataset, not
the number of rows. The engine never loads a full dataset into memory — it
streams data in chunks and updates constant-size running accumulators,
discarding each chunk once it's been processed.

| Dataset | pandas RAM | Zedda RAM |
|---|---|---|
| 1M rows, 10 cols | ~800 MB | ~2 MB |
| 10M rows, 30 cols | ~8 GB | ~6 MB |
| 1 TB Parquet | OOM | ~50 MB |

## Sampling on very large files

For files large enough that even a streaming single pass would be slow,
Zedda automatically samples using stratified row-group selection for
Parquet (reading from the start, middle, and end of the file) and reports
a confidence interval alongside sampled statistics rather than presenting
them as exact.
