"""Read COPC/LAZ header bounds from the metadata PDAL actually returns.

PDAL 2.10.2 / python-pdal 3.5.5, with ``readers.las`` or ``readers.copc`` and
``count`` set to 0:

- ``pipeline.execute()`` returns 0 (no points unpacked).
- Header stats are on ``metadata["readers.las"]`` or ``metadata["readers.copc"]``:
  ``minx``, ``miny``, ``maxx``, ``maxy``, and ``count``.
- ``count`` is the LAS header point count. It is not the value ``execute()`` returns.

``pdal info --metadata`` puts those same header fields directly on the top-level
``metadata`` object (and sets ``reader`` to ``readers.las`` or ``readers.copc``).
The file path is not a metadata key.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from lidar_catalog.models import PointCloudHeader

HEADER_FIELDS = ("minx", "miny", "maxx", "maxy", "count")
# Stage names observed on PDAL 2.10.2. Filename keys are not in this list.
READER_STAGES = ("readers.copc", "readers.las")


class MetadataError(ValueError):
    """PDAL returned a document without reader header stats."""


def extract_header(path: Path) -> PointCloudHeader:
    """Read bounding box and point count for a local COPC/LAZ/LAS file."""
    document = read_pdal_metadata(path)
    return header_from_metadata(document)


def read_pdal_metadata(path: Path) -> dict[str, Any]:
    """Run a header-only PDAL pipeline and return its metadata document."""
    try:
        import pdal
    except ImportError as exc:
        raise RuntimeError(
            "PDAL's Python module is not installed. "
            "Install it with conda-forge packages `pdal` and `python-pdal` "
            "(the `pdal` package import)."
        ) from exc

    # count 0: reader header stats are filled in ready(); zero points are unpacked.
    spec = json.dumps(
        {
            "pipeline": [
                {
                    "type": "readers.las",
                    "filename": str(path),
                    "count": 0,
                }
            ]
        }
    )
    pipeline = pdal.Pipeline(spec)
    pipeline.execute()
    metadata = pipeline.metadata
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    if not isinstance(metadata, dict):
        raise MetadataError(
            f"PDAL metadata for {path} was {type(metadata).__name__}, expected an object"
        )
    return metadata


def header_from_metadata(document: Mapping[str, Any]) -> PointCloudHeader:
    """Pull min/max XY and point count from a PDAL metadata document."""
    stats = _reader_stats(document)
    return PointCloudHeader(
        min_x=_number(stats, "minx", float),
        min_y=_number(stats, "miny", float),
        max_x=_number(stats, "maxx", float),
        max_y=_number(stats, "maxy", float),
        point_count=_number(stats, "count", int),
    )


def reader_spatial_reference(document: Mapping[str, Any]) -> str:
    """Return the reader CRS WKT, or an empty string when the file has none.

    H3 partitioning needs a CRS so X/Y can be reprojected to WGS84. PDAL puts
    the source CRS on the same reader stats node as the header bounds
    (``spatialreference``, or ``srs.wkt`` / ``srs.compoundwkt``).
    """
    stats = _reader_stats(document)
    text = stats.get("spatialreference") or ""
    if isinstance(text, str) and text.strip():
        return text.strip()
    srs = stats.get("srs")
    if isinstance(srs, dict):
        for key in ("compoundwkt", "wkt", "proj4"):
            value = srs.get(key) or ""
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _reader_stats(document: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        raise MetadataError("PDAL document has no metadata object")

    # `pdal info --metadata`: header fields sit directly on `metadata`.
    if _has_header(metadata):
        return metadata

    # Python pipeline: header fields sit on the reader stage, not the filename.
    stage_names: list[str] = []
    reader = document.get("reader")
    if isinstance(reader, str):
        stage_names.append(reader)
    stage_names.extend(READER_STAGES)

    seen: set[str] = set()
    for name in stage_names:
        if name in seen:
            continue
        seen.add(name)
        node = metadata.get(name)
        if isinstance(node, dict) and _has_header(node):
            return node

    for name, node in metadata.items():
        if name in seen or not isinstance(node, dict):
            continue
        if name.startswith("readers.") and _has_header(node):
            return node

    raise MetadataError(
        "PDAL metadata has no reader header stats "
        "(minx, miny, maxx, maxy, count). "
        "Expected them on metadata from `pdal info --metadata`, "
        "or on metadata['readers.las'] / metadata['readers.copc'] "
        "from a Python pipeline. A filename key is not a reader stage."
    )


def _has_header(node: Mapping[str, Any]) -> bool:
    return all(field in node for field in HEADER_FIELDS)


def _number(node: Mapping[str, Any], key: str, caster: type[float] | type[int]) -> float | int:
    try:
        return caster(node[key])
    except (TypeError, ValueError) as exc:
        raise MetadataError(
            f"PDAL metadata field {key!r} is not a number: {node.get(key)!r}"
        ) from exc
