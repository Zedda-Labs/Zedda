#include <nanobind/nanobind.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>
#include <nanobind/stl/function.h>

#include "fasteda/profile_builder.hpp"
#include "fasteda/profile_result.hpp"
#include "fasteda/column_accumulator.hpp"

namespace nb = nanobind;
using namespace fasteda;

NB_MODULE(fasteda_core, m) {
    m.doc() = "fasteda C++ core — blazing fast EDA engine";

    // ── ColumnProfile ─────────────────────────────────────────────
    nb::class_<ColumnProfile>(m, "ColumnProfile")
        .def_ro("name",               &ColumnProfile::name)
        .def_ro("type_str",           &ColumnProfile::type_str)
        .def_ro("total_count",        &ColumnProfile::total_count)
        .def_ro("null_count",         &ColumnProfile::null_count)
        .def_ro("non_null_count",     &ColumnProfile::non_null_count)
        .def_ro("null_pct",           &ColumnProfile::null_pct)
        .def_ro("unique_approx",      &ColumnProfile::unique_approx)
        .def_ro("unique_pct",         &ColumnProfile::unique_pct)
        .def_ro("mean",               &ColumnProfile::mean)
        .def_ro("stddev",             &ColumnProfile::stddev)
        .def_ro("variance",           &ColumnProfile::variance)
        .def_ro("skewness",           &ColumnProfile::skewness)
        .def_ro("kurtosis",           &ColumnProfile::kurtosis)
        .def_ro("val_min",            &ColumnProfile::val_min)
        .def_ro("val_max",            &ColumnProfile::val_max)
        .def_ro("range",              &ColumnProfile::range)
        .def_ro("min_str_len",        &ColumnProfile::min_str_len)
        .def_ro("max_str_len",        &ColumnProfile::max_str_len)
        .def_ro("mean_str_len",       &ColumnProfile::mean_str_len)
        .def_ro("has_high_nulls",     &ColumnProfile::has_high_nulls)
        .def_ro("is_constant",        &ColumnProfile::is_constant)
        .def_ro("is_high_cardinality",&ColumnProfile::is_high_cardinality)
        .def("__repr__", [](const ColumnProfile& c) {
            return "<Column '" + c.name + "' type=" + c.type_str
                 + " nulls=" + std::to_string(c.null_count) + ">";
        });

    // ── DatasetProfile ────────────────────────────────────────────
    nb::class_<DatasetProfile>(m, "DatasetProfile")
        .def_ro("file_name",          &DatasetProfile::file_name)
        .def_ro("file_path",          &DatasetProfile::file_path)
        .def_ro("num_rows",           &DatasetProfile::num_rows)
        .def_ro("num_cols",           &DatasetProfile::num_cols)
        .def_ro("num_numeric",        &DatasetProfile::num_numeric)
        .def_ro("num_string",         &DatasetProfile::num_string)
        .def_ro("overall_null_pct",   &DatasetProfile::overall_null_pct)
        .def_ro("total_null_cells",   &DatasetProfile::total_null_cells)
        .def_ro("total_cells",        &DatasetProfile::total_cells)
        .def_ro("scan_time_ms",       &DatasetProfile::scan_time_ms)
        .def_ro("columns",            &DatasetProfile::columns)
        .def("__repr__", [](const DatasetProfile& d) {
            return "<DatasetProfile '" + d.file_name + "' "
                 + std::to_string(d.num_rows) + " rows x "
                 + std::to_string(d.num_cols) + " cols>";
        });

    // ── profile() — main entry point ─────────────────────────────
    m.def("profile",
        [](const std::string& path, bool show_progress) {
            ProfileBuilder builder(path);
            if (show_progress) {
                builder.set_progress([](int64_t rows) {
                    // progress shown from Python side
                    (void)rows;
                });
            }
            return builder.build();
        },
        nb::arg("path"),
        nb::arg("show_progress") = true,
        "Profile a CSV/Excel/JSON/Parquet file.\n\n"
        "Example::\n\n"
        "    import fasteda as fe\n"
        "    p = fe.profile('data.csv')\n"
        "    print(p.num_rows)\n"
    );
}