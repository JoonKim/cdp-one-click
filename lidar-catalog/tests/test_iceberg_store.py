"""Local Spark + Iceberg append. Skipped when PySpark is not installed."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from lidar_catalog.models import CatalogRow
from lidar_catalog.stores import ICEBERG_SPARK_EXTENSIONS, IcebergSparkCatalogStore

pytest.importorskip("pyspark")


def test_local_spark_iceberg_append(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse"
    store = IcebergSparkCatalogStore(warehouse=warehouse)
    row = CatalogRow(
        dataset_source="USGS",
        file_name="tile.copc.laz",
        file_path="ofs://ozone/bucket/lidar/tile.copc.laz",
        min_x=635619.85,
        min_y=848899.7,
        max_x=638982.55,
        max_y=853535.43,
        point_count=1065,
        ingest_timestamp=datetime(2026, 11, 5, 16, 3, tzinfo=timezone.utc),
    )
    try:
        store.append(row)
        store.append(row)
        spark = store.spark
        assert ICEBERG_SPARK_EXTENSIONS in spark.conf.get("spark.sql.extensions")
        got = spark.sql("SELECT * FROM default.lidar_catalog ORDER BY file_name").collect()
        assert len(got) == 2
        assert got[0]["dataset_source"] == "USGS"
        assert got[0]["file_name"] == "tile.copc.laz"
        assert got[0]["file_path"] == "ofs://ozone/bucket/lidar/tile.copc.laz"
        assert got[0]["min_x"] == pytest.approx(635619.85)
        assert got[0]["max_y"] == pytest.approx(853535.43)
        assert got[0]["point_count"] == 1065
        assert got[0]["ingest_timestamp"] == datetime(2026, 11, 5, 16, 3)
        assert list(warehouse.rglob("*.metadata.json"))
    finally:
        spark_session = store._spark
        if spark_session is not None:
            spark_session.stop()
