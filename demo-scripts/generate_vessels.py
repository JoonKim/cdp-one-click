#!/usr/bin/env python3
"""
Generate realistic synthetic AIS vessel datasets for a maritime region.

One source of truth -> Entity Map (webapp/), GeoServer (geoserver/), HBase/COD
(demo-scripts/phoenix_spatial_demo.py). Synthetic data: no public feed/key needed.

Regions:
  hormuz    Strait of Hormuz        (layers: vessels, vessel_tracks, shipping_lanes)
  chinasea  South China Sea         (layers: scs_vessels, scs_vessel_tracks, scs_shipping_lanes)

Each region writes three GeoJSON layers (prefixed per region so they coexist):
  <prefix>vessels         vessel positions (Points) with AIS-like attributes
  <prefix>vessel_tracks   recent tracks (LineStrings)
  <prefix>shipping_lanes  traffic-separation lane centerlines (LineStrings)

Usage:
    python3 generate_vessels.py --region chinasea [--out DIR] [--seed N] [--count N]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random

REGIONS = {
    "hormuz": {
        "prefix": "",
        "lane": [[56.95, 26.25], [56.72, 26.40], [56.52, 26.55],
                 [56.36, 26.70], [56.20, 26.86], [56.03, 27.00]],
        "anchorages": {"Fujairah": (56.42, 25.12, 0.09),
                       "Bandar Abbas": (56.21, 27.14, 0.05),
                       "Khasab": (56.26, 26.19, 0.03)},
        "flags": {"Liberia": "636", "Marshall Islands": "538", "Panama": "353",
                  "Singapore": "563", "Iran": "422", "UAE": "470",
                  "Saudi Arabia": "403", "India": "419", "Greece": "237"},
        "dest": ["RAS TANURA", "FUJAIRAH", "JEBEL ALI", "BANDAR ABBAS", "KHARG IS",
                 "FOR ORDERS", "SINGAPORE", "SUEZ", "MINA AL AHMADI", "DAS ISLAND"],
        "count": 115,
    },
    "chinasea": {
        "prefix": "scs_",
        "lane": [[105.5, 3.0], [108.5, 6.5], [111.0, 10.0],
                 [113.5, 14.0], [115.5, 18.0], [117.8, 21.3]],
        "anchorages": {"Hong Kong": (114.15, 22.05, 0.11),
                       "Vung Tau": (107.10, 10.35, 0.10),
                       "Manila Bay": (120.50, 14.50, 0.10),
                       "Singapore": (104.10, 1.25, 0.09)},
        "flags": {"China": "412", "Hong Kong": "477", "Singapore": "563",
                  "Panama": "353", "Liberia": "636", "Marshall Islands": "538",
                  "Philippines": "548", "Vietnam": "574", "Japan": "431"},
        "dest": ["SINGAPORE", "HONG KONG", "SHANGHAI", "KAOHSIUNG", "MANILA",
                 "HO CHI MINH", "LAEM CHABANG", "SHEKOU", "NINGBO", "BUSAN"],
        "count": 130,
    },
}

VESSEL_TYPES = ["Crude Oil Tanker", "LNG Carrier", "Container Ship", "Bulk Carrier",
                "Chemical Tanker", "LPG Carrier", "Product Tanker", "General Cargo",
                "Fishing", "Tug", "Offshore Supply", "Naval"]
NAME_A = ["Gulf", "Desert", "Pacific", "Orient", "Pearl", "Falcon", "Olympic", "Cosmic",
          "Eternal", "Silver", "Northern", "Crystal", "Horizon", "Atlantic", "Eastern"]
NAME_B = ["Pioneer", "Trader", "Voyager", "Spirit", "Star", "Pride", "Progress",
          "Explorer", "Guardian", "Harmony", "Endeavour", "Breeze", "Sunrise", "Dragon"]


def bearing(p1, p2):
    return (math.degrees(math.atan2(p2[0] - p1[0], p2[1] - p1[1])) + 360) % 360


def vessel_props(rng, region, nav_status, sog, cog):
    flags = region["flags"]
    flag = rng.choice(list(flags))
    vtype = rng.choice(VESSEL_TYPES)
    length = {"Crude Oil Tanker": (250, 340), "LNG Carrier": (280, 345),
              "Container Ship": (200, 400), "Bulk Carrier": (180, 300)}.get(vtype, (40, 230))
    m = int(flags[flag] + "".join(str(rng.randint(0, 9)) for _ in range(6)))
    return {
        "id": str(m), "mmsi": m,
        "name": f"{rng.choice(NAME_A)} {rng.choice(NAME_B)}",
        "type": vtype, "flag": flag, "nav_status": nav_status,
        "sog_kn": round(sog, 1), "cog_deg": round(cog, 1),
        "heading_deg": round((cog + rng.uniform(-5, 5)) % 360, 1),
        "length_m": rng.randint(*length), "draught_m": round(rng.uniform(5, 22), 1),
        "destination": rng.choice(region["dest"]),
    }


def feature(geom, props):
    return {"type": "Feature", "properties": props, "geometry": geom}


def fc(name, feats):
    return {"type": "FeatureCollection", "name": name, "features": feats}


def point_on_lane(rng, lane):
    seg = rng.randint(0, len(lane) - 2)
    p1, p2 = lane[seg], lane[seg + 1]
    t = rng.random()
    lon = p1[0] + t * (p2[0] - p1[0])
    lat = p1[1] + t * (p2[1] - p1[1])
    cog = bearing(p1, p2)
    direction = rng.choice([1, -1])
    perp = math.radians(cog + 90)
    off = direction * rng.uniform(0.02, 0.12)
    lon += off * math.cos(perp)
    lat += off * math.sin(perp)
    if direction < 0:
        cog = (cog + 180) % 360
    return [round(lon, 5), round(lat, 5)], cog


def build(region, rng, count):
    lane = region["lane"]
    vessels = []
    n_moving = int(count * 0.55)
    for _ in range(n_moving):
        pos, cog = point_on_lane(rng, lane)
        vessels.append(feature({"type": "Point", "coordinates": pos},
                               vessel_props(rng, region, "Under way using engine", rng.uniform(8, 16), cog)))
    remaining = count - n_moving
    wsum = sum(a[2] for a in region["anchorages"].values())
    for _, (clon, clat, rad) in region["anchorages"].items():
        k = max(1, round(remaining * rad / wsum))
        for _ in range(k):
            lon = round(clon + rng.uniform(-rad, rad), 5)
            lat = round(clat + rng.uniform(-rad, rad), 5)
            vessels.append(feature({"type": "Point", "coordinates": [lon, lat]},
                                   vessel_props(rng, region, "At anchor", rng.uniform(0, 0.4), rng.uniform(0, 360))))

    tracks = []
    for i in range(16):
        seg = rng.randint(0, len(lane) - 2)
        p1, p2 = lane[seg], lane[seg + 1]
        lon = p1[0] + rng.random() * 0.4 * (p2[0] - p1[0])
        lat = p1[1] + rng.random() * 0.4 * (p2[1] - p1[1])
        pts = []
        for _ in range(rng.randint(4, 7)):
            lon += (p2[0] - p1[0]) * 0.14 + rng.uniform(-0.05, 0.05)
            lat += (p2[1] - p1[1]) * 0.14 + rng.uniform(-0.05, 0.05)
            pts.append([round(lon, 5), round(lat, 5)])
        tracks.append(feature({"type": "LineString", "coordinates": pts},
                              {"id": f"trk-{i:03d}", "name": f"Track {i:03d}",
                               "vessel_type": rng.choice(VESSEL_TYPES), "points": len(pts)}))

    lanes = [
        feature({"type": "LineString", "coordinates": lane},
                {"id": "lane-main", "name": "Main shipping lane"}),
        feature({"type": "LineString", "coordinates": [[p[0] + 0.15, p[1] - 0.15] for p in lane]},
                {"id": "lane-alt", "name": "Secondary shipping lane"}),
    ]
    return vessels, tracks, lanes


def main() -> int:
    ap = argparse.ArgumentParser(description="Synthetic AIS vessel generator")
    ap.add_argument("--region", choices=sorted(REGIONS), default="chinasea")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "webapp", "sample-data", "entity"))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--count", type=int)
    args = ap.parse_args()

    region = REGIONS[args.region]
    prefix = region["prefix"]
    rng = random.Random(args.seed)
    os.makedirs(args.out, exist_ok=True)
    count = args.count or region["count"]

    vessels, tracks, lanes = build(region, rng, count)
    out = {
        f"{prefix}vessels": vessels,
        f"{prefix}vessel_tracks": tracks,
        f"{prefix}shipping_lanes": lanes,
    }
    total = 0
    for layer, feats in out.items():
        path = os.path.join(args.out, f"{layer}.geojson")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(fc(layer, feats), fh, indent=1)
        total += len(feats)
        print(f"  wrote {path}  ({len(feats)} features)")
    print(f"Done [{args.region}]. {total} features -> {os.path.abspath(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
