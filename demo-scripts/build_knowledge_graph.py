#!/usr/bin/env python3
"""
Build an ontology / knowledge-graph layer from the geospatial entity datasets.

It turns the maritime AIS anomaly data (spoofing identity-theft pairs, zombie
vessels, and the featured track trk-013) into:

  * a property graph (nodes + edges) as JSON for the web "Knowledge Graph" view
    and the storyboard, and
  * a formal ontology + instances as RDF/Turtle (ontology.ttl) that loads into a
    graph database / triplestore (GraphDB, Jena, rdflib, Neo4j via neosemantics).

Ontology (classes):  Vessel, AisTrack, VesselType, Mmsi, Flag, Region, AnomalyType
Predicates:          hasType, operatesIn, flaggedAs, broadcasts, classifiedAs,
                     sharesIdentityWith  (same MMSI reported in two places)

Usage:
    python3 demo-scripts/build_knowledge_graph.py
    # writes webapp/sample-data/graph/knowledge_graph.json and ontology.ttl
"""
from __future__ import annotations

import json
import math
import os
import re

BASE = os.path.join(os.path.dirname(__file__), "..", "webapp", "sample-data")
ENTITY = os.path.join(BASE, "entity")
OUT = os.path.join(BASE, "graph")

KM2KN = 0.539957
TYPEMAX = {
    "Tug": 13, "Fishing": 15, "Offshore Supply": 14, "Naval": 32, "Bulk Carrier": 26,
    "Crude Oil Tanker": 17, "Product Tanker": 18, "LNG Carrier": 21,
    "LPG Carrier": 19, "General Cargo": 22, "Container Ship": 26,
}

CLASSES = {
    "Vessel": {"color": "#38bdf8", "desc": "An AIS-broadcasting vessel"},
    "AisTrack": {"color": "#22d3ee", "desc": "A sequence of AIS positions"},
    "VesselType": {"color": "#a78bfa", "desc": "Declared vessel category"},
    "Mmsi": {"color": "#f59e0b", "desc": "Maritime identity number broadcast by a vessel"},
    "Flag": {"color": "#34d399", "desc": "Flag state / registry"},
    "Region": {"color": "#60a5fa", "desc": "Operating area"},
    "AnomalyType": {"color": "#ef4444", "desc": "Class of detected anomaly"},
}
PREDICATES = {
    "hasType": ("Vessel|AisTrack", "VesselType"),
    "operatesIn": ("Vessel|AisTrack", "Region"),
    "flaggedAs": ("Vessel", "Flag"),
    "broadcasts": ("Vessel", "Mmsi"),
    "classifiedAs": ("Vessel|AisTrack", "AnomalyType"),
    "sharesIdentityWith": ("Vessel", "Vessel"),
}


def load(name):
    with open(os.path.join(ENTITY, f"{name}.geojson"), encoding="utf-8") as fh:
        return json.load(fh)["features"]


def haversine(a, b):
    R = 6371.0
    lon1, lat1 = a; lon2, lat2 = b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1); dl = math.radians(lon2 - lon1)
    x = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


class Graph:
    def __init__(self):
        self.nodes = {}
        self.edges = []
        self._edgeset = set()

    def node(self, ntype, key, label, **props):
        nid = f"{ntype}:{key}"
        if nid not in self.nodes:
            self.nodes[nid] = {"id": nid, "type": ntype, "label": label, **props}
        return nid

    def edge(self, src, rel, dst):
        k = (src, rel, dst)
        if src and dst and k not in self._edgeset:
            self._edgeset.add(k)
            self.edges.append({"source": src, "target": dst, "rel": rel})


