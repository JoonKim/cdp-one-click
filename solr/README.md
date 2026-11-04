# Solr / Cloudera Semantic Search — upgrade path

The web app ships an **in-app semantic search** (`webapp/semantic.py`, served at
`/search`) that needs **no extra cluster** — it runs TF-IDF + concept expansion
over the `geo_entity` records and renders the hits as a knowledge graph.

This folder is the **production upgrade path**: move that same search onto
**Apache Solr** via a **Cloudera Semantic Search** (or Data Discovery &
Exploration) Data Hub, with real embedding/vector (kNN) search.

## Why it isn't on the current clusters
COD is HBase/Phoenix only, and the Data Engineering Data Hub (`jkgeo-de`) has no
Solr service. Solr comes from a dedicated template — confirmed available in this
environment:
- `7.3.2 - Semantic Search for AWS`
- `7.3.2 - Data Discovery and Exploration - Spark3 for AWS`

## Steps (adds billable instances)
1. **Create a Solr Data Hub**
   ```bash
   cdp datahub create-aws-cluster --cluster-name jkgeo-search \
     --environment-name jkgeo-cdp-env \
     --cluster-definition-name "7.3.2 - Semantic Search for AWS"
   ```
2. **Create the collection** (Solr URL = `https://<host>/<cluster>/cdp-proxy-api/solr`)
   ```bash
   curl -u "$SOLR_USER:$SOLR_PASSWORD" \
     "$SOLR_URL/admin/collections?action=CREATE&name=geo_entity&numShards=1&replicationFactor=1"
   ```
3. **Apply the schema** (adds the text fields + a 384-dim `embedding` kNN vector field)
   ```bash
   curl -u "$SOLR_USER:$SOLR_PASSWORD" -H 'Content-Type: application/json' \
     -d @solr/geo_entity_fields.json "$SOLR_URL/geo_entity/schema"
   ```
4. **Index the geo_entity records** (same corpus as the in-app search)
   ```bash
   SOLR_URL=$SOLR_URL SOLR_USER=$SOLR_USER SOLR_PASSWORD=$SOLR_PASSWORD \
   python3 solr/index_to_solr.py --collection geo_entity --embed
   ```
   `--embed` adds dense-vector embeddings (needs `sentence-transformers`); without
   it you still get keyword search. You can also dump the docs without Solr:
   `python3 solr/index_to_solr.py --out /tmp/geo_solr_docs.json`.

## Keyword vs. semantic query
```bash
# keyword
curl -u "$U:$P" "$SOLR_URL/geo_entity/select?q=text:spoofing&rows=10"
# semantic (kNN over the embedding field; {queryVector} = embedding of the query text)
curl -u "$U:$P" "$SOLR_URL/geo_entity/select" --data-urlencode \
  'q={!knn f=embedding topK=10}[ ...queryVector... ]'
```

## Wiring the web app to Solr (instead of local TF-IDF)
Point `/api/search` at Solr by making `semantic_index()` call Solr's `select`
(keyword) or kNN (semantic) endpoint and mapping the returned docs into the same
`{results, graph}` shape. The knowledge-graph builder (`induced_graph`) is
engine-agnostic — it just needs the matched entity ids — so the `/search` page
and the graph view work unchanged whether the hits come from the local index,
HBase/Phoenix, or Solr.

## HBase → Solr (near-real-time, optional)
For live sync instead of batch indexing, use the **Lily HBase Indexer**
(hbase-indexer) to stream HBase edits on the `geo_entity` table into the Solr
collection via HBase replication.
