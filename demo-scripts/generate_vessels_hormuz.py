#!/usr/bin/env python3
"""
Generate a realistic synthetic AIS vessel dataset for the Strait of Hormuz.

Writes GeoJSON layers (one source of truth) consumed by:
  * the Entity Map web app (webapp/, via ENTITY_DIR)
  * GeoServer (geoserver/publish_entity.sh -> WMS/WFS)
  * HBase/COD (demo-scripts/phoenix_spatial_demo.py, via ENTITY_DIR)

Layers:
  vessels.geojson        ~115 vessel positions (Points) with AIS-like attributes
  vessel_tracks.geojson  recent tracks for a subset (LineStrings)
  shipping_lanes.geojson  the two TSS lane centerlines (LineStrings)

Deterministic (fixed seed). This is synthetic data (no public feed/key needed).

Usage:
    python3 generate_vessels_hormuz.py [--out DIR] [--seed N] [--count N]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random

# Strait of Hormuz TSS centerline, Gulf of Oman (SE) -> Persian Gulf (NW).
LANE = [
    [56.95, 26.25], [56.72, 26.40], [56.52, 26.55],
    [56.36, 26.70], [56.20, 26.86], [56.03, 27.00],
]
# Anchorages (lon, lat, radius_deg, count-weight)
ANCHORAGES = {
    "Fujairah": (56.42, 25.12, 0.09),
    "Bandar Abbas": (56.21, 27.14, 0.05),
    "Khasab": (56.26, 26.19, 0.03),
}

VESSEL_TYPES = [
    "Crude Oil Tanker", "LNG Carrier", "Container Ship", "Bulk Carrier",
    "Chemical Tanker", "LPG Carrier", "Product Tanker", "General Cargo",
    "Fishing", "Tug", "Offshore Supply", "Naval",
]
FLAGS = {  # flag -> MID prefix for MMSI
    "Liberia": "636", "Marshall Islands": "538", "Panama": "353", "Singapore": "563",
    "Iran": "422", "UAE": "470", "Saudi Arabia": "403", "India": "419", "Greece": "237",
}
DEST = ["RAS TANURA", "FUJAIRAH", "JEBEL ALI", "BANDAR ABBAS", "KHARG IS",
        "FOR ORDERS", "SINGAPORE", "SUEZ", "MINA AL AHMADI", "DAS ISLAND"]
NAME_A = ["Gulf", "Desert", "Pacific", "Orient", "Pearl", "Falcon", "Olympic",
          "Cosmic", "Eternal", "Silver", "Northern", "Crystal", "Horizon", "Atlantic"]
NAME_B = ["Pioneer", "Trader", "Voyager", "Spirit", "Star", "Pride", "Progress",
          "Explorer", "Guardian", "Harmony", "Endeavour", "Breeze", "Sunrise"]


def bearing(p1, p2):
    return (math.degrees(math.atan2(p2[0] - p1[0], p2[1] - p1[1])) + 360) % 360


def mmsi(rng, flag):
    return int(FLAGS[flag] + "".join(str(rng.randint(0, 9)) for _ in range(6)))


def vessel_props(rng, nav_status, sog, cog):
    flag = rng.choice(list(FLAGS))
    vtype = rng.choice(VESSEL_TYPES)
    length = {"Crude Oil Tanker": (250, 340), "LNG Carrier": (280, 345),
              "Container Ship": (200, 400), "Bulk Carrier": (180, 300)}.get(vtype, (40, 230))
    m = mmsi(rng, flag)
    return {
        "id": str(m),
        "mmsi": m,
        "name": f"{rng.choice(NAME_A)} {rng.choice(NAME_B)}",
        "type": vtype,
        "flag": flag,
        "nav_status": nav_status,
        "sog_kn": round(sog, 1),
        "cog_deg": round(cog, 1),
        "heading_deg": round((cog + rng.uniform(-5, 5)) % 360, 1),
        "length_m": rng.randint(*length),
        "draught_m": round(rng.uniform(5, 22), 1),
        "destination": rng.choice(DEST),
    }


def feature(geom, props):
    return {"type": "Feature", "properties": props, "geometry": geom}


def fc(name, feats):
    return {"type": "FeatureCollection", "name": name, "features": feats}


def point_on_lane(rng):
    seg = rng.randint(0, len(LANE) - 2)
    p1, p2 = LANE[seg], LANE[seg + 1]
    t = rng.random()
    lon = p1[0] + t * (p2[0] - p1[0])
    lat = p1[1] + t * (p2[1] - p1[1])
    cog = bearing(p1, p2)
    # Lateral offset for inbound vs outbound lane + jitter.
    direction = rng.choice([1, -1])
    perp = math.radians(cog + 90)
    off = direction * rng.uniform(0.004, 0.018)
    lon += off * math.cos(perp)
    lat += off * math.sin(perp)
    if direction < 0:
        cog = (cog + 180) % 360  # outbound travels opposite
    return [round(lon, 5), round(lat, 5)], cog


def main() -> int:
    ap = argparse.ArgumentParser(description="Strait of Hormuz synthetic AIS generator")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "webapp", "sample-data", "entity"))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--count", type=int, default=115, help="total vessels")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    os.makedirs(args.out, exist_ok=True)

    vessels = []
    n_moving = int(args.count * 0.55)
    for _ in range(n_moving):
        pos, cog = point_on_lane(rng)
        sog = rng.uniform(8, 16)
        vessels.append(feature({"type": "Point", "coordinates": pos},
                               vessel_props(rng, "Under way using engine", sog, cog)))
    # Anchored clusters.
    remaining = args.count - n_moving
    weights = [ANCHORAGES[a][2] for a in ANCHORAGES]
    for a, (clon, clat, rad) in ANCHORAGES.items():
        k = max(1, round(remaining * ANCHORAGES[a][2] / sum(weights)))
        for _ in range(k):
            lon = round(clon + rng.uniform(-rad, rad), 5)
            lat = round(clat + rng.uniform(-rad, rad), 5)
            vessels.append(feature({"type": "Point", "coordinates": [lon, lat]},
                                   vessel_props(rng, "At anchor", rng.uniform(0, 0.4), rng.uniform(0, 360))))

    # Recent tracks for a subset of moving vessels (follow the lane).
    tracks = []
    for i in range(14):
        seg = rng.randint(0, len(LANE) - 2)
        p1, p2 = LANE[seg], LANE[seg + 1]
        t0 = rng.random() * 0.5
        pts = []
        lon = p1[0] + t0 * (p2[0] - p1[0])
        lat = p1[1] + t0 * (p2[1] - p1[1])
        for _ in range(rng.randint(4, 7)):
            lon += (p2[0] - p1[0]) * 0.12 + rng.uniform(-0.004, 0.004)
            lat += (p2[1] - p1[1]) * 0.12 + rng.uniform(-0.004, 0.004)
            pts.append([round(lon, 5), round(lat, 5)])
        tracks.append(feature({"type": "LineString", "coordinates": pts}, {
            "id": f"trk-{i:03d}", "name": f"Track {i:03d}",
            "vessel_type": rng.choice(VESSEL_TYPES), "points": len(pts),
        }))

    lanes = [
        feature({"type": "LineString", "coordinates": LANE},
                {"id": "lane-inbound", "name": "TSS inbound lane", "direction": "NW (into Gulf)"}),
        feature({"type": "LineString", "coordinates": [[p[0] + 0.03, p[1] - 0.03] for p in LANE]},
                {"id": "lane-outbound", "name": "TSS outbound lane", "direction": "SE (to Gulf of Oman)"}),
    ]

    out = {
        "vessels": fc("vessels", vessels),
        "vessel_tracks": fc("vessel_tracks", tracks),
        "shipping_lanes": fc("shipping_lanes", lanes),
    }
    total = 0
    for layer, data in out.items():
        path = os.path.join(args.out, f"{layer}.geojson")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        total += len(data["features"])
        print(f"  wrote {path}  ({len(data['features'])} features)")
    print(f"Done. {total} features -> {os.path.abspath(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
