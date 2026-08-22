from typing import Iterator, Any

from . import InputAdapter
from .._schema import DatasetSchema, ColumnSchema, DataType, LogicalRecord
from .._models import InputMeta


class DataFrameAdapter(InputAdapter):
    supported_types = ["dataframe"]
    
    def __init__(self, df: Any):
        self.df = df
        
        # Check if pandas
        self._is_pandas = hasattr(df, "columns") and hasattr(df, "dtypes")
        if not self._is_pandas:
            raise TypeError("Only Pandas DataFrames are currently supported in DataFrameAdapter.")

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
