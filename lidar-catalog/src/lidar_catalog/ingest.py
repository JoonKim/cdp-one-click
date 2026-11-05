"""Download or open one COPC/LAZ tile and append its catalog row."""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from lidar_catalog.acquire import materialize_source, object_name
from lidar_catalog.metadata import extract_header
from lidar_catalog.models import DATASET_SOURCES, CatalogRow
from lidar_catalog.stores import CatalogStore


def ingest(
    source: str,
    dataset_source: str,
    store: CatalogStore,
    *,
    object_path: str | None = None,
    download_dir: Path | None = None,
    now: datetime | None = None,
) -> CatalogRow:
    """Register one tile.

    ``source`` is a local COPC/LAZ path or an http(s) tile URL. ``object_path``
    is the catalog ``file_path`` when the bytes live in Ozone or S3 and
    ``source`` is only where PDAL reads the header.
    """
    if dataset_source not in DATASET_SOURCES:
        allowed = ", ".join(DATASET_SOURCES)
        raise ValueError(f"dataset_source must be one of: {allowed}")
    if object_path is not None and not object_path.strip():
        raise ValueError("object_path is empty")

    temp_dir: Path | None = None
    download_root = download_dir
    if _is_http(source) and download_root is None:
        temp_dir = Path(tempfile.mkdtemp(prefix="lidar-catalog-"))
        download_root = temp_dir
    try:
        local_path, catalog_path = materialize_source(source, download_root)
        header = extract_header(local_path)
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)

    file_path = object_path if object_path is not None else catalog_path
    row = CatalogRow(
        dataset_source=dataset_source,
        file_name=object_name(file_path),
        file_path=file_path,
        min_x=header.min_x,
        min_y=header.min_y,
        max_x=header.max_x,
        max_y=header.max_y,
        point_count=header.point_count,
        ingest_timestamp=now if now is not None else datetime.now(timezone.utc),
    )
    store.append(row)
    return row


def _is_http(source: str) -> bool:
    return urlparse(source).scheme in {"http", "https"}
