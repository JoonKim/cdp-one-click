"""Writers for default.lidar_points.

``IcebergSparkPointStore`` appends zstd-compressed Parquet through Spark's
Iceberg writer. The table is partitioned by ``h3_index``.
``LocalJsonPointStore`` writes the same rows as JSON lines so a small flatten
can be proven without a Cloudera cluster or a Spark session.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import timezone
from pathlib import Path
from typing import Protocol

from lidar_catalog.points import POINT_COLUMNS, POINTS_TABLE, PointRow
from lidar_catalog.stores import (
    ICEBERG_SPARK_EXTENSIONS,
    SQL_DIR,
    build_local_spark,
)


class PointStore(Protocol):
    def append(self, rows: Sequence[PointRow]) -> None:
        """Append point rows."""


class LocalJsonPointStore:
    """Append point rows as JSON lines, one object per point."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def append(self, rows: Sequence[PointRow]) -> None:
        if not rows:
            raise ValueError("refusing to append an empty point batch")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row.as_dict()) + "\n")


class IcebergSparkPointStore:
    """Append into ``default.lidar_points`` with format ``iceberg`` and mode ``append``."""

    def __init__(
        self,
        *,
        warehouse: str | Path | None = None,
        spark: object | None = None,
        table: str = POINTS_TABLE,
    ) -> None:
        if spark is None and warehouse is None:
            raise ValueError("warehouse is required to start a local Spark session")
        self.warehouse = None if warehouse is None else str(Path(warehouse).resolve())
        self._spark = spark
        self.table = table
        self._table_ready = False

    @property
    def spark(self) -> object:
        if self._spark is None:
            self._spark = build_local_spark(self.warehouse or "")
        return self._spark

    def append(self, rows: Sequence[PointRow]) -> None:
        if not rows:
            raise ValueError("refusing to append an empty point batch")
        spark = self.spark
        extensions = spark.conf.get("spark.sql.extensions", "")  # type: ignore[attr-defined]
        if ICEBERG_SPARK_EXTENSIONS not in extensions:
            raise RuntimeError(
                "Spark session is missing "
                f"spark.sql.extensions={ICEBERG_SPARK_EXTENSIONS}"
            )
        self._ensure_table(spark)
        ordered = sorted(rows, key=lambda row: row.h3_index)
        frame = spark.createDataFrame(  # type: ignore[attr-defined]
            [_spark_values(row) for row in ordered],
            schema=_schema(),
        )
        frame.write.format("iceberg").mode("append").save(self.table)

    def _ensure_table(self, spark: object) -> None:
        if self._table_ready:
            return
        spark.sql("CREATE NAMESPACE IF NOT EXISTS default")  # type: ignore[attr-defined]
        ddl = (SQL_DIR / "lidar_points_spark.sql").read_text(encoding="utf-8")
        spark.sql(_single_statement(ddl))  # type: ignore[attr-defined]
        self._table_ready = True


def _schema() -> object:
    from pyspark.sql.types import (
        DoubleType,
        IntegerType,
        LongType,
        StringType,
        StructField,
        StructType,
        TimestampType,
    )

    return StructType(
        [
            StructField("h3_index", LongType(), False),
            StructField("h3_resolution", IntegerType(), False),
            StructField("x", DoubleType(), False),
            StructField("y", DoubleType(), False),
            StructField("z", DoubleType(), False),
            StructField("longitude", DoubleType(), False),
            StructField("latitude", DoubleType(), False),
            StructField("classification", IntegerType(), True),
            StructField("intensity", IntegerType(), True),
            StructField("return_number", IntegerType(), True),
            StructField("number_of_returns", IntegerType(), True),
            StructField("file_path", StringType(), False),
            StructField("dataset_source", StringType(), False),
            StructField("ingest_timestamp", TimestampType(), False),
        ]
    )


def _spark_values(row: PointRow) -> tuple[object, ...]:
    timestamp = row.ingest_timestamp
    if timestamp.tzinfo is not None:
        timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
    values = row.as_dict()
    values["ingest_timestamp"] = timestamp
    return tuple(values[column] for column in POINT_COLUMNS)


def _single_statement(sql_text: str) -> str:
    statement = sql_text.strip()
    if statement.endswith(";"):
        statement = statement[:-1].strip()
    return statement
