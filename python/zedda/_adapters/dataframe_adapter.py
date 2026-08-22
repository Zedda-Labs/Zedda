from typing import Iterator, Any

from . import InputAdapter
from .._schema import DatasetSchema, ColumnSchema, DataType, LogicalRecord
from .._models import InputMeta


class DataFrameAdapter(InputAdapter):
    """
    DataFrame InputAdapter — Python-row-iterator pattern.

    Wraps an in-memory DataFrame (currently Pandas only) into the InputAdapter
    contract. Coverage is always EXACT (full materialized data). Schema is
    extracted from DataFrame dtypes and mapped to canonical DataType.

    **Polars support:** The Phase 3 task description mentions pandas/polars, but the
    Phase 3 Definition of Done only requires pandas. Polars support is formally
    DEFERRED to Phase 4/5. Passing a Polars DataFrame raises ``NotImplementedError``
    with an explicit deferral message.

    Delegation contract:
    - ``open()``     → no-op (data already in memory)
    - ``schema()``   → extracted from DataFrame dtypes
    - ``coverage()`` → EXACT (full row count, all columns)
    - ``records()``  → yields LogicalRecord per row (Python-row-iterator pattern)
    - ``close()``    → no-op
    """
    supported_types = ["dataframe"]
    unsupported_types = []

    def __init__(self, df: Any):
        self.df = df

        # Check if pandas
        self._is_pandas = hasattr(df, "columns") and hasattr(df, "dtypes") and hasattr(df, "itertuples")
        if not self._is_pandas:
            # Polars DataFrames have .columns but no .itertuples; detect and give explicit message.
            if hasattr(df, "columns") and hasattr(df, "dtypes"):
                raise NotImplementedError(
                    "Polars DataFrame support in DataFrameAdapter is deferred to Phase 4/5. "
                    "Convert to Pandas with df.to_pandas() as a workaround, or await Phase 4."
                )
            raise TypeError(
                "DataFrameAdapter requires a Pandas DataFrame. "
                "Polars support is deferred to Phase 4/5."
            )

    def open(self) -> None:
        pass

    def schema(self) -> DatasetSchema:
        cols = []
        for col_name, dtype in zip(self.df.columns, self.df.dtypes):
            type_str = str(dtype).lower()
            
            # Map pandas dtypes to canonical DataType
            dt = DataType.UNKNOWN
            if "int8" in type_str: dt = DataType.INT8
            elif "int16" in type_str: dt = DataType.INT16
            elif "int32" in type_str: dt = DataType.INT32
            elif "int64" in type_str or "int" in type_str: dt = DataType.INT64
            elif "uint8" in type_str: dt = DataType.UINT8
            elif "uint16" in type_str: dt = DataType.UINT16
            elif "uint32" in type_str: dt = DataType.UINT32
            elif "uint64" in type_str: dt = DataType.UINT64
            elif "float16" in type_str: dt = DataType.FLOAT16
            elif "float32" in type_str: dt = DataType.FLOAT32
            elif "float64" in type_str or "float" in type_str: dt = DataType.FLOAT64
            elif "bool" in type_str: dt = DataType.BOOLEAN
            elif "datetime" in type_str or "timestamp" in type_str: dt = DataType.TIMESTAMP
            elif "date" in type_str: dt = DataType.DATE
            elif "timedelta" in type_str or "time" in type_str: dt = DataType.TIME
            elif "object" in type_str or "string" in type_str: dt = DataType.STRING
            elif "category" in type_str: dt = DataType.STRING
            
            cols.append(ColumnSchema(
                name=str(col_name),
                type=dt
            ))
        return DatasetSchema(columns=cols)

    def coverage(self) -> InputMeta:
        return InputMeta(
            source_path="<dataframe>",
            source_type="memory",
            format="dataframe",
            row_count=len(self.df),
            column_count=len(self.df.columns),
            coverage_fraction=1.0,
            unsupported_types=[]
        )

    def records(self) -> Iterator[LogicalRecord]:
        """
        Yields rows as LogicalRecords.
        For dataframes, we may also just convert to Arrow and pass to C++ kernel,
        but providing the iterator fulfills the contract.
        """
        for i, row in enumerate(self.df.itertuples(index=False)):
            yield LogicalRecord(
                row_index=i,
                values=row._asdict()
            )

    def close(self) -> None:
        pass
