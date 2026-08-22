import csv
import os
from typing import Iterator

from . import InputAdapter
from .._schema import DatasetSchema, ColumnSchema, DataType, LogicalRecord
from .._models import InputMeta
from .. import fasteda_core as _core


class CSVAdapter(InputAdapter):
    supported_types = ["csv", "txt", "tsv"]
    
    def __init__(self, path: str, is_sampled: bool = False, sample_size: int = 1000000):
        self.path = path
        self.is_sampled = is_sampled
        self.sample_size = sample_size
        self._profile = None
        self._encoding = "utf-8"
        self._delimiter = ","
        self._quotechar = '"'
        self._row_count = 0
        self._col_count = 0

    def open(self) -> None:
        if not os.path.exists(self.path):
            raise FileNotFoundError(f"File not found: {self.path}")
            
        # Detect BOM and encoding
        with open(self.path, "rb") as f:
            raw = f.read(4)
            if raw.startswith(b"\xef\xbb\xbf"):
                self._encoding = "utf-8-sig"
            elif raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
                self._encoding = "utf-16"
                
        # Sniff delimiter and quotechar
        try:
            with open(self.path, "r", encoding=self._encoding) as f:
                sample = f.read(1024 * 10)
                sniffer = csv.Sniffer()
                if sample:
                    dialect = sniffer.sniff(sample)
                    self._delimiter = dialect.delimiter
                    self._quotechar = dialect.quotechar
        except Exception:
            pass # fallback to defaults

        # We delegate the actual profiling to the C++ core
        # because doing it in Python row-by-row is too slow.
        self._profile = _core.profile(self.path, False, self.is_sampled, self.sample_size, False)
        self._row_count = self._profile.num_rows
        self._col_count = self._profile.num_cols

    def schema(self) -> DatasetSchema:
        if not self._profile:
            self.open()
            
        cols = []
        for c in self._profile.columns:
            # Map C++ type string to DataType enum
            cols.append(ColumnSchema(
                name=c.name,
                type=DataType.from_string(c.type_str)
            ))
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
            coverage_fraction=1.0 if not self.is_sampled else min(1.0, self.sample_size / max(1, self._row_count)),
            unsupported_types=[]
        )

    def records(self) -> Iterator[LogicalRecord]:
        """
        The CSV adapter delegates heavy lifting to the C++ kernel.
        Normally, this would yield logical records, but for CSV, the C++ 
        ProfileBuilder handles boundary detection and parsing internally.
        """
        raise NotImplementedError("CSV scanning is delegated to the C++ kernel.")

    def close(self) -> None:
        self._profile = None