def build():
    g = Graph()

    anomalies = load("vessel_anomalies")
    # Vessels + their attributes + anomaly classification.
    pairs = {}  # pair_id -> [node_ids]
    for ft in anomalies:
        p = ft["properties"]
        vid = g.node("Vessel", p["id"], p.get("name", p["id"]),
                     alert=p.get("alert_type"), severity=p.get("severity"))
        if p.get("type"):
            g.edge(vid, "hasType", g.node("VesselType", p["type"], p["type"]))
        if p.get("flag"):
            g.edge(vid, "flaggedAs", g.node("Flag", p["flag"], p["flag"]))
        if p.get("region"):
            g.edge(vid, "operatesIn", g.node("Region", p["region"], p["region"]))
        if p.get("mmsi") is not None:
            g.edge(vid, "broadcasts", g.node("Mmsi", str(p["mmsi"]), f"MMSI {p['mmsi']}"))
        if p.get("alert_type"):
            g.edge(vid, "classifiedAs",
                   g.node("AnomalyType", p["alert_type"], p["alert_type"]))
        if p.get("pair_id"):
            pairs.setdefault(p["pair_id"], []).append(vid)

    # Identity theft: the two endpoints that share one MMSI.
    for members in pairs.values():
        if len(members) == 2:
            g.edge(members[0], "sharesIdentityWith", members[1])

    # Featured track trk-013 (South China Sea) -> impossible speed.
    for ft in load("scs_vessel_tracks"):
        p = ft["properties"]
        if p["id"] != "trk-013":
            continue
        co = ft["geometry"]["coordinates"]
        speeds = [haversine(co[i - 1], co[i]) * KM2KN for i in range(1, len(co))]
        avg = sum(speeds) / len(speeds)
        vt = p.get("vessel_type", "Tug")
        ratio = avg / TYPEMAX.get(vt, 25)
        tid = g.node("AisTrack", p["id"], p.get("name", p["id"]),
                     avg_speed_kn=round(avg, 1), type_max_kn=TYPEMAX.get(vt, 25),
                     impossibility_ratio=round(ratio, 2), featured=True)
        g.edge(tid, "hasType", g.node("VesselType", vt, vt))
        g.edge(tid, "operatesIn", g.node("Region", "South China Sea", "South China Sea"))
        g.edge(tid, "classifiedAs",
               g.node("AnomalyType", "Impossible Speed", "Impossible Speed"))

    counts = {}
    for n in g.nodes.values():
        counts[n["type"]] = counts.get(n["type"], 0) + 1

    graph = {
        "ontology": {
            "classes": [{"name": k, **v} for k, v in CLASSES.items()],
            "predicates": [{"name": k, "domain": d, "range": r}
                           for k, (d, r) in PREDICATES.items()],
        },
        "stats": {"nodes": len(g.nodes), "edges": len(g.edges), "byClass": counts},
        "nodes": list(g.nodes.values()),
        "edges": g.edges,
    }
    return g, graph


# ---- RDF / Turtle export (loadable into a triplestore / graph DB) ----
NS = "http://cdp.demo/geo#"


def iri(nid):
    return "geo:" + re.sub(r"[^A-Za-z0-9_]", "_", nid)


def to_turtle(g):
    lines = [
        "@prefix geo: <%s> ." % NS,
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "",
        "# ---- Ontology: classes ----",
    ]
    for c in CLASSES:
        lines.append(f"geo:{c} a owl:Class ; rdfs:label \"{c}\" .")
    lines += ["", "# ---- Ontology: object properties (domain/range) ----"]
    for p, (dom, rng) in PREDICATES.items():
        doms = " , ".join(f"geo:{d}" for d in dom.split("|"))
        lines.append(
            f"geo:{p} a owl:ObjectProperty ; rdfs:domain {doms} ; rdfs:range geo:{rng} ."
        )
    lines += ["", "# ---- Instances ----"]
    cls_of = {n["id"]: n["type"] for n in g.nodes.values()}
    for n in g.nodes.values():
        lbl = n["label"].replace('"', '\\"')
        lines.append(f"{iri(n['id'])} a geo:{n['type']} ; rdfs:label \"{lbl}\" .")
    lines.append("")
    for e in g.edges:
        lines.append(f"{iri(e['source'])} geo:{e['rel']} {iri(e['target'])} .")
    return "\n".join(lines) + "\n"


def main():
    os.makedirs(OUT, exist_ok=True)
    g, graph = build()
    with open(os.path.join(OUT, "knowledge_graph.json"), "w", encoding="utf-8") as fh:
        json.dump(graph, fh)
    with open(os.path.join(OUT, "ontology.ttl"), "w", encoding="utf-8") as fh:
        fh.write(to_turtle(g))
    print("nodes:", graph["stats"]["nodes"], "edges:", graph["stats"]["edges"])
    print("by class:", graph["stats"]["byClass"])
    print("wrote:", os.path.join(OUT, "knowledge_graph.json"))
    print("wrote:", os.path.join(OUT, "ontology.ttl"))


if __name__ == "__main__":
    main()
