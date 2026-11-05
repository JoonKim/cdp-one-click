"""Ingest orchestration with the local JSON catalog store and a mocked PDAL header."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from lidar_catalog.ingest import ingest
from lidar_catalog.models import CATALOG_COLUMNS, PointCloudHeader
from lidar_catalog.stores import LocalJsonCatalogStore
from lidar_catalog.__main__ import main

NOW = datetime(2026, 11, 5, 16, 3, tzinfo=timezone.utc)
HEADER = PointCloudHeader(
    min_x=635619.85,
    min_y=848899.7,
    max_x=638982.55,
    max_y=853535.43,
    point_count=1065,
)


def _patch_header(monkeypatch) -> None:
    monkeypatch.setattr("lidar_catalog.ingest.extract_header", lambda path: HEADER)


def test_local_file_appends_one_row(monkeypatch, tmp_path: Path) -> None:
    _patch_header(monkeypatch)
    tile = tmp_path / "tile.copc.laz"
    tile.write_bytes(b"laz")
    catalog = tmp_path / "catalog.jsonl"
    store = LocalJsonCatalogStore(catalog)

    row = ingest(str(tile), "USGS", store, now=NOW)

    lines = catalog.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    saved = json.loads(lines[0])
    assert list(saved) == list(CATALOG_COLUMNS)
    assert saved["dataset_source"] == "USGS"
    assert saved["file_name"] == "tile.copc.laz"
    assert saved["file_path"] == str(tile.resolve())
    assert saved["point_count"] == 1065
    assert saved["min_x"] == 635619.85
    assert saved["ingest_timestamp"] == NOW.isoformat()
    assert row.file_path == saved["file_path"]


def test_second_append_does_not_overwrite(monkeypatch, tmp_path: Path) -> None:
    _patch_header(monkeypatch)
    tile = tmp_path / "tile.laz"
    tile.write_bytes(b"laz")
    store = LocalJsonCatalogStore(tmp_path / "catalog.jsonl")
    ingest(str(tile), "OpenTopography", store, now=NOW)
    ingest(str(tile), "OpenTopography", store, now=NOW)
    assert len((tmp_path / "catalog.jsonl").read_text(encoding="utf-8").splitlines()) == 2


def test_object_path_is_the_catalog_file_path(monkeypatch, tmp_path: Path) -> None:
    _patch_header(monkeypatch)
    tile = tmp_path / "staged.copc.laz"
    tile.write_bytes(b"laz")
    store = LocalJsonCatalogStore(tmp_path / "catalog.jsonl")
    row = ingest(
        str(tile),
        "USGS",
        store,
        object_path="ofs://ozone/bucket/lidar/staged.copc.laz",
        now=NOW,
    )
    assert row.file_path == "ofs://ozone/bucket/lidar/staged.copc.laz"
    assert row.file_name == "staged.copc.laz"


def test_failed_download_does_not_append(monkeypatch, tmp_path: Path) -> None:
    def explode(source: str, download_dir: Path | None):
        del source, download_dir
        raise requests.HTTPError("404 Client Error")

    monkeypatch.setattr("lidar_catalog.ingest.materialize_source", explode)
    store = LocalJsonCatalogStore(tmp_path / "catalog.jsonl")
    with pytest.raises(requests.HTTPError):
        ingest("https://example.com/missing.copc.laz", "USGS", store, now=NOW)
    assert not store.path.exists()


def test_unknown_dataset_source(tmp_path: Path) -> None:
    tile = tmp_path / "tile.laz"
    tile.write_bytes(b"laz")
    store = LocalJsonCatalogStore(tmp_path / "catalog.jsonl")
    with pytest.raises(ValueError, match="dataset_source"):
        ingest(str(tile), "somewhere", store)
    assert not store.path.exists()


def test_cli_local_store(monkeypatch, tmp_path: Path, capsys) -> None:
    _patch_header(monkeypatch)
    tile = tmp_path / "tile.copc.laz"
    tile.write_bytes(b"laz")
    catalog = tmp_path / "catalog.jsonl"
    code = main(
        [
            "--source",
            str(tile),
            "--dataset-source",
            "USGS",
            "--store",
            "local",
            "--catalog-path",
            str(catalog),
        ]
    )
    assert code == 0
    saved = json.loads(catalog.read_text(encoding="utf-8").splitlines()[0])
    assert saved["point_count"] == 1065
    printed = json.loads(capsys.readouterr().out)
    assert printed["file_name"] == "tile.copc.laz"


def test_cli_download_failure(monkeypatch, tmp_path: Path, capsys) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise requests.HTTPError("404 Client Error")

    monkeypatch.setattr("lidar_catalog.acquire.download_tile", explode)
    catalog = tmp_path / "catalog.jsonl"
    code = main(
        [
            "--source",
            "https://example.com/missing.copc.laz",
            "--dataset-source",
            "USGS",
            "--store",
            "local",
            "--catalog-path",
            str(catalog),
        ]
    )
    assert code == 1
    assert not catalog.exists()
    assert "404" in capsys.readouterr().err


def test_ddl_matches_catalog_columns() -> None:
    sql_dir = Path(__file__).resolve().parents[1] / "sql"
    hive = (sql_dir / "lidar_catalog.sql").read_text(encoding="utf-8")
    spark = (sql_dir / "lidar_catalog_spark.sql").read_text(encoding="utf-8")
    assert hive == (
        "CREATE TABLE default.lidar_catalog (\n"
        "    dataset_source STRING,\n"
        "    file_name STRING,\n"
        "    file_path STRING,\n"
        "    min_x DOUBLE,\n"
        "    min_y DOUBLE,\n"
        "    max_x DOUBLE,\n"
        "    max_y DOUBLE,\n"
        "    point_count BIGINT,\n"
        "    ingest_timestamp TIMESTAMP\n"
        ") STORED AS ICEBERG;\n"
    )
    assert "STORED AS ICEBERG" not in spark
    assert "USING iceberg" in spark
    for column in CATALOG_COLUMNS:
        assert column in hive
        assert column in spark
