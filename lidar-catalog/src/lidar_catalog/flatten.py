"""Flatten one COPC/LAZ tile into default.lidar_points.

The catalog table is unchanged. ``file_path`` on each point is the join key
back to ``default.lidar_catalog``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from lidar_catalog.acquire import materialize_source
from lidar_catalog.metadata import MetadataError
from lidar_catalog.models import DATASET_SOURCES
from lidar_catalog.point_stores import IcebergSparkPointStore, LocalJsonPointStore, PointStore
from lidar_catalog.points import H3_RESOLUTION, FlattenResult, PointRow, read_points


def flatten_tile(
    source: str,
    dataset_source: str,
    store: PointStore,
    *,
    object_path: str | None = None,
    download_dir: Path | None = None,
    limit: int | None = None,
    now: datetime | None = None,
) -> FlattenResult:
    """Unpack one tile and append its points.

    ``source`` is a local COPC/LAZ path or an http(s) tile URL. ``object_path``
    is the ``file_path`` stored on each point when the bytes live in Ozone or
    S3. ``limit`` reads only the first N points for a local proof.
    """
    if dataset_source not in DATASET_SOURCES:
        allowed = ", ".join(DATASET_SOURCES)
        raise ValueError(f"dataset_source must be one of: {allowed}")
    if object_path is not None and not object_path.strip():
        raise ValueError("object_path is empty")
    if limit is not None and limit < 1:
        raise ValueError("limit must be >= 1")

    temp_dir: Path | None = None
    download_root = download_dir
    if _is_http(source) and download_root is None:
        temp_dir = Path(tempfile.mkdtemp(prefix="lidar-points-"))
        download_root = temp_dir
    try:
        local_path, catalog_path = materialize_source(source, download_root)
        file_path = object_path if object_path is not None else catalog_path
        rows = read_points(
            local_path,
            file_path=file_path,
            dataset_source=dataset_source,
            limit=limit,
            now=now,
        )
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)

    store.append(rows)
    return _result(rows, file_path=file_path, dataset_source=dataset_source)


def _result(rows: Sequence[PointRow], *, file_path: str, dataset_source: str) -> FlattenResult:
    return FlattenResult(
        file_path=file_path,
        dataset_source=dataset_source,
        points_written=len(rows),
        h3_resolution=H3_RESOLUTION,
        h3_cell_count=len({row.h3_index for row in rows}),
    )


def _is_http(source: str) -> bool:
    return urlparse(source).scheme in {"http", "https"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Unpack COPC/LAZ points with PDAL and append them to the "
            f"H3-partitioned Iceberg table default.lidar_points "
            f"(resolution {H3_RESOLUTION})."
        )
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Local .laz/.copc.laz path, or an http(s) URL of a real tile.",
    )
    parser.add_argument(
        "--dataset-source",
        required=True,
        choices=DATASET_SOURCES,
        help="dataset_source stored on each point. Matches the catalog vocabulary.",
    )
    parser.add_argument(
        "--store",
        choices=("local", "iceberg"),
        default="local",
        help=(
            "local writes JSON lines. "
            "iceberg appends with Spark's Iceberg writer (default: local)."
        ),
    )
    parser.add_argument(
        "--points-path",
        type=Path,
        default=Path("lidar_points.jsonl"),
        help="JSON lines path used when --store local.",
    )
    parser.add_argument(
        "--warehouse",
        type=Path,
        help="Local Iceberg warehouse directory used when --store iceberg.",
    )
    parser.add_argument(
        "--object-path",
        help=(
            "file_path stored on each point. Use an Ozone or S3 URI when the "
            "object already lives in object storage. This joins to lidar_catalog."
        ),
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        help="Keep a URL download in this directory. Default is a temporary directory.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Read only the first N points. Use this for a small local proof.",
    )
    args = parser.parse_args(argv)

    if args.store == "iceberg":
        if args.warehouse is None:
            parser.error("--warehouse is required when --store iceberg")
        store: LocalJsonPointStore | IcebergSparkPointStore = IcebergSparkPointStore(
            warehouse=args.warehouse
        )
    else:
        store = LocalJsonPointStore(args.points_path)

    try:
        result = flatten_tile(
            args.source,
            args.dataset_source,
            store,
            object_path=args.object_path,
            download_dir=args.download_dir,
            limit=args.limit,
        )
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
