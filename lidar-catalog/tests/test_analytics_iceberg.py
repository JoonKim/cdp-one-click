"""Catalog intersection through local Spark + Iceberg, then a small canopy summary."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from lidar_catalog.analytics import Box, IcebergCatalogIndex, canopy_density
from lidar_catalog.models import CatalogRow
from lidar_catalog.stores import ICEBERG_SPARK_EXTENSIONS, IcebergSparkCatalogStore

pytest.importorskip("pyspark")

NOW = datetime(2026, 11, 5, 16, 30, tzinfo=timezone.utc)


def test_iceberg_catalog_intersection_then_canopy_summary(tmp_path: Path) -> None:
    from pyspark.sql import SparkSession

    active = SparkSession.getActiveSession()
    if active is not None:
        active.stop()

    inside = tmp_path / "inside.copc.laz"
    outside = tmp_path / "outside.copc.laz"
    inside.write_bytes(b"in")
    outside.write_bytes(b"out")
    store = IcebergSparkCatalogStore(warehouse=tmp_path / "warehouse")
    try:
        store.append(
            CatalogRow(
                dataset_source="USGS",
                file_name="inside.copc.laz",
                file_path=str(inside),
                min_x=0,
                min_y=0,
                max_x=10,
                max_y=10,
                point_count=20,
                ingest_timestamp=NOW,
            )
        )
        store.append(
            CatalogRow(
                dataset_source="OpenTopography",
                file_name="outside.copc.laz",
                file_path=str(outside),
                min_x=100,
                min_y=100,
                max_x=110,
                max_y=110,
                point_count=50,
                ingest_timestamp=NOW,
            )
        )
        assert ICEBERG_SPARK_EXTENSIONS in store.spark.conf.get("spark.sql.extensions")
        index = IcebergCatalogIndex(spark=store.spark)
        hits = index.intersecting(Box(9, 9, 12, 12))
        assert [row.file_path for row in hits] == [str(inside)]

        def counts(path: Path, box: Box) -> dict[int, int]:
            assert path == inside
            assert box.min_x == 9
            return {2: 3, 4: 1}

        result = canopy_density(Box(9, 9, 12, 12), index, crop_counts=counts)
        assert result.file_count == 1
        assert result.total_points == 4
        assert result.canopy_points == 1
        assert result.canopy_density == pytest.approx(0.25)
        assert result.files[0].dataset_source == "USGS"
        assert "lidar_points" not in json_tables(store.spark)
    finally:
        if store._spark is not None:
            store._spark.stop()


def json_tables(spark: object) -> set[str]:
    listed = spark.sql("SHOW TABLES IN default").collect()  # type: ignore[attr-defined]
    return {row["tableName"] for row in listed}
