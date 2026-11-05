"""Catalog writers.

``IcebergSparkCatalogStore`` appends with Spark's Iceberg writer.
``LocalJsonCatalogStore`` writes the same row to a JSON lines file so the
catalog append can be proven without a Cloudera cluster or a Spark session.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from lidar_catalog.models import TABLE_NAME, CatalogRow

ICEBERG_SPARK_EXTENSIONS = (
    "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions"
)
ICEBERG_SPARK_PACKAGE = "org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.7.2"
SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


class CatalogStore(Protocol):
    def append(self, row: CatalogRow) -> None:
        """Append one catalog row."""


class LocalJsonCatalogStore:
    """Append catalog rows as JSON lines. One object, the same columns as Iceberg."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def append(self, row: CatalogRow) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row.as_dict()) + "\n")


class IcebergSparkCatalogStore:
    """Append into ``default.lidar_catalog`` with format ``iceberg`` and mode ``append``."""

    def __init__(
        self,
        *,
        warehouse: str | Path | None = None,
        spark: object | None = None,
        table: str = TABLE_NAME,
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

    def append(self, row: CatalogRow) -> None:
        spark = self.spark
        extensions = spark.conf.get("spark.sql.extensions", "")  # type: ignore[attr-defined]
        if ICEBERG_SPARK_EXTENSIONS not in extensions:
            raise RuntimeError(
                "Spark session is missing "
                f"spark.sql.extensions={ICEBERG_SPARK_EXTENSIONS}"
            )
        self._ensure_table(spark)
        frame = spark.createDataFrame([_spark_values(row)], schema=_schema())  # type: ignore[attr-defined]
        frame.write.format("iceberg").mode("append").save(self.table)

    def _ensure_table(self, spark: object) -> None:
        if self._table_ready:
            return
        spark.sql("CREATE NAMESPACE IF NOT EXISTS default")  # type: ignore[attr-defined]
        ddl = (SQL_DIR / "lidar_catalog_spark.sql").read_text(encoding="utf-8")
        spark.sql(_single_statement(ddl))  # type: ignore[attr-defined]
        self._table_ready = True


def build_local_spark(warehouse: str) -> object:
    """Local Spark session with the Iceberg Spark extensions and a Hadoop catalog."""
    _ensure_java_home()
    from pyspark.sql import SparkSession

    warehouse_path = str(Path(warehouse).resolve())
    return (
        SparkSession.builder.master("local[1]")
        .appName("lidar-catalog-ingest")
        .config("spark.sql.extensions", ICEBERG_SPARK_EXTENSIONS)
        .config("spark.sql.catalog.local", "org.apache.iceberg.spark.SparkCatalog")
        .config("spark.sql.catalog.local.type", "hadoop")
        .config("spark.sql.catalog.local.warehouse", warehouse_path)
        .config("spark.sql.defaultCatalog", "local")
        .config("spark.sql.catalogImplementation", "in-memory")
        .config("spark.sql.warehouse.dir", warehouse_path)
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.jars.packages", ICEBERG_SPARK_PACKAGE)
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "1")
        .config("spark.driver.host", "127.0.0.1")
        .config(
            "spark.driver.extraJavaOptions",
            f"-Dderby.system.home={warehouse_path}",
        )
        .getOrCreate()
    )


def _ensure_java_home() -> None:
    if os.environ.get("JAVA_HOME"):
        return
    for candidate in (
        Path("/usr/lib/jvm/java-21-openjdk-amd64"),
        Path("/usr/lib/jvm/default-java"),
    ):
        if candidate.is_dir():
            os.environ["JAVA_HOME"] = str(candidate)
            return


def _schema() -> object:
    from pyspark.sql.types import (
        DoubleType,
        LongType,
        StringType,
        StructField,
        StructType,
        TimestampType,
    )

    return StructType(
        [
            StructField("dataset_source", StringType(), True),
            StructField("file_name", StringType(), True),
            StructField("file_path", StringType(), True),
            StructField("min_x", DoubleType(), True),
            StructField("min_y", DoubleType(), True),
            StructField("max_x", DoubleType(), True),
            StructField("max_y", DoubleType(), True),
            StructField("point_count", LongType(), True),
            StructField("ingest_timestamp", TimestampType(), True),
        ]
    )


def _spark_values(row: CatalogRow) -> tuple[object, ...]:
    timestamp = row.ingest_timestamp
    if timestamp.tzinfo is not None:
        from datetime import timezone

        timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
    return (
        row.dataset_source,
        row.file_name,
        row.file_path,
        float(row.min_x),
        float(row.min_y),
        float(row.max_x),
        float(row.max_y),
        int(row.point_count),
        timestamp,
    )


def _single_statement(sql_text: str) -> str:
    statement = sql_text.strip()
    if statement.endswith(";"):
        statement = statement[:-1].strip()
    return statement
