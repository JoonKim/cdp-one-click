"""Unpack COPC/LAZ points and assign an H3 cell.

Resolution 9 is the partition grid. H3's average resolution-9 hexagon is about
0.105 km² with an edge of about 201 m. At a few points per square meter that
is a large Iceberg partition, and a few-hundred-meter analysis window still
touches only a handful of cells. Resolution 8 (about 0.74 km², edge about 531 m)
is close to a whole small tile, so pruning barely helps. Resolution 10 (about
0.015 km², edge about 76 m) multiplies the partition count by seven.

PDAL 2.10.2 pipeline used here, verified on a COPC tile:

1. ``readers.las`` (also reads LAZ and COPC). Optional ``count`` caps the read.
2. ``filters.ferry`` copies X/Y/Z to Xnative/Ynative/Znative before reprojection.
3. ``filters.reprojection`` to EPSG:4326. Afterwards X is longitude and Y is
   latitude (a sample point came back as X=-117.26, Y=49.34).

The native coordinates stay on the row for later measurement. The catalog
table remains the file index; each point stores ``file_path`` so it joins back.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import h3

from lidar_catalog.metadata import read_pdal_metadata, reader_spatial_reference

# Average resolution-9 hexagon from h3.average_hexagon_area / edge_length.
H3_RESOLUTION = 9
POINTS_TABLE = "default.lidar_points"
POINT_COLUMNS = (
    "h3_index",
    "h3_resolution",
    "x",
    "y",
    "z",
    "longitude",
    "latitude",
    "classification",
    "intensity",
    "return_number",
    "number_of_returns",
    "file_path",
    "dataset_source",
    "ingest_timestamp",
)
_NATIVE = ("Xnative", "Ynative", "Znative")
_WGS84 = ("X", "Y", "Z")
_OPTIONAL = (
    ("Classification", "classification"),
    ("Intensity", "intensity"),
    ("ReturnNumber", "return_number"),
    ("NumberOfReturns", "number_of_returns"),
)
_SIGNED_BIGINT_MAX = 2**63 - 1


@dataclass(frozen=True)
class PointRow:
    h3_index: int
    h3_resolution: int
    x: float
    y: float
    z: float
    longitude: float
    latitude: float
    classification: int | None
    intensity: int | None
    return_number: int | None
    number_of_returns: int | None
    file_path: str
    dataset_source: str
    ingest_timestamp: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "h3_index": self.h3_index,
            "h3_resolution": self.h3_resolution,
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "longitude": self.longitude,
            "latitude": self.latitude,
            "classification": self.classification,
            "intensity": self.intensity,
            "return_number": self.return_number,
            "number_of_returns": self.number_of_returns,
            "file_path": self.file_path,
            "dataset_source": self.dataset_source,
            "ingest_timestamp": self.ingest_timestamp.isoformat(),
        }


@dataclass(frozen=True)
class FlattenResult:
    file_path: str
    dataset_source: str
    points_written: int
    h3_resolution: int
    h3_cell_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "file_path": self.file_path,
            "dataset_source": self.dataset_source,
            "points_written": self.points_written,
            "h3_resolution": self.h3_resolution,
            "h3_cell_count": self.h3_cell_count,
        }


def read_points(
    path: Path,
    *,
    file_path: str,
    dataset_source: str,
    limit: int | None = None,
    now: datetime | None = None,
    resolution: int = H3_RESOLUTION,
) -> list[PointRow]:
    """Unpack points from a local COPC/LAZ/LAS file into H3-keyed rows."""
    if limit is not None and limit < 1:
        raise ValueError("limit must be >= 1")
    document = read_pdal_metadata(path)
    if not reader_spatial_reference(document):
        raise ValueError(
            f"{path} has no spatial reference. "
            "H3 cells need a CRS so PDAL can reproject X/Y to WGS84 longitude/latitude."
        )
    arrays = _read_reprojected_arrays(path, limit)
    rows = points_from_arrays(
        arrays,
        file_path=file_path,
        dataset_source=dataset_source,
        now=now if now is not None else datetime.now(timezone.utc),
        resolution=resolution,
    )
    if not rows:
        raise ValueError(f"no points read from {path}")
    return rows


def points_from_arrays(
    arrays: Sequence[Any],
    *,
    file_path: str,
    dataset_source: str,
    now: datetime,
    resolution: int = H3_RESOLUTION,
) -> list[PointRow]:
    """Build point rows from PDAL arrays that already include native and WGS84 axes.

    ``X`` / ``Y`` are longitude / latitude after ``filters.reprojection`` to
    EPSG:4326. ``Xnative`` / ``Ynative`` / ``Znative`` are the source coordinates.
    """
    rows: list[PointRow] = []
    for array in arrays:
        names = set(array.dtype.names or ())
        missing = [name for name in (*_NATIVE, *_WGS84) if name not in names]
        if missing:
            raise ValueError(
                "PDAL point array is missing "
                + ", ".join(missing)
                + ". Expected ferry copies Xnative/Ynative/Znative and "
                "reprojected X/Y (longitude/latitude)."
            )
        count = len(array)
        for index in range(count):
            longitude = float(array["X"][index])
            latitude = float(array["Y"][index])
            native_x = float(array["Xnative"][index])
            native_y = float(array["Ynative"][index])
            native_z = float(array["Znative"][index])
            _require_wgs84(longitude, latitude)
            _require_finite(native_x, native_y, native_z, longitude, latitude)
            cell = h3.latlng_to_cell(latitude, longitude, resolution)
            h3_index = h3.str_to_int(cell)
            if h3_index < 0 or h3_index > _SIGNED_BIGINT_MAX:
                raise ValueError(f"H3 cell {cell} does not fit in a signed BIGINT")
            optional = {
                field: _optional_int(array, dimension, index, names)
                for dimension, field in _OPTIONAL
            }
            rows.append(
                PointRow(
                    h3_index=h3_index,
                    h3_resolution=resolution,
                    x=native_x,
                    y=native_y,
                    z=native_z,
                    longitude=longitude,
                    latitude=latitude,
                    classification=optional["classification"],
                    intensity=optional["intensity"],
                    return_number=optional["return_number"],
                    number_of_returns=optional["number_of_returns"],
                    file_path=file_path,
                    dataset_source=dataset_source,
                    ingest_timestamp=now,
                )
            )
    return rows


def _read_reprojected_arrays(path: Path, limit: int | None) -> list[Any]:
    try:
        import pdal
    except ImportError as exc:
        raise RuntimeError(
            "PDAL's Python module is not installed. "
            "Install it with conda-forge packages `pdal` and `python-pdal` "
            "(the `pdal` package import)."
        ) from exc

    reader: dict[str, object] = {"type": "readers.las", "filename": str(path)}
    if limit is not None:
        reader["count"] = limit
    spec = {
        "pipeline": [
            reader,
            {
                "type": "filters.ferry",
                "dimensions": "X=>Xnative,Y=>Ynative,Z=>Znative",
            },
            {"type": "filters.reprojection", "out_srs": "EPSG:4326"},
        ]
    }
    pipeline = pdal.Pipeline(json.dumps(spec))
    pipeline.execute()
    return list(pipeline.arrays)


def _optional_int(array: Any, dimension: str, index: int, names: set[str]) -> int | None:
    if dimension not in names:
        return None
    value = array[dimension][index]
    if value is None:
        return None
    return int(value)


def _require_wgs84(longitude: float, latitude: float) -> None:
    if not (-180.0 <= longitude <= 180.0 and -90.0 <= latitude <= 90.0):
        raise ValueError(
            "reprojected coordinates "
            f"({longitude}, {latitude}) are outside longitude/latitude range. "
            "PDAL's X/Y after EPSG:4326 are longitude/latitude."
        )


def _require_finite(*values: float) -> None:
    if not all(math.isfinite(value) for value in values):
        raise ValueError("point coordinates must be finite")


def h3_cell(latitude: float, longitude: float, resolution: int = H3_RESOLUTION) -> int:
    """H3 cell id for a WGS84 point, as a signed BIGINT."""
    _require_wgs84(longitude, latitude)
    cell = h3.str_to_int(h3.latlng_to_cell(latitude, longitude, resolution))
    if cell < 0 or cell > _SIGNED_BIGINT_MAX:
        raise ValueError(f"H3 cell does not fit in a signed BIGINT: {cell}")
    return cell

