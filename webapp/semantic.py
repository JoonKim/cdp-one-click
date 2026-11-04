"""
Lightweight, self-contained semantic search over the geo_entity records
(the same data stored in COD/HBase and Iceberg) -- no Solr cluster required.

It builds a TF-IDF index over each entity's text, expands the query with a small
maritime concept/synonym map so natural-language queries match by meaning (e.g.
"ship pretending to be someone else" -> spoofing / identity theft), ranks by
cosine similarity, and builds the induced knowledge graph of the hits (entities
plus their ontology neighbours: type, flag, region, MMSI, anomaly, spoof pairs).

This is the "Option B" local stand-in for Cloudera Semantic Search (Solr +
embeddings). The Solr/embedding upgrade path lives under solr/.
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
from collections import Counter

STOP = set(
    "a an the of to in on at and or for with by from is are was were be been this that "
    "it its as into near around over under out up down no not vs via per".split()
)

# token -> related terms (concept expansion gives the search its "semantic" feel)
CONCEPTS = {
    "spoof": ["spoofing", "identity", "theft", "fake", "impossible", "mmsi", "two", "places", "alert"],
    "spoofing": ["identity", "theft", "fake", "impossible", "mmsi", "two", "places", "alert"],
    "identity": ["spoofing", "theft", "mmsi", "impersonation", "fake"],
    "theft": ["spoofing", "identity", "mmsi", "stolen"],
    "fake": ["spoofing", "fraud", "impersonation", "identity"],
    "fraud": ["spoofing", "fake", "anomaly", "alert"],
    "zombie": ["ghost", "dark", "dead", "anomaly", "alert"],
    "ghost": ["zombie", "dark", "anomaly"],
    "dark": ["zombie", "ghost", "anomaly"],
    "anomaly": ["spoofing", "zombie", "impossible", "alert", "suspicious", "high", "severity"],
    "suspicious": ["anomaly", "alert", "spoofing", "zombie"],
    "alert": ["anomaly", "warning", "high", "severity"],
    "threat": ["anomaly", "alert", "spoofing", "suspicious"],
    "fast": ["impossible", "speed", "knots", "quick"],
    "speed": ["impossible", "knots", "fast"],
    "impossible": ["speed", "knots", "spoofing", "anomaly"],
    "slow": ["anchored", "stopped", "moored"],
    "tug": ["tugboat", "tug"],
    "oil": ["tanker", "crude", "petroleum", "product"],
    "tanker": ["oil", "crude", "lng", "lpg", "product", "petroleum"],
    "crude": ["oil", "tanker", "petroleum"],
    "gas": ["lng", "lpg", "tanker"],
    "lng": ["gas", "tanker"],
    "fishing": ["trawler", "fishing"],
    "cargo": ["container", "bulk", "general", "freight"],
    "container": ["cargo", "freight", "ship"],
    "bulk": ["cargo", "carrier"],
    "naval": ["navy", "military", "warship"],
    "military": ["naval", "navy", "warship"],
    "vessel": ["ship", "boat", "vessel"],
    "ship": ["vessel", "boat"],
    "track": ["route", "path", "trajectory", "movement"],
    "route": ["track", "lane", "path", "shipping"],
    "sensor": ["station", "monitor", "detector"],
    "facility": ["terminal", "port", "depot", "station"],
    "incident": ["event", "alert", "report"],
    "port": ["terminal", "facility", "harbor"],
    # regions
    "hormuz": ["strait", "gulf", "persian", "oman"],
    "gulf": ["hormuz", "strait"],
    "china": ["south", "sea", "scs"],
    "scs": ["south", "china", "sea"],
    "pacific": ["ocean", "us", "america"],
    "francisco": ["san", "bay", "california"],
    "sf": ["san", "francisco", "bay"],
}
PHRASES = {
    "identity theft": ["spoofing", "identity", "theft", "mmsi", "impossible"],
    "same mmsi": ["spoofing", "identity", "mmsi", "two", "places"],
    "two places": ["spoofing", "impossible", "mmsi"],
    "impossible speed": ["impossible", "speed", "knots", "anomaly"],
    "dark vessel": ["zombie", "ghost", "dark"],
    "south china sea": ["south", "china", "sea", "scs"],
    "strait of hormuz": ["hormuz", "strait", "gulf"],
    "san francisco": ["san", "francisco", "bay"],
    "pretending to be": ["spoofing", "fake", "identity", "impersonation"],
}

LAYER_WORDS = {
    "scs_vessels": "south china sea vessel ship ais",
    "scs_vessel_tracks": "south china sea vessel track route movement",
    "scs_shipping_lanes": "south china sea shipping lane route",
    "vessels": "vessel ship ais strait hormuz",
    "vessel_tracks": "vessel track route movement strait hormuz",
    "vessel_anomalies": "vessel anomaly alert suspicious spoofing zombie",
    "spoof_links": "spoofing identity theft link anomaly impossible",
    "shipping_lanes": "shipping lane route corridor",
    "facilities": "facility terminal port depot san francisco",
    "incidents": "incident event alert report san francisco",
    "sensors": "sensor monitor detector san francisco",
    "stations": "station san francisco",
    "zones": "zone area region san francisco",
    "service_areas": "service area coverage san francisco",
    "routes": "route path san francisco",
    "delivery_routes": "delivery route logistics san francisco",
}
LAYER_CLASS = {
    "vessels": "Vessel", "scs_vessels": "Vessel", "vessel_anomalies": "Vessel",
    "vessel_tracks": "AisTrack", "scs_vessel_tracks": "AisTrack",
    "spoof_links": "SpoofLink",
    "shipping_lanes": "Route", "scs_shipping_lanes": "Route",
    "routes": "Route", "delivery_routes": "Route",
    "facilities": "Place", "stations": "Place", "sensors": "Place",
    "incidents": "Place", "zones": "Zone", "service_areas": "Zone",
}


def _centroid(geom):
    t = geom["type"]; c = geom["coordinates"]
    if t == "Point":
        pts = [c]
    elif t == "LineString":
        pts = c
    elif t == "Polygon":
        pts = c[0]
    elif t == "MultiPolygon":
        pts = [p for poly in c for p in poly[0]]
    else:
        pts = [c]
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _region(lon, lat):
    if 50 <= lon <= 62 and 20 <= lat <= 30:
        return "Strait of Hormuz"
    if 99 <= lon <= 126:
        return "South China Sea"
    if -125 <= lon <= -121 and 36 <= lat <= 39:
        return "San Francisco Bay"
    if -130 <= lon <= -60:
        return "US Waters"
    return "Open Ocean"


def tokenize(s):
    return [t for t in re.split(r"[^a-z0-9]+", s.lower()) if t and len(t) > 1 and t not in STOP]


class SemanticIndex:
    def __init__(self, entity_dir: str):
        self.entity_dir = entity_dir
        self.docs = self._load()
        self._build()

    def _load(self):
        docs = []
        paths = sorted(glob.glob(os.path.join(self.entity_dir, "*.geojson")))
        for path in paths:
            layer = os.path.splitext(os.path.basename(path))[0]
            try:
                data = json.load(open(path, encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            feats = data.get("features", []) if data.get("type") == "FeatureCollection" else [data]
            for i, ft in enumerate(feats):
                p = ft.get("properties", {}) or {}
                lon, lat = _centroid(ft["geometry"])
                region = p.get("region") or _region(lon, lat)
                vtype = p.get("type") or p.get("vessel_type")
                fields = [
                    p.get("name", ""), layer.replace("_", " "), LAYER_WORDS.get(layer, ""),
                    str(vtype or ""), str(p.get("flag") or ""), region,
                    str(p.get("alert_type") or ""), str(p.get("note") or ""),
                    str(p.get("destination") or ""), str(p.get("nav_status") or ""),
                    str(p.get("severity") or ""), str(p.get("status") or ""),
                ]
                text = " ".join(x for x in fields if x)
                docs.append({
                    "id": str(p.get("id", f"{layer}-{i}")),
                    "layer": layer,
                    "cls": LAYER_CLASS.get(layer, "Place"),
                    "name": str(p.get("name", p.get("id", f"{layer}-{i}"))),
                    "vtype": vtype, "flag": p.get("flag"), "region": region,
                    "alert_type": p.get("alert_type"), "mmsi": p.get("mmsi"),
                    "pair_id": p.get("pair_id"),
                    "note": p.get("note"),
                    "lon": round(lon, 4), "lat": round(lat, 4),
                    "text": text,
                })
        return docs

    def _build(self):
        self.df = Counter()
        self.doc_vec = []
        self.doc_norm = []
        tfs = []
        for d in self.docs:
            tf = Counter(tokenize(d["text"]))
            tfs.append(tf)
            for t in tf:
                self.df[t] += 1
        n = max(1, len(self.docs))
        self.idf = {t: math.log((n + 1) / (df + 1)) + 1 for t, df in self.df.items()}
        self._default_idf = math.log(n + 1) + 1
        for tf in tfs:
            v = {t: (1 + math.log(c)) * self.idf.get(t, 0) for t, c in tf.items()}
            norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
            self.doc_vec.append(v)
            self.doc_norm.append(norm)

    def _expand(self, q: str):
        toks = tokenize(q)
        exp = list(toks)
        for t in toks:
            exp += CONCEPTS.get(t, [])
        ql = q.lower()
        for phrase, terms in PHRASES.items():
            if phrase in ql:
                exp += terms
        return exp

    def search(self, q: str, k: int = 15):
        exp = self._expand(q)
        if not exp:
            return []
        qtf = Counter(exp)
        qv = {t: (1 + math.log(c)) * self.idf.get(t, self._default_idf) for t, c in qtf.items()}
        qnorm = math.sqrt(sum(x * x for x in qv.values())) or 1.0
        scored = []
        for i, dv in enumerate(self.doc_vec):
            dot = sum(w * dv.get(t, 0) for t, w in qv.items())
            if dot <= 0:
                continue
            scored.append((dot / (qnorm * self.doc_norm[i]), i))
        scored.sort(reverse=True)
        out = []
        for s, i in scored[:k]:
            d = self.docs[i]
            out.append({
                "id": d["id"], "layer": d["layer"], "cls": d["cls"], "name": d["name"],
                "vtype": d["vtype"], "flag": d["flag"], "region": d["region"],
                "alert_type": d["alert_type"], "mmsi": d["mmsi"], "note": d["note"],
                "lon": d["lon"], "lat": d["lat"], "score": round(float(s), 3),
            })
        return out

    # ---- induced knowledge graph of the hits ----
    def induced_graph(self, hit_ids):
        by_id = {d["id"]: d for d in self.docs}
        hits = [by_id[i] for i in hit_ids if i in by_id]
        nodes, edges, seen = {}, [], set()

        def node(ntype, key, label, **extra):
            nid = f"{ntype}:{key}"
            if nid not in nodes:
                nodes[nid] = {"id": nid, "type": ntype, "label": label, **extra}
            return nid

        def edge(s, rel, t):
            k = (s, rel, t)
            if s and t and k not in seen:
                seen.add(k)
                edges.append({"source": s, "target": t, "rel": rel})

        # index spoof pairs so an anomaly hit pulls in its "other place" partner
        pairs = {}
        for d in self.docs:
            if d.get("pair_id"):
                pairs.setdefault(d["pair_id"], []).append(d)

        def add_entity(d, hit=False):
            nid = node(d["cls"], d["id"], d["name"], layer=d["layer"], hit=hit,
                       score=d.get("score"), region=d.get("region"), alert=d.get("alert_type"))
            edge(nid, "operatesIn", node("Region", d["region"], d["region"]))
            if d.get("vtype"):
                edge(nid, "hasType", node("VesselType", d["vtype"], d["vtype"]))
            if d.get("flag"):
                edge(nid, "flaggedAs", node("Flag", d["flag"], d["flag"]))
            if d.get("mmsi") is not None:
                edge(nid, "broadcasts", node("Mmsi", str(d["mmsi"]), f"MMSI {d['mmsi']}"))
            if d.get("alert_type"):
                edge(nid, "classifiedAs", node("AnomalyType", d["alert_type"], d["alert_type"]))
            return nid

        for d in hits:
            nid = add_entity(d, hit=True)
            # bring in the spoofing partner (same MMSI, "two places")
            if d.get("pair_id"):
                for partner in pairs.get(d["pair_id"], []):
                    if partner["id"] != d["id"]:
                        pnid = add_entity(partner, hit=False)
                        edge(nid, "sharesIdentityWith", pnid)

        return {"nodes": list(nodes.values()), "edges": edges}
