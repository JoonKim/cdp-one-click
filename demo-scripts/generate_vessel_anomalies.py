#!/usr/bin/env python3
"""
Generate synthetic AIS identity-theft anomalies (spoofing / zombie vessels).

Models two classic maritime anomalies:
  * Spoofing  - the SAME MMSI is reported in two impossible-to-reconcile places
                at once (e.g., South China Sea AND US waters). Rendered as a pair
                of points sharing one MMSI + a link line between them.
  * Zombie    - an MMSI that belongs to a scrapped/decommissioned vessel still
                transmitting. Rendered as single points in US waters.

Writes (into the entity directory, one source of truth -> map/GeoServer/HBase):
  vessel_anomalies.geojson  points, alert_type in {Spoofing, Zombie}
  spoof_links.geojson       LineStrings linking each spoofing pair

All anomaly features carry status=alert / severity=high so the Entity Map's
alert highlighting picks them up.

Usage:
    python3 generate_vessel_anomalies.py [--out DIR] [--seed N] [--pairs N] [--zombies N]
"""
from __future__ import annotations

import argparse
import json
import os
import random

# South China Sea sampling box (along the main lane).
SCS = (108.0, 118.0, 6.0, 20.0)  # lon_min, lon_max, lat_min, lat_max

# US coastal areas (lon, lat, radius_deg).
US_AREAS = {
    "Los Angeles / Long Beach": (-118.20, 33.72, 0.25),
    "San Francisco approaches": (-122.70, 37.70, 0.25),
    "Houston / Galveston": (-94.70, 29.30, 0.30),
    "New York / NJ": (-73.90, 40.50, 0.30),
    "Miami": (-80.10, 25.70, 0.25),
    "Savannah": (-80.80, 31.95, 0.25),
    "Seattle / Puget Sound": (-122.45, 47.90, 0.30),
}

FLAGS = {"China": "412", "Hong Kong": "477", "Singapore": "563", "Panama": "353",
         "Liberia": "636", "Marshall Islands": "538", "Vietnam": "574", "Malta": "248"}
TYPES = ["Crude Oil Tanker", "LNG Carrier", "Container Ship", "Bulk Carrier",
         "Chemical Tanker", "Product Tanker", "General Cargo", "Fishing"]
NAME_A = ["Gulf", "Pacific", "Orient", "Pearl", "Falcon", "Cosmic", "Silver",
          "Northern", "Crystal", "Horizon", "Atlantic", "Eastern", "Dragon"]
NAME_B = ["Pioneer", "Trader", "Voyager", "Spirit", "Star", "Pride", "Explorer",
          "Guardian", "Harmony", "Endeavour", "Sunrise", "Phoenix", "Fortune"]


def mmsi(rng, flag):
    return int(FLAGS[flag] + "".join(str(rng.randint(0, 9)) for _ in range(6)))


def feature(geom, props):
    return {"type": "Feature", "properties": props, "geometry": geom}


def fc(name, feats):
    return {"type": "FeatureCollection", "name": name, "features": feats}


def haversine_km(a, b):
    import math
    (lon1, lat1), (lon2, lat2) = a, b
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(h)))


def main() -> int:
    ap = argparse.ArgumentParser(description="Synthetic AIS spoofing/zombie generator")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "webapp", "sample-data", "entity"))
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--pairs", type=int, default=12, help="spoofing pairs (SCS <-> US)")
    ap.add_argument("--zombies", type=int, default=8)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    os.makedirs(args.out, exist_ok=True)

    anomalies = []
    links = []

    # Spoofing pairs: same MMSI/name/type, one in the SCS, one in US waters.
    for i in range(args.pairs):
        flag = rng.choice(list(FLAGS))
        m = mmsi(rng, flag)
        nm = f"{rng.choice(NAME_A)} {rng.choice(NAME_B)}"
        vt = rng.choice(TYPES)
        pair_id = f"spoof-{i:03d}"

        scs_pt = [round(rng.uniform(SCS[0], SCS[1]), 5), round(rng.uniform(SCS[2], SCS[3]), 5)]
        us_name, (clon, clat, rad) = rng.choice(list(US_AREAS.items()))
        us_pt = [round(clon + rng.uniform(-rad, rad), 5), round(clat + rng.uniform(-rad, rad), 5)]
        dist = haversine_km(scs_pt, us_pt)

        base = {"mmsi": m, "name": nm, "type": vt, "flag": flag,
                "alert_type": "Spoofing", "pair_id": pair_id,
                "status": "alert", "severity": "high"}
        anomalies.append(feature({"type": "Point", "coordinates": scs_pt}, dict(
            base, id=f"{pair_id}-a", region="South China Sea",
            note=f"MMSI {m} simultaneously reported in US waters (~{dist} km away)")))
        anomalies.append(feature({"type": "Point", "coordinates": us_pt}, dict(
            base, id=f"{pair_id}-b", region=f"US - {us_name}",
            note=f"MMSI {m} simultaneously reported in the South China Sea (~{dist} km away)")))
        links.append(feature({"type": "LineString", "coordinates": [scs_pt, us_pt]}, {
            "id": pair_id, "mmsi": m, "name": nm, "alert_type": "Spoofing",
            "distance_km": dist, "status": "alert", "severity": "high",
            "note": "Same MMSI in two places at once - physically impossible"}))

    # Zombie vessels: MMSI of a scrapped vessel still transmitting, in US waters.
    for i in range(args.zombies):
        flag = rng.choice(list(FLAGS))
        m = mmsi(rng, flag)
        us_name, (clon, clat, rad) = rng.choice(list(US_AREAS.items()))
        pt = [round(clon + rng.uniform(-rad, rad), 5), round(clat + rng.uniform(-rad, rad), 5)]
        anomalies.append(feature({"type": "Point", "coordinates": pt}, {
            "id": f"zombie-{i:03d}", "mmsi": m,
            "name": f"{rng.choice(NAME_A)} {rng.choice(NAME_B)}", "type": rng.choice(TYPES),
            "flag": flag, "alert_type": "Zombie", "region": f"US - {us_name}",
            "status": "alert", "severity": "high",
            "note": f"MMSI {m} belongs to a vessel scrapped in {rng.randint(2015, 2022)} - still transmitting"}))

    out = {"vessel_anomalies": fc("vessel_anomalies", anomalies),
           "spoof_links": fc("spoof_links", links)}
    total = 0
    for layer, data in out.items():
        path = os.path.join(args.out, f"{layer}.geojson")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        total += len(data["features"])
        print(f"  wrote {path}  ({len(data['features'])} features)")
    print(f"Done. {args.pairs} spoofing pairs + {args.zombies} zombies "
          f"= {total} features -> {os.path.abspath(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
