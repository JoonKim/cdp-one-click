"""Bounding-box canopy density.

Intersection and the density fraction are tested without PDAL. The PDAL crop
is covered with a mock pipeline that returns class codes, plus a live crop
when LIDAR_SAMPLE is a readable tile.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lidar_catalog.analytics import (
    CANOPY_CLASSES,
    Box,
    LocalJsonCatalogIndex,
    boxes_intersect,
    canopy_density,
    canopy_fraction,
    crop_bounds,
    crop_classification_counts,
    main,
)
from lidar_catalog.metadata import extract_header
from lidar_catalog.models import CatalogRow
from lidar_catalog.stores import LocalJsonCatalogStore

NOW = datetime(2026, 11, 5, 16, 30, tzinfo=timezone.utc)


def _row(path: str, min_x: float, min_y: float, max_x: float, max_y: float, name: str) -> CatalogRow:
    return CatalogRow(
        dataset_source="USGS",
        file_name=name,
        file_path=path,
        min_x=min_x,
        min_y=min_y,
        max_x=max_x,
        max_y=max_y,
        point_count=10,
        ingest_timestamp=NOW,
    )


def test_edge_touch_intersects_and_gap_does_not() -> None:
    tile = Box(0, 0, 10, 10)
    assert boxes_intersect(Box(10, 0, 12, 1), tile)
    assert boxes_intersect(Box(2, 2, 3, 3), tile)
    assert not boxes_intersect(Box(10.1, 0, 12, 1), tile)
    assert not boxes_intersect(Box(-2, -2, -0.1, -0.1), tile)


def test_canopy_fraction_uses_asprs_vegetation_classes() -> None:
    assert CANOPY_CLASSES == (3, 4, 5)
    assert canopy_fraction(2, 8) == pytest.approx(0.25)
    assert canopy_fraction(0, 4) == 0
    assert canopy_fraction(0, 0) is None


def test_local_catalog_returns_intersecting_files_only(tmp_path: Path) -> None:
    catalog = tmp_path / "lidar_catalog.jsonl"
    store = LocalJsonCatalogStore(catalog)
    inside = tmp_path / "inside.copc.laz"
    outside = tmp_path / "outside.copc.laz"
    inside.write_bytes(b"laz")
    outside.write_bytes(b"laz")
    store.append(_row(str(inside), 0, 0, 10, 10, "inside.copc.laz"))
    store.append(_row(str(outside), 100, 100, 110, 110, "outside.copc.laz"))

    seen: list[Path] = []

    def counts(path: Path, box: Box) -> dict[int, int]:
        seen.append(path)
        assert box == Box(1, 1, 2, 2)
        if path == inside:
            return {2: 6, 5: 2, 3: 2}
        raise AssertionError(f"unexpected tile {path}")

    result = canopy_density(Box(1, 1, 2, 2), LocalJsonCatalogIndex(catalog), crop_counts=counts)
    assert seen == [inside]
    assert result.file_count == 1
    assert result.total_points == 10
    assert result.canopy_points == 4
    assert result.canopy_density == pytest.approx(0.4)
    assert result.classification_counts == {2: 6, 5: 2, 3: 2}
    assert result.files[0].file_path == str(inside)
    payload = result.as_dict()
    assert "X" not in json.dumps(payload)
    assert set(payload) == {
        "min_x",
        "min_y",
        "max_x",
        "max_y",
        "file_count",
        "total_points",
        "canopy_points",
        "canopy_density",
        "classification_counts",
        "files",
    }


def test_density_is_the_sum_across_files(tmp_path: Path) -> None:
    catalog = tmp_path / "lidar_catalog.jsonl"
    store = LocalJsonCatalogStore(catalog)
    first = tmp_path / "a.laz"
    second = tmp_path / "b.laz"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    store.append(_row(str(first), 0, 0, 5, 5, "a.laz"))
    store.append(_row(str(second), 4, 4, 9, 9, "b.laz"))

    def counts(path: Path, box: Box) -> dict[int, int]:
        del box
        if path == first:
            return {5: 1, 2: 1}
        return {4: 9, 2: 1}

    result = canopy_density(Box(0, 0, 9, 9), LocalJsonCatalogIndex(catalog), crop_counts=counts)
    assert result.total_points == 12
    assert result.canopy_points == 10
    assert result.canopy_density == pytest.approx(10 / 12)


def test_disjoint_query_does_not_call_pdal(tmp_path: Path) -> None:
    catalog = tmp_path / "lidar_catalog.jsonl"
    LocalJsonCatalogStore(catalog).append(_row(str(tmp_path / "a.laz"), 0, 0, 1, 1, "a.laz"))

    def counts(path: Path, box: Box) -> dict[int, int]:
        raise AssertionError("PDAL should not run when no tile intersects")

    result = canopy_density(Box(5, 5, 6, 6), LocalJsonCatalogIndex(catalog), crop_counts=counts)
    assert result.file_count == 0
    assert result.total_points == 0
    assert result.canopy_density is None
    assert result.files == ()


def test_object_storage_path_is_not_a_successful_density(tmp_path: Path) -> None:
    catalog = tmp_path / "lidar_catalog.jsonl"
    LocalJsonCatalogStore(catalog).append(
        _row("ofs://ozone/bucket/lidar/tile.copc.laz", 0, 0, 10, 10, "tile.copc.laz")
    )

    def counts(path: Path, box: Box) -> dict[int, int]:
        raise AssertionError("object URI must fail before PDAL")

    with pytest.raises(ValueError, match="object-storage"):
        canopy_density(Box(0, 0, 1, 1), LocalJsonCatalogIndex(catalog), crop_counts=counts)


def test_inverted_box_raises() -> None:
    with pytest.raises(ValueError, match="min must be <= max"):
        canopy_density(Box(2, 0, 1, 1), LocalJsonCatalogIndex("missing.jsonl"))


def test_crop_pipeline_counts_classes_and_drops_points(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class _Array:
        dtype = type("Dtype", (), {"names": ("Classification", "X", "Y", "Z")})()

        def __len__(self) -> int:
            return 4

        def __getitem__(self, key: str) -> list[int]:
            assert key == "Classification"
            return [2, 5, 5, 1]

    class _Pipeline:
        def __init__(self, spec: str) -> None:
            captured["spec"] = json.loads(spec)

        def execute(self) -> int:
            return 4

        arrays = [_Array()]

    monkeypatch.setitem(sys.modules, "pdal", type("pdal", (), {"Pipeline": _Pipeline}))
    tile = tmp_path / "tile.laz"
    counts = crop_classification_counts(tile, Box(635619.85, 848899.7, 638982.55, 853535.43))
    spec = captured["spec"]["pipeline"]
    assert [stage["type"] for stage in spec] == ["readers.las", "filters.crop"]
    assert spec[1]["bounds"] == crop_bounds(Box(635619.85, 848899.7, 638982.55, 853535.43))
    assert "writers." not in json.dumps(spec)
    assert counts == {2: 1, 5: 2, 1: 1}


def test_cli_prints_the_summary(monkeypatch, tmp_path: Path, capsys) -> None:
    catalog = tmp_path / "lidar_catalog.jsonl"
    tile = tmp_path / "tile.copc.laz"
    tile.write_bytes(b"laz")
    LocalJsonCatalogStore(catalog).append(_row(str(tile), 0, 0, 10, 10, "tile.copc.laz"))

    def counts(path: Path, box: Box) -> dict[int, int]:
        del path, box
        return {5: 1, 2: 3}

    monkeypatch.setattr("lidar_catalog.analytics.crop_classification_counts", counts)
    code = main(
        [
            "--min-x",
            "1",
            "--min-y",
            "1",
            "--max-x",
            "2",
            "--max-y",
            "2",
            "--store",
            "local",
            "--catalog-path",
            str(catalog),
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["canopy_points"] == 1
    assert payload["total_points"] == 4
    assert payload["canopy_density"] == pytest.approx(0.25)
    assert "files" in payload and len(payload["files"]) == 1


@pytest.mark.skipif(importlib.util.find_spec("pdal") is None, reason="PDAL Python module is not installed")
def test_live_catalog_crop(tmp_path: Path) -> None:
    sample = os.environ.get("LIDAR_SAMPLE")
    if not sample:
        pytest.skip("Set LIDAR_SAMPLE to a LAS, LAZ, or COPC path")
    header = extract_header(Path(sample))
    catalog = tmp_path / "lidar_catalog.jsonl"
    LocalJsonCatalogStore(catalog).append(
        CatalogRow(
            dataset_source="USGS",
            file_name=Path(sample).name,
            file_path=sample,
            min_x=header.min_x,
            min_y=header.min_y,
            max_x=header.max_x,
            max_y=header.max_y,
            point_count=header.point_count,
            ingest_timestamp=NOW,
        )
    )
    box = Box(header.min_x, header.min_y, header.max_x, header.max_y)
    result = canopy_density(box, LocalJsonCatalogIndex(catalog))
    assert result.file_count == 1
    assert result.total_points == header.point_count
    assert result.canopy_points <= result.total_points
    assert sum(result.classification_counts.values()) == result.total_points
    if result.total_points == 0:
        assert result.canopy_density is None
    else:
        assert result.canopy_density == pytest.approx(result.canopy_points / result.total_points)
    assert len(json.dumps(result.as_dict())) < 5000
