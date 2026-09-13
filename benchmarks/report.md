# Zedda Hardware-Normalized Benchmark Report

> **Generated:** 2026-09-13 14:46:29
> **Hardware:** Intel(R) Core(TM) i3-6006U CPU @ 2.00GHz (2P/4L cores) | 7.9 GB RAM | Windows 10 (AMD64) | Python 3.12.4

## 1. Methodology

- **Metric:** `Rows/sec/core` is normalized by physical CPU core count.
- **Timing:** `time.perf_counter()`, median of multiple runs after warm-up.
- **Profiling Scope:** Full summary profiling (null count, mean, min/max, distinct, histograms).

## 2. CSV Benchmark Results

| Engine | Workload | Median (ms) | Throughput (rows/s) | Normalized (rows/s/core) | vs Pandas |
|--------|----------|-------------|---------------------|--------------------------|-----------|
| **Zedda** | CSV Full Profile | 104.3 | 95,846 | **47,923** | 0.59x |
| **Polars** | CSV Read + Describe | 10.3 | 970,859 | **485,429** | 5.99x |
| **DuckDB** | CSV SUMMARIZE SQL | 350.6 | 28,521 | **14,260** | 0.18x |
| **Pandas** | CSV Read + Describe All | 61.7 | 162,003 | **81,001** | 1.00x |

## 3. Parquet Benchmark Results

| Engine | Workload | Median (ms) | Throughput (rows/s) | Normalized (rows/s/core) | vs Pandas |
|--------|----------|-------------|---------------------|--------------------------|-----------|
| **Zedda** | Parquet Zero-Copy Profile | 86.6 | 115,463 | **57,731** | 0.43x |
| **Polars** | Parquet Read + Describe | 7.9 | 1,258,083 | **629,041** | 4.64x |
| **DuckDB** | Parquet SUMMARIZE SQL | 55.0 | 181,941 | **90,970** | 0.67x |
| **Pandas** | Parquet Read + Describe All | 36.9 | 270,876 | **135,438** | 1.00x |
