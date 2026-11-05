"""Bounding-box canopy density.

Find ``default.lidar_catalog`` rows whose box intersects the request, crop
those COPC/LAZ files with PDAL, and return counts. The raw cloud stays in
the PDAL pipeline.

Canopy points are ASPRS classes 3, 4, and 5 (low, medium, and high
vegetation). ``canopy_density`` is canopy points divided by points inside
the crop. The request box uses the same coordinates as the catalog
(``min_x``, ``min_y``, ``max_x``, ``max_y``), which are the tile CRS, not
longitude/latitude.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlparse

import requests

from lidar_catalog.metadata import MetadataError
from lidar_catalog.models import TABLE_NAME, CatalogRow
from lidar_catalog.stores import SQL_DIR, build_local_spark

CANOPY_CLASSES = (3, 4, 5)
_OBJECT_SCHEMES = {"http", "https", "s3", "s3a", "ofs", "abfs", "abfss", "gs", "wasb", "wasbs"}


@dataclass(frozen=True)
class Box:
    min_x: float
    min_y: float
    max_x: float
    max_y: float


@dataclass(frozen=True)
class FileCanopy:
    file_path: str
    file_name: str
    dataset_source: str
    total_points: int
    canopy_points: int
    canopy_density: float | None

    def as_dict(self) -> dict[str, object]:
        return {
            "file_path": self.file_path,
            "file_name": self.file_name,
            "dataset_source": self.dataset_source,
            "total_points": self.total_points,
            "canopy_points": self.canopy_points,
            "canopy_density": self.canopy_density,
        }


@dataclass(frozen=True)
class CanopyDensityResult:
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    file_count: int
    total_points: int
    canopy_points: int
    canopy_density: float | None
    classification_counts: dict[int, int]
    files: tuple[FileCanopy, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "min_x": self.min_x,
            "min_y": self.min_y,
            "max_x": self.max_x,
            "max_y": self.max_y,
            "file_count": self.file_count,
            "total_points": self.total_points,
            "canopy_points": self.canopy_points,
            "canopy_density": self.canopy_density,
            "classification_counts": {
                str(code): self.classification_counts[code]
                for code in sorted(self.classification_counts)
            },
            "files": [item.as_dict() for item in self.files],
        }


class CatalogIndex(Protocol):
    def intersecting(self, box: Box) -> Sequence[CatalogRow]:
        """Catalog rows whose bounds intersect ``box``."""


CountFn = Callable[[Path, Box], dict[int, int]]


def boxes_intersect(query: Box, tile: Box) -> bool:
    """True when the boxes overlap, including a shared edge."""
    return (
        query.min_x <= tile.max_x
        and query.max_x >= tile.min_x
        and query.min_y <= tile.max_y
        and query.max_y >= tile.min_y
    )


def validate_box(box: Box) -> None:
    values = {
        "min_x": box.min_x,
        "min_y": box.min_y,
        "max_x": box.max_x,
        "max_y": box.max_y,
    }
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a finite number")
        if not math.isfinite(float(value)):
            raise ValueError(f"{name} must be a finite number")
    if box.min_x > box.max_x or box.min_y > box.max_y:
        raise ValueError("bounding box min must be <= max")


def canopy_fraction(canopy_points: int, total_points: int) -> float | None:
    if total_points < 0 or canopy_points < 0:
        raise ValueError("point counts must be >= 0")
    if canopy_points > total_points:
        raise ValueError("canopy_points cannot exceed total_points")
    if total_points == 0:
        return None
    return canopy_points / total_points


def counts_to_canopy(counts: dict[int, int]) -> tuple[int, int]:
    total = 0
    canopy = 0
    for code, count in counts.items():
        if count < 0:
            raise ValueError("classification counts must be >= 0")
        total += count
        if code in CANOPY_CLASSES:
            canopy += count
    return total, canopy


class LocalJsonCatalogIndex:
    """Read the JSON lines written by ``LocalJsonCatalogStore``."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def intersecting(self, box: Box) -> list[CatalogRow]:
        validate_box(box)
        if not self.path.is_file():
            raise FileNotFoundError(f"catalog not found: {self.path}")
        matches: list[CatalogRow] = []
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                row = catalog_row_from_record(record)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"{self.path}:{line_number} is not a lidar_catalog row") from exc
            tile = Box(row.min_x, row.min_y, row.max_x, row.max_y)
            if boxes_intersect(box, tile):
                matches.append(row)
        matches.sort(key=lambda row: (row.file_path, row.ingest_timestamp))
        return matches


