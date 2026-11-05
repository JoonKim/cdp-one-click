"""Command line for one lidar_catalog append."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

from lidar_catalog.ingest import ingest
from lidar_catalog.metadata import MetadataError
from lidar_catalog.models import DATASET_SOURCES
from lidar_catalog.stores import IcebergSparkCatalogStore, LocalJsonCatalogStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read a COPC/LAZ header with PDAL and append one row to "
            "default.lidar_catalog."
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
        help="Catalog dataset_source.",
    )
    parser.add_argument(
        "--store",
        choices=("local", "iceberg"),
        default="local",
        help=(
            "local writes the row to a JSON lines file. "
            "iceberg appends with Spark's Iceberg writer (default: local)."
        ),
    )
    parser.add_argument(
        "--catalog-path",
        type=Path,
        default=Path("lidar_catalog.jsonl"),
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
            "file_path recorded in the catalog. Use an Ozone or S3 URI when "
            "the object already lives in object storage."
        ),
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        help="Keep a URL download in this directory. Default is a temporary directory.",
    )
    args = parser.parse_args(argv)

    if args.store == "iceberg":
        if args.warehouse is None:
            parser.error("--warehouse is required when --store iceberg")
        store: LocalJsonCatalogStore | IcebergSparkCatalogStore = (
            IcebergSparkCatalogStore(warehouse=args.warehouse)
        )
    else:
        store = LocalJsonCatalogStore(args.catalog_path)

    try:
        row = ingest(
            args.source,
            args.dataset_source,
            store,
            object_path=args.object_path,
            download_dir=args.download_dir,
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

    print(json.dumps(row.as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
