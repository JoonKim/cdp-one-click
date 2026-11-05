"""Point flatten. PDAL is mocked; H3 ids come from the h3 library.

A live unpack runs only when PDAL is installed and LIDAR_SAMPLE points at a
tile that has a spatial reference.
"""

from __future__ import annotations

import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import h3
import pytest

from lidar_catalog.flatten import flatten_tile, main
from lidar_catalog.point_stores import LocalJsonPointStore
from lidar_catalog.points import H3_RESOLUTION, POINT_COLUMNS, points_from_arrays

NOW = datetime(2026, 11, 5, 16, 20, tzinfo=timezone.utc)
SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


class _Array:
    def __init__(self, columns: dict[str, list[object]]) -> None:
        self.dtype = type("Dtype", (), {"names": tuple(columns)})()
        self._columns = columns

    def __getitem__(self, key: str) -> list[object]:
        return self._columns[key]

    def __len__(self) -> int:
        return len(next(iter(self._columns.values())))


def _array() -> _Array:
    return _Array(
        {
            "X": [-123.07],
            "Y": [44.05],
            "Z": [120.0],
            "Xnative": [635619.85],
            "Ynative": [848899.7],
            "Znative": [406.59],
            "Classification": [2],
            "Intensity": [12],
            "ReturnNumber": [1],
            "NumberOfReturns": [1],
        }
    )


def test_resolution_nine_uses_latitude_longitude_order() -> None:
    rows = points_from_arrays(
        [_array()],
        file_path="ofs://ozone/bucket/lidar/tile.copc.laz",
        dataset_source="USGS",
        now=NOW,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.h3_resolution == H3_RESOLUTION == 9
    assert row.h3_index == h3.str_to_int(h3.latlng_to_cell(44.05, -123.07, 9))
    assert row.x == pytest.approx(635619.85)
    assert row.y == pytest.approx(848899.7)
    assert row.z == pytest.approx(406.59)
    assert row.longitude == pytest.approx(-123.07)
    assert row.latitude == pytest.approx(44.05)
    assert row.classification == 2
    assert row.file_path == "ofs://ozone/bucket/lidar/tile.copc.laz"
    assert list(row.as_dict()) == list(POINT_COLUMNS)


def test_latitude_outside_range_is_rejected() -> None:
    # Y=-123 is not a latitude. That is the swapped-axis failure mode.
    array = _array()
    array._columns["Y"] = [-123.0]
    array._columns["X"] = [44.05]
    with pytest.raises(ValueError, match="longitude/latitude"):
        points_from_arrays(
            [array],
            file_path="tile.laz",
            dataset_source="USGS",
            now=NOW,
        )


def test_local_flatten_appends_points_and_leaves_catalog_alone(monkeypatch, tmp_path: Path) -> None:
    tile = tmp_path / "tile.copc.laz"
    tile.write_bytes(b"laz")
    catalog = tmp_path / "lidar_catalog.jsonl"

    def fake_read(path: Path, **kwargs: object) -> list:
        assert path == tile
        assert kwargs["file_path"] == "ofs://ozone/bucket/lidar/tile.copc.laz"
        assert kwargs["limit"] == 2
        return points_from_arrays(
            [_array()],
            file_path=str(kwargs["file_path"]),
            dataset_source=str(kwargs["dataset_source"]),
            now=NOW,
        )

    monkeypatch.setattr("lidar_catalog.flatten.read_points", fake_read)
    store = LocalJsonPointStore(tmp_path / "lidar_points.jsonl")
    result = flatten_tile(
        str(tile),
        "USGS",
        store,
        object_path="ofs://ozone/bucket/lidar/tile.copc.laz",
        limit=2,
        now=NOW,
    )
    lines = store.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    saved = json.loads(lines[0])
    assert saved["h3_resolution"] == 9
    assert saved["h3_index"] == h3.str_to_int(h3.latlng_to_cell(44.05, -123.07, 9))
    assert result.points_written == 1
    assert result.h3_cell_count == 1
    assert result.h3_resolution == 9
    assert not catalog.exists()


def test_cli_local_limit(monkeypatch, tmp_path: Path, capsys) -> None:
    tile = tmp_path / "tile.laz"
    tile.write_bytes(b"laz")

    def fake_read(path: Path, **kwargs: object) -> list:
        del path
        return points_from_arrays(
            [_array()],
            file_path=str(kwargs["file_path"]),
            dataset_source=str(kwargs["dataset_source"]),
            now=NOW,
        )

    monkeypatch.setattr("lidar_catalog.flatten.read_points", fake_read)
    points_path = tmp_path / "points.jsonl"
    code = main(
        [
            "--source",
            str(tile),
            "--dataset-source",
            "OpenTopography",
            "--store",
            "local",
            "--points-path",
            str(points_path),
            "--limit",
            "2",
        ]
    )
    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["points_written"] == 1
    assert summary["h3_resolution"] == 9
    assert points_path.is_file()


def test_missing_crs_message_from_metadata(monkeypatch, tmp_path: Path) -> None:
    tile = tmp_path / "plain.las"
    tile.write_bytes(b"las")
    monkeypatch.setattr(
        "lidar_catalog.points.read_pdal_metadata",
        lambda path: json.loads(
            (Path(__file__).parent / "fixtures" / "pdal_pipeline_readers_las.json").read_text()
        ),
    )
    from lidar_catalog.points import read_points

    with pytest.raises(ValueError, match="no spatial reference"):
        read_points(tile, file_path=str(tile), dataset_source="USGS", limit=1)


def test_point_ddl_records_resolution_nine_and_zstd() -> None:
    hive = (SQL_DIR / "lidar_points.sql").read_text(encoding="utf-8")
    spark = (SQL_DIR / "lidar_points_spark.sql").read_text(encoding="utf-8")
    assert "PARTITIONED BY (h3_index BIGINT)" in hive
    assert "PARTITIONED BY (h3_index)" in spark
    assert "STORED AS ICEBERG" in hive
    assert "USING iceberg" in spark
    for text in (hive, spark):
        assert "write.parquet.compression-codec" in text
        assert "zstd" in text
        assert "'h3.resolution'='9'" in text.replace(" ", "") or "'h3.resolution' = '9'" in text
    assert "default.lidar_catalog" not in hive
    assert "default.lidar_points" in hive


@pytest.mark.skipif(importlib.util.find_spec("pdal") is None, reason="PDAL Python module is not installed")
def test_live_pdal_flatten_sample() -> None:
    sample = os.environ.get("LIDAR_SAMPLE")
    if not sample:
        pytest.skip("Set LIDAR_SAMPLE to a CRS-backed LAS, LAZ, or COPC path")
    from lidar_catalog.points import read_points

    rows = read_points(
        Path(sample),
        file_path=sample,
        dataset_source="USGS",
        limit=5,
        now=NOW,
    )
    assert 1 <= len(rows) <= 5
    assert all(row.h3_resolution == 9 for row in rows)
    assert all(-180 <= row.longitude <= 180 for row in rows)
    assert all(-90 <= row.latitude <= 90 for row in rows)
