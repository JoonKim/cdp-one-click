#!/usr/bin/env python3
"""
Ingest the geospatial entity datasets into an Apache Iceberg table on the
*existing* CDP cluster -- no new servers.

It runs as a Spark 3 job on the Data Hub (``spark3-submit``). The Data Hub's
Spark 3 already has Iceberg enabled (``spark.sql.catalog.spark_catalog`` is the
Iceberg ``SparkSessionCatalog`` of type ``hive``), so tables are created in the
shared Hive Metastore (SDX) and stored in the environment's S3 warehouse.

It builds exactly the same rows as the COD/Phoenix ``geo_entity`` table from the
same GeoJSON datasets, writes them to the Iceberg table ``<db>.<table>``, then
verifies the result (row count, per-layer counts, Iceberg snapshots/files) and
writes a compact JSON export the web app renders as a table.

Usage (on the Data Hub master, as a kinit'd workload user):
    spark3-submit iceberg_ingest.py \
        --entity-dir /tmp/entity \
        --database geo --table geo_entity \
        --export /tmp/iceberg_export.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os


def centroid_and_bbox(geom: dict):
    gtype = geom["type"]
    coords = geom["coordinates"]
    if gtype == "Point":
        pts = [coords]
    elif gtype == "LineString":
        pts = coords
    elif gtype == "Polygon":
        pts = coords[0]
    elif gtype == "MultiPolygon":
        pts = [p for poly in coords for p in poly[0]]
    else:
        pts = [coords]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (
        sum(xs) / len(xs),
        sum(ys) / len(ys),
        min(xs),
        min(ys),
        max(xs),
        max(ys),
    )


def load_features(entity_dir: str):
    rows = []
    paths = sorted(glob.glob(os.path.join(entity_dir, "*.geojson"))) + sorted(
        glob.glob(os.path.join(entity_dir, "*.json"))
    )
    for path in paths:
        layer = os.path.splitext(os.path.basename(path))[0]
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        feats = data.get("features", []) if data.get("type") == "FeatureCollection" else [data]
        for feat in feats:
            props = feat.get("properties", {})
            clon, clat, minx, miny, maxx, maxy = centroid_and_bbox(feat["geometry"])
            mmsi = props.get("mmsi")
            sog = props.get("sog_kn")
            rows.append(
                {
                    "layer": layer,
                    "id": str(props.get("id", f"{layer}-{len(rows)}")),
                    "name": str(props.get("name", "")),
                    "geom_type": feat["geometry"]["type"],
                    "center_lon": float(clon),
                    "center_lat": float(clat),
                    "min_lon": float(minx),
                    "min_lat": float(miny),
                    "max_lon": float(maxx),
                    "max_lat": float(maxy),
                    "geojson": json.dumps(feat["geometry"]),
                    "mmsi": str(mmsi) if mmsi is not None else None,
                    "alert_type": props.get("alert_type"),
                    "vtype": props.get("type"),
                    "flag": props.get("flag"),
                    "sog": float(sog) if sog is not None else None,
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest entity datasets into an Iceberg table")
    parser.add_argument("--entity-dir", default=os.environ.get("ENTITY_DIR", "/tmp/entity"))
    parser.add_argument("--database", default=os.environ.get("ICEBERG_DB", "geo"))
    parser.add_argument("--table", default=os.environ.get("ICEBERG_TABLE", "geo_entity"))
    parser.add_argument("--export", default=os.environ.get("ICEBERG_EXPORT", "/tmp/iceberg_export.json"))
    args = parser.parse_args()

    from pyspark.sql import SparkSession
    from pyspark.sql.types import (
        DoubleType,
        StringType,
        StructField,
        StructType,
    )

    fqtn = f"{args.database}.{args.table}"
    rows = load_features(args.entity_dir)
    print(f"Loaded {len(rows)} features from {args.entity_dir}")

    schema = StructType(
        [
            StructField("layer", StringType(), False),
            StructField("id", StringType(), False),
            StructField("name", StringType(), True),
            StructField("geom_type", StringType(), True),
            StructField("center_lon", DoubleType(), True),
            StructField("center_lat", DoubleType(), True),
            StructField("min_lon", DoubleType(), True),
            StructField("min_lat", DoubleType(), True),
            StructField("max_lon", DoubleType(), True),
            StructField("max_lat", DoubleType(), True),
            StructField("geojson", StringType(), True),
            StructField("mmsi", StringType(), True),
            StructField("alert_type", StringType(), True),
            StructField("vtype", StringType(), True),
            StructField("flag", StringType(), True),
            StructField("sog", DoubleType(), True),
        ]
    )

    spark = SparkSession.builder.appName("geo-iceberg-ingest").enableHiveSupport().getOrCreate()

    df = spark.createDataFrame(rows, schema=schema).repartition(4, "layer")

    spark.sql(f"CREATE DATABASE IF NOT EXISTS {args.database}")
    # Create-or-replace the Iceberg table (partitioned by layer) with the data.
    (
        df.sortWithinPartitions("layer", "id")
        .writeTo(fqtn)
        .using("iceberg")
        .partitionedBy("layer")
        .tableProperty("format-version", "2")
        .createOrReplace()
    )
    print(f"Wrote Iceberg table {fqtn}")

    total = spark.sql(f"SELECT COUNT(*) AS n FROM {fqtn}").collect()[0]["n"]
    print(f"Row count: {total}")

    print("Per-layer counts:")
    per_layer = {}
    for r in spark.sql(
        f"SELECT layer, COUNT(*) AS n FROM {fqtn} GROUP BY layer ORDER BY layer"
    ).collect():
        per_layer[r["layer"]] = r["n"]
        print(f"   {r['layer']:<22} {r['n']}")

    # Iceberg metadata tables prove it is a real Iceberg table.
    snapshot_id = None
    file_count = None
    try:
        snaps = spark.sql(
            f"SELECT snapshot_id, committed_at FROM {fqtn}.snapshots ORDER BY committed_at DESC"
        ).collect()
        if snaps:
            snapshot_id = snaps[0]["snapshot_id"]
            print(f"Iceberg snapshots: {len(snaps)} (current {snapshot_id})")
        file_count = spark.sql(f"SELECT COUNT(*) AS n FROM {fqtn}.files").collect()[0]["n"]
        print(f"Iceberg data files: {file_count}")
    except Exception as exc:  # pragma: no cover - metadata tables are best-effort
        print(f"(metadata tables unavailable: {exc})")

    location = None
    table_format = "iceberg"
    try:
        for r in spark.sql(f"DESCRIBE EXTENDED {fqtn}").collect():
            col = (r["col_name"] or "").strip().lower()
            if col == "location":
                location = r["data_type"]
            elif col == "provider":
                table_format = r["data_type"]
    except Exception:
        pass
    print(f"Table location: {location}")

    # Compact export for the web table (geojson omitted; it is large).
    cols = [
        "layer", "id", "name", "geom_type",
        "center_lon", "center_lat", "min_lon", "min_lat", "max_lon", "max_lat",
        "mmsi", "alert_type", "vtype", "flag", "sog",
    ]
    export_rows = [
        {c: row[c] for c in cols}
        for row in spark.sql(
            f"SELECT {', '.join(cols)} FROM {fqtn} ORDER BY layer, id"
        ).collect()
    ]
    payload = {
        "table": fqtn,
        "format": table_format,
        "catalog": "Hive Metastore (SDX) via Spark3 Iceberg",
        "location": location,
        "snapshotId": str(snapshot_id) if snapshot_id is not None else None,
        "dataFiles": file_count,
        "rowCount": total,
        "columns": cols,
        "perLayer": per_layer,
        "rows": export_rows,
    }
    with open(args.export, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    print(f"Wrote export: {args.export} ({len(export_rows)} rows)")

    spark.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