class IcebergCatalogIndex:
    """Run the catalog intersection SQL on a local or cluster Spark session."""

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

    @property
    def spark(self) -> object:
        if self._spark is None:
            self._spark = build_local_spark(self.warehouse or "")
        return self._spark

    def intersecting(self, box: Box) -> list[CatalogRow]:
        validate_box(box)
        spark = self.spark
        self._require_table(spark)
        statement = intersect_sql(box, table=self.table)
        rows = spark.sql(statement).collect()  # type: ignore[attr-defined]
        parsed = [catalog_row_from_record(_spark_row_dict(row)) for row in rows]
        parsed.sort(key=lambda row: (row.file_path, row.ingest_timestamp))
        return parsed

    def _require_table(self, spark: object) -> None:
        try:
            listed = spark.sql("SHOW TABLES IN default").collect()  # type: ignore[attr-defined]
        except Exception as exc:
            message = str(exc).lower()
            if "default" in message or "schema" in message or "namespace" in message:
                raise RuntimeError(
                    "Iceberg namespace default is missing. "
                    "Create default.lidar_catalog before a bounding-box query."
                ) from exc
            raise
        names = set()
        for item in listed:
            record = _spark_row_dict(item)
            names.add(str(record.get("tableName", record.get("table", ""))))
        if "lidar_catalog" not in names:
            raise RuntimeError(
                "default.lidar_catalog is missing. Register tiles before a bounding-box query."
            )


def canopy_density(
    box: Box,
    index: CatalogIndex,
    *,
    crop_counts: CountFn | None = None,
) -> CanopyDensityResult:
    """Intersect the catalog, crop each tile with PDAL, return canopy density."""
    validate_box(box)
    counter = crop_classification_counts if crop_counts is None else crop_counts
    combined: dict[int, int] = {}
    files: list[FileCanopy] = []
    for row in index.intersecting(box):
        path = readable_local_tile(row.file_path)
        counts = counter(path, box)
        total, canopy = counts_to_canopy(counts)
        for code, count in counts.items():
            combined[code] = combined.get(code, 0) + count
        files.append(
            FileCanopy(
                file_path=row.file_path,
                file_name=row.file_name,
                dataset_source=row.dataset_source,
                total_points=total,
                canopy_points=canopy,
                canopy_density=canopy_fraction(canopy, total),
            )
        )
    total_points, canopy_points = counts_to_canopy(combined)
    return CanopyDensityResult(
        min_x=float(box.min_x),
        min_y=float(box.min_y),
        max_x=float(box.max_x),
        max_y=float(box.max_y),
        file_count=len(files),
        total_points=total_points,
        canopy_points=canopy_points,
        canopy_density=canopy_fraction(canopy_points, total_points),
        classification_counts=combined,
        files=tuple(files),
    )


def crop_classification_counts(path: Path, box: Box) -> dict[int, int]:
    """PDAL crop of ``path`` to ``box``. Returns class counts, not points."""
    try:
        import pdal
    except ImportError as exc:
        raise RuntimeError(
            "PDAL's Python module is not installed. "
            "Install it with conda-forge packages `pdal` and `python-pdal` "
            "(the `pdal` package import)."
        ) from exc

    spec = {
        "pipeline": [
            {"type": "readers.las", "filename": str(path)},
            {"type": "filters.crop", "bounds": crop_bounds(box)},
        ]
    }
    pipeline = pdal.Pipeline(json.dumps(spec))
    pipeline.execute()
    counts: dict[int, int] = {}
    for array in pipeline.arrays:
        names = set(array.dtype.names or ())
        if "Classification" not in names:
            raise ValueError(f"{path} has no Classification dimension")
        for value in array["Classification"]:
            code = int(value)
            counts[code] = counts.get(code, 0) + 1
    return counts


def crop_bounds(box: Box) -> str:
    """PDAL filters.crop bounds. X then Y, matching readers.las."""
    return (
        f"([{_pdal_number(box.min_x)}, {_pdal_number(box.max_x)}], "
        f"[{_pdal_number(box.min_y)}, {_pdal_number(box.max_y)}])"
    )


