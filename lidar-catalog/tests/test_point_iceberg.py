"""Local Spark + Iceberg append of H3-partitioned points."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import h3
import pytest

from lidar_catalog.points import H3_RESOLUTION, PointRow
from lidar_catalog.point_stores import IcebergSparkPointStore
from lidar_catalog.stores import ICEBERG_SPARK_EXTENSIONS

pytest.importorskip("pyspark")

NOW = datetime(2026, 11, 5, 16, 20, tzinfo=timezone.utc)


def _row(latitude: float, longitude: float, *, file_path: str) -> PointRow:
    return PointRow(
        h3_index=h3.str_to_int(h3.latlng_to_cell(latitude, longitude, H3_RESOLUTION)),
        h3_resolution=H3_RESOLUTION,
        x=100.0,
        y=200.0,
        z=30.0,
        longitude=longitude,
        latitude=latitude,
        classification=2,
        intensity=10,
        return_number=1,
        number_of_returns=1,
        file_path=file_path,
        dataset_source="USGS",
        ingest_timestamp=NOW,
    )


def test_local_spark_appends_partitioned_compressed_points(tmp_path: Path) -> None:
    from pyspark.sql import SparkSession

    active = SparkSession.getActiveSession()
    if active is not None:
        active.stop()

    warehouse = tmp_path / "warehouse"
    store = IcebergSparkPointStore(warehouse=warehouse)
    eugene = _row(44.05, -123.07, file_path="ofs://ozone/bucket/lidar/a.copc.laz")
    portland = _row(45.52, -122.68, file_path="ofs://ozone/bucket/lidar/a.copc.laz")
    assert eugene.h3_index != portland.h3_index
    try:
        store.append([portland, eugene])
        spark = store.spark
        assert ICEBERG_SPARK_EXTENSIONS in spark.conf.get("spark.sql.extensions")
        props = {
            row["key"]: row["value"]
            for row in spark.sql("SHOW TBLPROPERTIES default.lidar_points").collect()
        }
        assert props["write.parquet.compression-codec"] == "zstd"
        assert props["h3.resolution"] == "9"
        got = spark.sql(
            "SELECT h3_index, h3_resolution, latitude, file_path "
            "FROM default.lidar_points ORDER BY latitude"
        ).collect()
        assert len(got) == 2
        assert got[0]["h3_index"] == eugene.h3_index
        assert got[1]["h3_index"] == portland.h3_index
        assert all(row["h3_resolution"] == 9 for row in got)
        assert got[0]["file_path"] == "ofs://ozone/bucket/lidar/a.copc.laz"
        catalog = spark.sql("SHOW TABLES IN default").collect()
        names = {row["tableName"] for row in catalog}
        assert "lidar_points" in names
        assert "lidar_catalog" not in names
    finally:
        spark_session = store._spark
        if spark_session is not None:
            spark_session.stop()
