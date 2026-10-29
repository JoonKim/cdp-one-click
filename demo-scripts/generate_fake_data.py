#!/usr/bin/env python3
"""
Generate richer fake geospatial datasets (GeoJSON) for the demo.

One source of truth: the files written here are read by
  * the Entity Map web app  (webapp/, via ENTITY_DIR)
  * the local GeoServer stack (geoserver/publish_entity.sh -> WMS/WFS layers)
  * HBase/COD                (demo-scripts/phoenix_spatial_demo.py or the
                              geohash loader, via ENTITY_DIR)

Deterministic (fixed seed) so the committed data is stable and reproducible.

Usage:
    python3 generate_fake_data.py [--out DIR] [--seed N] [--scale F]
Default --out is ../webapp/sample-data/entity (adds new layers alongside the
existing stations/zones/routes). Existing files are not overwritten unless the
layer names collide.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random

# Bounding box over San Francisco (lon/lat) so it overlays the existing data + OSM tiles.
LON_MIN, LON_MAX = -122.455, -122.385
LAT_MIN, LAT_MAX = 37.740, 37.810

FIRST = ["North", "South", "East", "West", "Bay", "Market", "Mission", "Marina",
         "Sunset", "Richmond", "Central", "Harbor", "Hill", "Park", "Union"]
SECOND = ["Gate", "Station", "Depot", "Yard", "Hub", "Point", "Plaza", "Terminal",
          "Junction", "Works", "Center", "Landing", "Field", "Crossing"]


def rnd_point(rng):
    return [round(rng.uniform(LON_MIN, LON_MAX), 5), round(rng.uniform(LAT_MIN, LAT_MAX), 5)]


def name(rng):
    return f"{rng.choice(FIRST)} {rng.choice(SECOND)}"


def feature(geom, props):
    return {"type": "Feature", "properties": props, "geometry": geom}


def fc(name_, feats):
    return {"type": "FeatureCollection", "name": name_, "features": feats}


def gen_points(rng, layer, n, prop_fn):
    feats = []
    for i in range(n):
        lon, lat = rnd_point(rng)
        props = {"id": f"{layer[:3]}-{i:03d}", "name": name(rng)}
        props.update(prop_fn(rng))
        feats.append(feature({"type": "Point", "coordinates": [lon, lat]}, props))
    return fc(layer, feats)


def gen_lines(rng, layer, n, prop_fn):
    feats = []
    for i in range(n):
        lon, lat = rnd_point(rng)
        pts = [[lon, lat]]
        for _ in range(rng.randint(3, 6)):
            lon = round(min(max(lon + rng.uniform(-0.012, 0.012), LON_MIN), LON_MAX), 5)
            lat = round(min(max(lat + rng.uniform(-0.010, 0.010), LAT_MIN), LAT_MAX), 5)
            pts.append([lon, lat])
        props = {"id": f"{layer[:3]}-{i:03d}", "name": name(rng)}
        props.update(prop_fn(rng))
        feats.append(feature({"type": "LineString", "coordinates": pts}, props))
    return fc(layer, feats)


def gen_polygons(rng, layer, n, prop_fn):
    feats = []
    for i in range(n):
        cx, cy = rnd_point(rng)
        k = rng.randint(5, 7)
        r = rng.uniform(0.004, 0.012)
        ring = []
        for j in range(k):
            ang = 2 * math.pi * j / k
            ring.append([round(cx + r * math.cos(ang), 5), round(cy + r * math.sin(ang) * 0.8, 5)])
        ring.append(ring[0])
        props = {"id": f"{layer[:3]}-{i:03d}", "name": name(rng)}
        props.update(prop_fn(rng))
        feats.append(feature({"type": "Polygon", "coordinates": [ring]}, props))
    return fc(layer, feats)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate fake geospatial datasets")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "webapp", "sample-data", "entity"))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--scale", type=float, default=1.0, help="multiply feature counts")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    s = args.scale
    os.makedirs(args.out, exist_ok=True)

    datasets = {
        "sensors": gen_points(rng, "sensors", int(60 * s), lambda r: {
            "kind": r.choice(["temperature", "air_quality", "noise", "traffic"]),
            "status": r.choice(["ok", "ok", "ok", "warning", "alert"]),
            "reading": round(r.uniform(0, 100), 1),
        }),
        "incidents": gen_points(rng, "incidents", int(35 * s), lambda r: {
            "type": r.choice(["outage", "accident", "alarm", "maintenance"]),
            "severity": r.choice(["low", "medium", "high"]),
            "open": r.choice([True, False]),
        }),
        "facilities": gen_points(rng, "facilities", int(24 * s), lambda r: {
            "kind": r.choice(["depot", "office", "substation", "warehouse"]),
            "capacity": r.randint(20, 500),
        }),
        "delivery_routes": gen_lines(rng, "delivery_routes", int(14 * s), lambda r: {
            "mode": r.choice(["truck", "drone", "bike", "van"]),
            "stops": r.randint(3, 12),
            "active": r.choice([True, False]),
        }),
        "service_areas": gen_polygons(rng, "service_areas", int(10 * s), lambda r: {
            "tier": r.choice(["gold", "silver", "bronze"]),
            "population": r.randint(500, 50000),
        }),
    }

    total = 0
    for layer, data in datasets.items():
        path = os.path.join(args.out, f"{layer}.geojson")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        n = len(data["features"])
        total += n
        print(f"  wrote {path}  ({n} features)")
    print(f"Done. {total} features across {len(datasets)} layers -> {os.path.abspath(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
