#!/usr/bin/env python3
"""
Phoenix spatial demo for COD (Cloudera Operational Database).

Connects to COD's Phoenix Query Server through the Knox gateway using the
Phoenix *thin* client (Avatica over HTTPS with BASIC auth) -- no ZooKeeper and
no Kerberos required on the client side. It creates a small spatial table from
the GeoJSON datasets in the entity directory and runs SQL spatial queries
(bounding-box intersect, point-in-window, and nearest-N).

This is the SQL companion to the GeoMesa/HBase geospatial flow: GeoMesa's
command-line tools can't negotiate CDP's TLS-secured ZooKeeper, but the Phoenix
thin client goes over HTTPS/Knox and works cleanly.

Prerequisites:
    pip install phoenixdb            # needs build deps: python3-dev, libkrb5-dev, gcc
                                     # (gssapi is pulled in but only BASIC auth is used)

Configuration (env vars or flags):
    PHOENIX_URL       Avatica endpoint, e.g. the phoenix-thin-jdbc URL from
                      `cdp opdb describe-client-connectivity` with the
                      `jdbc:phoenix:thin:url=` prefix and `;...` params stripped:
                      https://<gateway>/<cod>/cdp-proxy-api/avatica/
    PHOENIX_USER      CDP workload username (e.g. joonkim_0)
    PHOENIX_PASSWORD  CDP workload password
    ENTITY_DIR        GeoJSON directory (default: ../webapp/sample-data/entity)
    PHOENIX_VERIFY    'true' (default; *.cloudera.site uses a public cert),
                      'false', or a path to a CA bundle/truststore
    PHOENIX_TABLE     Phoenix table name (default: geo_entity)

Usage:
    PHOENIX_URL=https://host/cod/cdp-proxy-api/avatica/ \
    PHOENIX_USER=joonkim_0 PHOENIX_PASSWORD=... \
    python3 phoenix_spatial_demo.py
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys


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
    for path in sorted(glob.glob(os.path.join(entity_dir, "*.geojson"))) + sorted(
        glob.glob(os.path.join(entity_dir, "*.json"))
    ):
        layer = os.path.splitext(os.path.basename(path))[0]
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        feats = data.get("features", []) if data.get("type") == "FeatureCollection" else [data]
        for feat in feats:
            props = feat.get("properties", {})
            clon, clat, minx, miny, maxx, maxy = centroid_and_bbox(feat["geometry"])
            rows.append(
                (
                    layer,
                    str(props.get("id", f"{layer}-{len(rows)}")),
                    str(props.get("name", "")),
                    feat["geometry"]["type"],
                    clon,
                    clat,
                    minx,
                    miny,
                    maxx,
                    maxy,
                    json.dumps(feat["geometry"]),
                )
            )
    return rows


def resolve_verify(value: str):
    if value.lower() in ("true", "1", "yes"):
        return True
    if value.lower() in ("false", "0", "no"):
        return False
    return value  # path to a CA bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Phoenix spatial demo for COD")
    parser.add_argument("--url", default=os.environ.get("PHOENIX_URL"))
    parser.add_argument("--user", default=os.environ.get("PHOENIX_USER"))
    parser.add_argument("--password", default=os.environ.get("PHOENIX_PASSWORD"))
    parser.add_argument(
        "--entity-dir",
        default=os.environ.get(
            "ENTITY_DIR",
            os.path.join(os.path.dirname(__file__), "..", "webapp", "sample-data", "entity"),
        ),
    )
    parser.add_argument("--table", default=os.environ.get("PHOENIX_TABLE", "geo_entity"))
    parser.add_argument("--verify", default=os.environ.get("PHOENIX_VERIFY", "true"))
    args = parser.parse_args()

    try:
        import phoenixdb
    except ImportError as exc:
        print(
            f"phoenixdb is not available ({exc}). Install it:\n"
            "  macOS:  brew install krb5 && "
            'export PATH="$(brew --prefix krb5)/bin:$PATH" && '
            "pip install -r demo-scripts/requirements-phoenix.txt\n"
            "  Linux:  sudo apt-get install -y python3-dev libkrb5-dev gcc && "
            "pip install -r demo-scripts/requirements-phoenix.txt",
            file=sys.stderr,
        )
        return 2

    if not args.url or not args.user or args.password is None:
        print("ERROR: PHOENIX_URL, PHOENIX_USER and PHOENIX_PASSWORD are required.", file=sys.stderr)
        return 2

    table = args.table
    rows = load_features(args.entity_dir)
    print(f"Loaded {len(rows)} features from {args.entity_dir}")

    conn = phoenixdb.connect(
        args.url,
        autocommit=True,
        authentication="BASIC",
        avatica_user=args.user,
        avatica_password=args.password,
        verify=resolve_verify(args.verify),
    )
    cur = conn.cursor()

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table} (
            layer VARCHAR NOT NULL,
            id VARCHAR NOT NULL,
            name VARCHAR,
            geom_type VARCHAR,
            center_lon DOUBLE, center_lat DOUBLE,
            min_lon DOUBLE, min_lat DOUBLE, max_lon DOUBLE, max_lat DOUBLE,
            geojson VARCHAR
            CONSTRAINT pk PRIMARY KEY (layer, id)
        )
        """
    )
    upsert_sql = f"""UPSERT INTO {table}
                (layer, id, name, geom_type, center_lon, center_lat,
                 min_lon, min_lat, max_lon, max_lat, geojson)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)"""
    # A freshly CREATEd table's regions may not be online for the very first
    # write, surfacing as a transient CommitException/RetriesExhausted. Retry.
    import time

    for attempt in range(1, 6):
        try:
            for r in rows:
                cur.execute(upsert_sql, r)
            break
        except phoenixdb.errors.Error as exc:
            msg = str(exc)
            if attempt < 5 and ("RetriesExhausted" in msg or "CommitException" in msg):
                print(f"   (transient write error, retrying {attempt}/5 after new-table warm-up...)")
                time.sleep(5)
                continue
            raise
    print(f"Upserted into Phoenix table '{table}'.\n")

    def run(title, sql, params=()):
        print(f"== {title} ==")
        print(f"   SQL: {' '.join(sql.split())}")
        cur.execute(sql, params)
        for row in cur.fetchall():
            print("   ->", row)
        print()

    run("Feature count by layer", f"SELECT layer, COUNT(*) FROM {table} GROUP BY layer")

    # Bounding-box intersect: features whose bbox overlaps the query window.
    # Query window = downtown SF core (minlon, minlat, maxlon, maxlat).
    qminlon, qminlat, qmaxlon, qmaxlat = -122.410, 37.785, -122.395, 37.800
    run(
        f"Bounding-box intersect [{qminlon},{qminlat} .. {qmaxlon},{qmaxlat}] (downtown core)",
        f"""SELECT name, layer, geom_type FROM {table}
            WHERE min_lon <= ? AND max_lon >= ? AND min_lat <= ? AND max_lat >= ?""",
        (qmaxlon, qminlon, qmaxlat, qminlat),
    )

    # Point-in-window: features whose centroid falls in a (southern/Mission) window.
    run(
        "Centroid-in-window (Mission district: lon -122.43..-122.41, lat 37.75..37.775)",
        f"""SELECT name, layer, center_lat, center_lon FROM {table}
            WHERE center_lon BETWEEN ? AND ? AND center_lat BETWEEN ? AND ?""",
        (-122.43, -122.41, 37.75, 37.775),
    )

    # Nearest-N to a point (Embarcadero ~ -122.3971, 37.7929) by squared distance.
    plon, plat = -122.3971, 37.7929
    run(
        f"3 nearest features to ({plat}, {plon}) (Embarcadero)",
        f"""SELECT name, layer, center_lat, center_lon FROM {table}
            ORDER BY (center_lon - ?) * (center_lon - ?) + (center_lat - ?) * (center_lat - ?)
            LIMIT 3""",
        (plon, plon, plat, plat),
    )

    cur.close()
    conn.close()
    print("Phoenix spatial demo complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
