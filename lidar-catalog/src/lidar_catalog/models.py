"""Catalog row written to default.lidar_catalog."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# Column order matches sql/lidar_catalog.sql.
CATALOG_COLUMNS = (
    "dataset_source",
    "file_name",
    "file_path",
    "min_x",
    "min_y",
    "max_x",
    "max_y",
    "point_count",
    "ingest_timestamp",
)

DATASET_SOURCES = ("USGS", "OpenTopography")
TABLE_NAME = "default.lidar_catalog"


@dataclass(frozen=True)
class PointCloudHeader:
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    point_count: int


@dataclass(frozen=True)
class CatalogRow:
    dataset_source: str
    file_name: str
    file_path: str
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    point_count: int
    ingest_timestamp: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "dataset_source": self.dataset_source,
            "file_name": self.file_name,
            "file_path": self.file_path,
            "min_x": self.min_x,
            "min_y": self.min_y,
            "max_x": self.max_x,
            "max_y": self.max_y,
            "point_count": self.point_count,
            "ingest_timestamp": self.ingest_timestamp.isoformat(),
        }
