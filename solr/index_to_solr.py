#!/usr/bin/env python3
"""
Index the geo_entity records into a Solr collection on a Cloudera Semantic
Search / Data Discovery & Exploration (DDE) Data Hub -- the production upgrade
path for the in-app semantic search (webapp/semantic.py).

This is the "Option A" bridge. It reads the same geo_entity documents (from the
GeoJSON that was loaded into COD/HBase + Iceberg) and posts them to Solr over
Knox. Optionally it adds dense-vector embeddings so Solr can do semantic (kNN)
search instead of only keyword search.

Prereqs:
  * A Solr-bearing Data Hub, e.g.  cdp datahub create-aws-cluster \
        --cluster-name jkgeo-search --environment-name jkgeo-cdp-env \
        --cluster-definition-name "7.3.2 - Semantic Search for AWS"
  * A collection:  curl -u user:pw "<solr>/admin/collections?action=CREATE&name=geo_entity&numShards=1&replicationFactor=1"
  * Apply the schema:  curl -u user:pw -H 'Content-Type: application/json' \
        -d @solr/geo_entity_fields.json  "<solr>/geo_entity/schema"

Usage:
  SOLR_URL=https://<host>/<cluster>/cdp-proxy-api/solr \
  SOLR_USER=joonkim_0 SOLR_PASSWORD=... \
  python3 solr/index_to_solr.py --collection geo_entity --entity-dir webapp/sample-data/entity [--embed]

With --embed it uses sentence-transformers (all-MiniLM-L6-v2, 384-dim) if
installed; otherwise it indexes text-only (keyword search still works).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

# Reuse the exact document builder from the web app's semantic layer so the Solr
# index matches the in-app search corpus one-to-one.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webapp"))


def build_docs(entity_dir):
    from semantic import SemanticIndex  # same fields/regions/classes

    idx = SemanticIndex(entity_dir)
    docs = []
    for d in idx.docs:
        docs.append({
            "id": f"{d['layer']}:{d['id']}",
            "layer": d["layer"], "cls": d["cls"], "name": d["name"],
            "vtype": d.get("vtype"), "flag": d.get("flag"), "region": d["region"],
            "alert_type": d.get("alert_type"),
            "mmsi": None if d.get("mmsi") is None else str(d["mmsi"]),
            "note": d.get("note"), "lon": d["lon"], "lat": d["lat"], "text": d["text"],
        })
    return docs


def add_embeddings(docs):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("sentence-transformers not installed -> indexing text-only "
              "(keyword search). pip install sentence-transformers for semantic kNN.",
              file=sys.stderr)
        return docs
    model = SentenceTransformer("all-MiniLM-L6-v2")
    vecs = model.encode([d["text"] for d in docs], normalize_embeddings=True)
    for d, v in zip(docs, vecs):
        d["embedding"] = [float(x) for x in v]
    print(f"added {len(vecs[0])}-dim embeddings to {len(docs)} docs")
    return docs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solr-url", default=os.environ.get("SOLR_URL"))
    ap.add_argument("--collection", default=os.environ.get("SOLR_COLLECTION", "geo_entity"))
    ap.add_argument("--user", default=os.environ.get("SOLR_USER"))
    ap.add_argument("--password", default=os.environ.get("SOLR_PASSWORD"))
    ap.add_argument("--entity-dir", default=os.environ.get(
        "ENTITY_DIR", os.path.join(os.path.dirname(__file__), "..", "webapp", "sample-data", "entity")))
    ap.add_argument("--embed", action="store_true", help="add dense-vector embeddings for semantic kNN")
    ap.add_argument("--out", help="write docs to a JSON file instead of posting to Solr")
    args = ap.parse_args()

    docs = build_docs(args.entity_dir)
    if args.embed:
        docs = add_embeddings(docs)
    print(f"built {len(docs)} documents from {args.entity_dir}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(docs, fh)
        print("wrote", args.out)
        return 0

    if not args.solr_url:
        print("SOLR_URL not set; use --out to dump docs, or set SOLR_URL to post.", file=sys.stderr)
        return 2

    import requests

    url = f"{args.solr_url.rstrip('/')}/{args.collection}/update?commit=true"
    auth = (args.user, args.password) if args.user else None
    resp = requests.post(url, json=docs, auth=auth, timeout=120,
                         headers={"Content-Type": "application/json"})
    print("Solr response:", resp.status_code, resp.text[:300])
    return 0 if resp.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
