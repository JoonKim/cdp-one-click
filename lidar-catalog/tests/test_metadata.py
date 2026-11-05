"""Header extraction.

Unit tests use fixtures captured from PDAL 2.10.2 (git-version 21d285) and
python-pdal 3.5.5, plus a mock ``pdal.Pipeline``. CI does not need a PDAL
install.

Captured inputs:

- ``pdal info --metadata`` on PDAL ``test/data/las/simple.las``
- Python pipeline metadata for ``readers.las`` with ``count`` 0 on that file
  (``execute()`` returned 0; header ``count`` was 1065)
- Python pipeline metadata for ``readers.copc`` with ``count`` 0 on PDAL
  ``test/data/copc/1.2-with-color.copc.laz``

Set ``LIDAR_SAMPLE`` to a real LAS/LAZ/COPC path to also run the live reader.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from lidar_catalog.metadata import (
    MetadataError,
    extract_header,
    header_from_metadata,
    reader_spatial_reference,
)

FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED = {
    "min_x": 635619.85,
    "min_y": 848899.7,
    "max_x": 638982.55,
    "max_y": 853535.43,
    "point_count": 1065,
}


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _assert_header(header) -> None:
    assert header.min_x == pytest.approx(EXPECTED["min_x"])
    assert header.min_y == pytest.approx(EXPECTED["min_y"])
    assert header.max_x == pytest.approx(EXPECTED["max_x"])
    assert header.max_y == pytest.approx(EXPECTED["max_y"])
    assert header.point_count == EXPECTED["point_count"]


def test_cli_info_metadata_uses_header_fields_not_filename() -> None:
    document = _load("pdal_info_metadata.json")
    filename = document["filename"]
    assert filename not in document["metadata"]
    _assert_header(header_from_metadata(document))


def test_python_pipeline_readers_las() -> None:
    _assert_header(header_from_metadata(_load("pdal_pipeline_readers_las.json")))


def test_python_pipeline_readers_copc() -> None:
    document = _load("pdal_pipeline_readers_copc.json")
    assert document["metadata"]["readers.copc"]["copc"] is True
    _assert_header(header_from_metadata(document))


def test_filename_key_is_not_reader_stats() -> None:
    document = {
        "metadata": {
            "/tmp/tile.copc.laz": {
                "minx": 1,
                "miny": 2,
                "maxx": 3,
                "maxy": 4,
                "count": 5,
            }
        }
    }
    with pytest.raises(MetadataError, match="filename key"):
        header_from_metadata(document)


def test_stats_filter_bbox_is_not_reader_header() -> None:
    document = {
        "metadata": {
            "filters.stats": {
                "bbox": {
                    "native": {
                        "bbox": {"minx": 1, "miny": 2, "maxx": 3, "maxy": 4}
                    }
                },
                "statistic": [{"name": "X", "count": 9}],
            }
        }
    }
    with pytest.raises(MetadataError, match="reader header"):
        header_from_metadata(document)


def test_copc_fixture_has_a_spatial_reference() -> None:
    text = reader_spatial_reference(_load("pdal_pipeline_readers_copc.json"))
    assert text.startswith("COMPD_CS[")


def test_las_fixture_without_crs_is_empty() -> None:
    assert reader_spatial_reference(_load("pdal_pipeline_readers_las.json")) == ""
    assert reader_spatial_reference(_load("pdal_info_metadata.json")) == ""


def test_extract_header_reads_stage_metadata_not_execute_count(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}
    fixture = _load("pdal_pipeline_readers_las.json")

    class FakePipeline:
        def __init__(self, spec: str) -> None:
            captured["spec"] = json.loads(spec)

        def execute(self) -> int:
            return 0

        @property
        def metadata(self) -> dict:
            return fixture

    monkeypatch.setitem(sys.modules, "pdal", type("pdal", (), {"Pipeline": FakePipeline}))
    tile = tmp_path / "tile.laz"
    tile.write_bytes(b"unused")

    header = extract_header(tile)

    spec = captured["spec"]
    assert spec["pipeline"][0]["type"] == "readers.las"
    assert spec["pipeline"][0]["count"] == 0
    assert spec["pipeline"][0]["filename"] == str(tile)
    # execute() was 0; the catalog count is the header field.
    _assert_header(header)


def test_extract_header_accepts_json_string_metadata(monkeypatch, tmp_path) -> None:
    payload = json.dumps(_load("pdal_pipeline_readers_las.json"))

    class FakePipeline:
        def __init__(self, spec: str) -> None:
            del spec

        def execute(self) -> int:
            return 0

        @property
        def metadata(self) -> str:
            return payload

    monkeypatch.setitem(sys.modules, "pdal", type("pdal", (), {"Pipeline": FakePipeline}))
    header = extract_header(tmp_path / "tile.laz")
    _assert_header(header)


@pytest.mark.skipif(importlib.util.find_spec("pdal") is None, reason="PDAL Python module is not installed")
def test_live_pdal_sample() -> None:
    sample = os.environ.get("LIDAR_SAMPLE")
    if not sample:
        pytest.skip("Set LIDAR_SAMPLE to a LAS, LAZ, or COPC path to read a live header")
    header = extract_header(Path(sample))
    assert header.point_count > 0
    assert header.max_x >= header.min_x
    assert header.max_y >= header.min_y
