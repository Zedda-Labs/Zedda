from __future__ import annotations

import csv
import os
import tempfile
from collections.abc import Iterator

from .. import fasteda_core as _core
from .._models import InputMeta
from .._schema import ColumnSchema, DatasetSchema, DataType, LogicalRecord
from . import InputAdapter


class CSVAdapter(InputAdapter):
    """
    CSV InputAdapter — C++-kernel-delegation pattern.

    This adapter does NOT yield Python-level LogicalRecords.
    Instead, it delegates ALL data movement (parsing, chunking, boundary detection,
    and stat accumulation) to the C++ ``ProfileBuilder`` for throughput reasons.

    The C++ engine handles: BOM detection, quote-aware boundary detection,
    multi-threaded mmap-backed scanning, and SIMD-accelerated parsing.
    Routing CSV rows up to Python LogicalRecord objects would cause a ~100x
    throughput regression and memory bloat proportional to file size.

    Delegation contract:
    - ``open()``     → delegates profiling to ``fasteda_core.profile()``
    - ``schema()``   → extracts column types from C++ ProfileResult
    - ``coverage()`` → returns InputMeta from C++ ProfileResult
    - ``records()``  → raises ``NotImplementedError`` (kernel-delegation pattern;
                        see InputAdapter docstring for the two valid patterns)
    - ``close()``    → resets C++ profile reference
    """

    supported_types = ["csv", "txt", "tsv"]
    unsupported_types = []

    def __init__(
        self,
        path: str,
        is_sampled: bool = False,
        sample_size: int = 1000000,
        correlate: bool = False,
        delimiter: str | None = None,
        quotechar: str | None = None,
        escapechar: str | None = None,
        encoding: str | None = None,
        quote_char: str | None = None,
        **kwargs,
    ):
        self.path = path
        self.is_sampled = is_sampled
        self.sample_size = sample_size
        self.correlate = correlate
        self._profile = None
        self._encoding = "utf-8"
        self._delimiter = ","
        self._quotechar = '"'
        self._escapechar = "\0"
        self._requested_delimiter = delimiter
        if quotechar is not None and quote_char is not None and quotechar != quote_char:
            raise ValueError("quotechar and quote_char specify different values")
        self._requested_quotechar = quotechar if quotechar is not None else quote_char
        self._requested_escapechar = escapechar
        self._requested_encoding = encoding
        self._row_count = 0
        self._col_count = 0

    def open(self) -> None:
        if not os.path.exists(self.path):
            raise FileNotFoundError(f"File not found: {self.path}")

        def _validate_char(value: str | None, name: str) -> str | None:
            if value is not None and len(value) != 1:
                raise ValueError(f"{name} must be exactly one character")
            return value

        _validate_char(self._requested_delimiter, "delimiter")
        _validate_char(self._requested_quotechar, "quotechar")
        _validate_char(self._requested_escapechar, "escapechar")
        if self._requested_encoding not in (
            None,
            "auto",
            "utf-8",
            "utf-8-sig",
            "utf-16",
            "utf-16-le",
            "utf-16-be",
        ):
            raise ValueError(
                "encoding must be one of auto, utf-8, utf-8-sig, utf-16, "
                "utf-16-le, or utf-16-be"
            )

        # Detect BOM and encoding. Native parsing also receives the result.
        with open(self.path, "rb") as f:
            raw = f.read(4)
            if raw.startswith(b"\xef\xbb\xbf"):
                self._encoding = "utf-8-sig"
            elif raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
                self._encoding = "utf-16"
        if self._requested_encoding not in (None, "auto"):
            self._encoding = self._requested_encoding

        # Sniff delimiter and quotechar
        try:
            with open(self.path, encoding=self._encoding) as f:
                sample = f.read(1024 * 10)
                sniffer = csv.Sniffer()
                if sample:
                    dialect = sniffer.sniff(sample, delimiters=",\t;|:")
                    if self._requested_delimiter is None and dialect.delimiter in (
                        ",",
                        "\t",
                        ";",
                        "|",
                        ":",
                    ):
                        self._delimiter = dialect.delimiter
                    if self._requested_quotechar is None:
                        self._quotechar = dialect.quotechar
                    if self._requested_escapechar is None:
                        self._escapechar = dialect.escapechar or "\0"
        except Exception:
            pass  # fallback to defaults

        if self._requested_delimiter is not None:
            self._delimiter = self._requested_delimiter
        if self._requested_quotechar is not None:
            self._quotechar = self._requested_quotechar
        if self._requested_escapechar is not None:
            self._escapechar = self._requested_escapechar

        # The native parser is byte-oriented. Normalize UTF-16 into a private
        # UTF-8 file before delegation; ordinary UTF-8 keeps the mmap fast path.
        profile_path = self.path
        temp_path = None
        try:
            if self._encoding in ("utf-16", "utf-16-le", "utf-16-be"):
                temp_fd, temp_path = tempfile.mkstemp(suffix=".csv")
                with (
                    os.fdopen(temp_fd, "w", encoding="utf-8", newline="") as output,
                    open(self.path, encoding=self._encoding, newline="") as source,
                ):
                    output.write(source.read())

                profile_path = temp_path

            # We delegate actual profiling to the C++ core because doing it in
            # Python row-by-row is too slow.
            try:
                self._profile = _core.profile(
                    profile_path,
                    False,
                    self.is_sampled,
                    self.sample_size,
                    self.correlate,
                    ord(self._delimiter),
                    ord(self._quotechar),
                    ord(self._escapechar) if self._escapechar != "\0" else 0,
                    "utf-8" if temp_path else self._encoding,
                )
            except RuntimeError as e:
                from .._errors import ZeddaError
                raise ZeddaError(str(e))
        finally:
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except FileNotFoundError:
                    pass

        self._profile.file_name = os.path.basename(self.path)
        self._profile.file_path = self.path
        self._row_count = self._profile.num_rows
        self._col_count = self._profile.num_cols

    def schema(self) -> DatasetSchema:
        if not self._profile:
            self.open()

        cols = []
        for c in self._profile.columns:
            # Map C++ type string to DataType enum
            cols.append(
                ColumnSchema(name=c.name, type=DataType.from_string(c.type_str))
            )
        return DatasetSchema(columns=cols)

    def coverage(self) -> InputMeta:
        if not self._profile:
            self.open()

        return InputMeta(
            source_path=self.path,
            source_type="file",
            format="csv",
            row_count=self._row_count,
            column_count=self._col_count,
            coverage_fraction=1.0
            if not self.is_sampled
            else min(1.0, self.sample_size / max(1, self._row_count)),
            unsupported_types=sorted(
                {
                    unsupported
                    for column in self._profile.columns
                    for unsupported in getattr(column, "unsupported_types", [])
                }
            ),
        )

    def records(self) -> Iterator[LogicalRecord]:
        """
        C++-kernel-delegation pattern — NOT implemented for CSV.

        CSV profiling is fully delegated to the C++ ProfileBuilder in open().
        Calling this method intentionally raises NotImplementedError.

        This is the documented, tested behavior for kernel-delegating adapters.
        See InputAdapter class docstring for the two valid adapter patterns.

        Raises:
            NotImplementedError: Always. Use schema() and coverage() to obtain
                results after open(). The C++ kernel has already computed all
                statistics during open().
        """
        raise NotImplementedError(
            "CSVAdapter delegates profiling to the C++ kernel (fasteda_core.profile). "
            "Row-level iteration is not available; use schema() and coverage() to obtain "
            "results. See InputAdapter docstring for the kernel-delegation contract."
        )

    def close(self) -> None:
        self._profile = None
