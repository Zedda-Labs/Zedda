#include <nanobind/nanobind.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>
#include <nanobind/stl/array.h>
#include <nanobind/stl/function.h>
#include <stdexcept>

#include "zedda/profile_builder.hpp"
#include "zedda/profile_result.hpp"
#include "zedda/column_accumulator.hpp"
#include "zedda/arrow_profiler.hpp"

namespace nb = nanobind;
using namespace zedda;

NB_MODULE(fasteda_core, m) {
    m.doc() = "zedda C++ core — blazing fast EDA engine";

    // ── ColumnProfile ─────────────────────────────────────────────
    // FIX C-M10: Use def_ro (read-only) for purely-computed fields so
    // Python users can't put the struct into an inconsistent state by
    // writing e.g. cp.unique_approx = 999. Fields that Python's
    // _scan_arrow legitimately overwrites with Parquet footer stats
    // (null_count, null_pct, non_null_count, has_high_nulls, val_min,
    // val_max, range) remain def_rw. 'name' is writable for renaming.
    nb::class_<ColumnProfile>(m, "ColumnProfile")
        .def_rw("name",               &ColumnProfile::name)
        .def_ro("type_str",           &ColumnProfile::type_str)
        .def_ro("total_count",        &ColumnProfile::total_count)
        .def_rw("null_count",         &ColumnProfile::null_count)
        .def_rw("non_null_count",     &ColumnProfile::non_null_count)
        .def_rw("null_pct",           &ColumnProfile::null_pct)
        .def_ro("valid_count",        &ColumnProfile::valid_count)
        .def_ro("missing_count",      &ColumnProfile::missing_count)
        .def_ro("invalid_count",      &ColumnProfile::invalid_count)
        .def_ro("parse_error_count",  &ColumnProfile::parse_error_count)
        .def_ro("unsupported_types",  &ColumnProfile::unsupported_types)
        .def_ro("type_mismatch_count",&ColumnProfile::type_mismatch_count)
        .def_ro("type_mismatch_pct",  &ColumnProfile::type_mismatch_pct)
        .def_ro("unique_approx",      &ColumnProfile::unique_approx)
        .def_ro("unique_pct",         &ColumnProfile::unique_pct)
        .def_ro("mean",               &ColumnProfile::mean)
        .def_ro("stddev",             &ColumnProfile::stddev)
        .def_ro("variance",           &ColumnProfile::variance)
        .def_ro("skewness",           &ColumnProfile::skewness)
        .def_ro("kurtosis",           &ColumnProfile::kurtosis)
        .def_rw("val_min",            &ColumnProfile::val_min)
        .def_rw("val_max",            &ColumnProfile::val_max)
        .def_rw("range",              &ColumnProfile::range)
        .def_ro("min_str_len",        &ColumnProfile::min_str_len)
        .def_ro("max_str_len",        &ColumnProfile::max_str_len)
        .def_ro("mean_str_len",       &ColumnProfile::mean_str_len)
        .def_rw("has_high_nulls",     &ColumnProfile::has_high_nulls)
        .def_ro("is_constant",          &ColumnProfile::is_constant)
        .def_ro("is_high_cardinality",  &ColumnProfile::is_high_cardinality)
        // ── New in v0.5.0 ───────────────────────────────────────
        // 16-bin equal-width histogram from a per-thread reservoir sample.
        .def_ro("histogram_bins",       &ColumnProfile::histogram_bins)
        // Distinct string values (low-cardinality str cols, cap 100)
        .def_ro("top_values",           &ColumnProfile::top_values)
        // Exact unique count (-1 = not computed; overrides unique_approx when valid)
        .def_ro("unique_exact",         &ColumnProfile::unique_exact)
        .def_ro("exact_unique_valid",   &ColumnProfile::exact_unique_valid)
        // Aliases for F-014 categorical drift support
        .def_prop_ro("distinct_values", [](const ColumnProfile& c) { return c.top_values; })
        .def_prop_ro("distinct_overflowed", [](const ColumnProfile& c) { return !c.exact_unique_valid; })
        .def("__repr__", [](const ColumnProfile& c) {
            return "<ColumnProfile '" + c.name + "' (" + c.type_str + ")>";
        });

    // ── CorrelationResult ─────────────────────────────────────────
    nb::class_<CorrelationResult>(m, "CorrelationResult")
        .def_ro("col_a",     &CorrelationResult::col_a)
        .def_ro("col_b",     &CorrelationResult::col_b)
        .def_ro("r",         &CorrelationResult::r)
        .def_ro("direction", &CorrelationResult::direction)
        .def_ro("strength",  &CorrelationResult::strength)
        .def("__repr__", [](const CorrelationResult& cr) {
            return "<Correlation '" + cr.col_a + "' <-> '" + cr.col_b +
                   "' r=" + std::to_string(cr.r) + ">";
        });

    // ── DatasetProfile ────────────────────────────────────────────
    nb::class_<DatasetProfile>(m, "DatasetProfile")
        .def_rw("file_name",            &DatasetProfile::file_name)
        .def_rw("file_path",            &DatasetProfile::file_path)
        .def_rw("num_rows",             &DatasetProfile::num_rows)
        .def_rw("num_cols",             &DatasetProfile::num_cols)
        .def_rw("num_numeric",          &DatasetProfile::num_numeric)
        .def_rw("num_string",           &DatasetProfile::num_string)
        .def_rw("overall_null_pct",     &DatasetProfile::overall_null_pct)
        .def_rw("total_null_cells",     &DatasetProfile::total_null_cells)
        .def_rw("total_cells",          &DatasetProfile::total_cells)
        .def_rw("scan_time_ms",         &DatasetProfile::scan_time_ms)
        .def_rw("is_sampled",           &DatasetProfile::is_sampled)
        .def_rw("columns",              &DatasetProfile::columns)
        .def_ro("correlations",         &DatasetProfile::correlations)
        // FIX PERF-1: expose correlation_skipped so Python layer can show
        // a user-facing yellow warning when correlation was auto-skipped.
        .def_ro("correlation_skipped",  &DatasetProfile::correlation_skipped)
        .def("__repr__", [](const DatasetProfile& d) {
            return "<DatasetProfile '" + d.file_name + "' "
                 + std::to_string(d.num_rows) + " rows x "
                 + std::to_string(d.num_cols) + " cols>";
        });

    // ── profile() — main entry point ──────────────────────────────
    m.def("profile",
        [](const std::string& path, bool show_progress,
           bool is_sampled, int64_t sample_size, bool correlate,
           int delimiter, int quote_char, int escape_char,
           const std::string& encoding) {
            auto to_char = [](int value, const char* name) {
                if (value < 0 || value > 255) {
                    throw std::invalid_argument(std::string(name) + " must be a byte");
                }
                return static_cast<char>(value);
            };
            StreamReaderConfig config;
            config.delimiter = to_char(delimiter, "delimiter");
            config.quote_char = to_char(quote_char, "quote_char");
            config.escape_char = to_char(escape_char, "escape_char");
            config.encoding = encoding;
            if (encoding == "utf-16" || encoding == "utf-16-le"
                || encoding == "utf-16-be") {
                throw std::invalid_argument(
                    "UTF-16 input must be normalized by CSVAdapter before native profiling");
            }
            ProfileBuilder builder(path, config);
            if (show_progress) {
                builder.set_progress([](int64_t rows) {
                    // Feature 7 NOTE: progress forwarding to Python is not yet
                    // implemented. The C++ callback fires correctly but the row
                    // count is not forwarded to any Python-side callback.
                    // TODO: forward rows via nanobind to enable real progress bars.
                    (void)rows;
                });
            }
            // FIX C-H4: Release the GIL during the long CPU-bound C++ scan.
            // Without this, every other Python thread is blocked for the
            // entire scan (potentially seconds). The returned DatasetProfile
            // contains only POD/std::string/std::vector — safe to construct
            // without the GIL.
            nb::gil_scoped_release guard;
            return builder.build(is_sampled, sample_size, correlate);
        },
        nb::arg("path"),
        nb::arg("show_progress") = true,
        nb::arg("is_sampled")    = false,
        nb::arg("sample_size")   = 1000000,
        // FIX PERF-1: correlate=False (default) skips O(N²) correlation
        // when numeric cols > 50. Users can force it with correlate=True.
        nb::arg("correlate")     = false,
        nb::arg("delimiter")     = 44,
        nb::arg("quote_char")    = 34,
        nb::arg("escape_char")   = 0,
        nb::arg("encoding")      = "auto",
        "Profile a CSV/Excel/JSON/Parquet file.\n\n"
        "Example::\n\n"
        "    import zedda as zd\n"
        "    p = zd.profile('data.csv')\n"
        "    print(p.num_rows)\n"
    );

    // ── ArrowProfiler ──────────────────────────────────────────────
    nb::class_<ArrowProfiler>(m, "ArrowProfiler")
        .def(nb::init<const std::string&, int64_t>(), nb::arg("file_name"), nb::arg("total_rows"))
        .def("consume_batch", &ArrowProfiler::consume_batch, nb::arg("schema_ptr"), nb::arg("array_ptr"))
        .def("finalize", &ArrowProfiler::finalize);
}