def readable_local_tile(file_path: str) -> Path:
    parsed = urlparse(file_path)
    if parsed.scheme in _OBJECT_SCHEMES:
        raise ValueError(
            f"{file_path} is an object-storage path. "
            "This PDAL job reads a local COPC/LAZ file. "
            "Register that local path in lidar_catalog, or run where the object is mounted."
        )
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path))
    elif parsed.scheme:
        raise ValueError(f"unsupported tile path: {file_path}")
    else:
        path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"tile not found: {file_path}")
    return path


def intersect_sql(box: Box, *, table: str = TABLE_NAME) -> str:
    template = (SQL_DIR / "lidar_catalog_intersect.sql").read_text(encoding="utf-8")
    rendered = template.format(
        min_x=_sql_number(box.min_x),
        min_y=_sql_number(box.min_y),
        max_x=_sql_number(box.max_x),
        max_y=_sql_number(box.max_y),
    )
    if table != TABLE_NAME:
        rendered = rendered.replace(TABLE_NAME, table, 1)
    return _executable_sql(rendered)


def catalog_row_from_record(record: dict[str, object]) -> CatalogRow:
    timestamp = record["ingest_timestamp"]
    if isinstance(timestamp, datetime):
        parsed = timestamp
    else:
        parsed = datetime.fromisoformat(str(timestamp))
    return CatalogRow(
        dataset_source=str(record["dataset_source"]),
        file_name=str(record["file_name"]),
        file_path=str(record["file_path"]),
        min_x=float(record["min_x"]),  # type: ignore[arg-type]
        min_y=float(record["min_y"]),  # type: ignore[arg-type]
        max_x=float(record["max_x"]),  # type: ignore[arg-type]
        max_y=float(record["max_y"]),  # type: ignore[arg-type]
        point_count=int(record["point_count"]),  # type: ignore[arg-type]
        ingest_timestamp=parsed,
    )


def _spark_row_dict(row: object) -> dict[str, object]:
    if hasattr(row, "asDict"):
        return dict(row.asDict())  # type: ignore[attr-defined]
    return dict(row)  # type: ignore[arg-type]


def _executable_sql(sql_text: str) -> str:
    lines = [line for line in sql_text.splitlines() if not line.strip().startswith("--")]
    statement = "\n".join(lines).strip()
    if statement.endswith(";"):
        statement = statement[:-1].strip()
    return statement


def _sql_number(value: float) -> str:
    number = _finite(value, "bounding box coordinate")
    return repr(number)


def _pdal_number(value: float) -> str:
    return repr(_finite(value, "bounding box coordinate"))


def _finite(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Query default.lidar_catalog for a bounding box and return canopy "
            "density from a PDAL crop. Canopy classes are ASPRS 3, 4, and 5."
        )
    )
    parser.add_argument("--min-x", required=True, type=float)
    parser.add_argument("--min-y", required=True, type=float)
    parser.add_argument("--max-x", required=True, type=float)
    parser.add_argument("--max-y", required=True, type=float)
    parser.add_argument(
        "--store",
        choices=("local", "iceberg"),
        default="local",
        help="local reads a JSON lines catalog. iceberg queries default.lidar_catalog.",
    )
    parser.add_argument(
        "--catalog-path",
        type=Path,
        default=Path("lidar_catalog.jsonl"),
        help="JSON lines catalog used when --store local.",
    )
    parser.add_argument(
        "--warehouse",
        type=Path,
        help="Local Iceberg warehouse used when --store iceberg.",
    )
    args = parser.parse_args(argv)
    box = Box(args.min_x, args.min_y, args.max_x, args.max_y)
    if args.store == "iceberg":
        if args.warehouse is None:
            parser.error("--warehouse is required when --store iceberg")
        index: CatalogIndex = IcebergCatalogIndex(warehouse=args.warehouse)
    else:
        index = LocalJsonCatalogIndex(args.catalog_path)
    try:
        result = canopy_density(box, index)
    except (
        FileNotFoundError,
        ValueError,
        MetadataError,
        RuntimeError,
        requests.RequestException,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result.as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
