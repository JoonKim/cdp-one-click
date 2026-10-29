# 5‑Minute Demo Script — CDP Geospatial Anomaly Demo

**Goal:** show one vessel dataset, governed once, served two ways (operational **HBase/Phoenix** + analytical **Iceberg**), visualized in a web app, and narrated through the **trk‑013** anomaly storyboard — in under 5 minutes.

**Before you start (2–3 min, off camera):** the stack auto‑stops to save cost. Restart it:
```bash
./cdp_demo_start.sh parameters/parameters_aws_sandbox.json     # env → data lake → COD + Data Hub
cd webapp && ./run.sh                                          # local web app on :8888
```
Open tabs: **Entity Map** `http://127.0.0.1:8888/`, **Storyboard** `/story`, **Iceberg Table** `/table`, **Dashboard** `/dashboard`.

> Timings are cumulative. Lines in quotes are what you say; `[ ]` are what you click.

---

## 0:00 – 0:30 · Hook + what it is
> "This is a geospatial anomaly‑detection demo running on **Cloudera Data Platform in AWS**. The same AIS vessel data is stored two ways — an **operational** copy in HBase and an **analytical** copy in Iceberg — and visualized in a web app. I'll walk one real anomaly end to end."

`[Open the Services Dashboard /dashboard — the architecture diagram + green service cards]`

## 0:30 – 1:30 · Architecture — how each service works (one line each)
> "Everything sits on one **CDP Environment** — **FreeIPA** gives us Kerberos identity, DNS, and a security realm."
> "The **SDX Data Lake** is shared governance for every engine: **Ranger** for access policies, **Atlas** for lineage, the **Hive Metastore** for shared table schemas, and **IDBroker** to broker S3 access — set once, enforced everywhere."
> "**COD — the Operational Database** — is **HBase** for low‑latency key‑value storage, with **Phoenix** adding a SQL layer on top so we can query HBase with SQL."
> "The **Data Hub** is our compute: **Spark 3 on YARN** for data engineering."
> "**Iceberg** is an open table format — Parquet files on **S3** plus a snapshot/metadata layer, registered in the Hive Metastore, so Hive, Impala, and Spark can all query it."
> "And a small **Flask + Leaflet web app** ties it together: a map, the Iceberg table, this dashboard, and the storyboard."

## 1:30 – 3:30 · The storyboard — the anomaly, end to end
`[Open /story — advance with the Next button / arrow keys]`

> **Page 1 (Briefing):** "Meet track **trk‑013** in the South China Sea. Its AIS transponder declares it a **Tug**."
> **Page 2 (The track):** "Here are its six reported positions. The legs are long and evenly spaced."
> **Page 3 (The abnormal pattern):** "If those are hourly pings, each leg implies about **39 knots** — but a tug tops out near **13 knots**. That's **3× faster than physically possible**. Every bar sits far past the red limit line."
> **Page 4 (Visual mode — ranked):** "Scoring the whole fleet by an **impossibility ratio** — observed speed over the plausible max for its declared type — **trk‑013 is #1 of 16**. And the region already shows **12 spoofing links** and **32 anomaly points**."
> **Page 5 (Iceberg — visual mode):** "This same record lives in the **Iceberg** table `geo.geo_entity` — 476 features across 16 layers, on S3, with a snapshot ID — queried by Spark, no new servers added."
> **Page 6 (Verdict + lineage):** "Verdict: **Impossible Speed**, consistent with **AIS spoofing**. And the lineage: one **GeoJSON** feed → **COD/HBase** and **Iceberg/S3** → **map, table, and storyboard**."

## 3:30 – 4:30 · The payoff — one dataset, two query paths
`[Open /table — the Iceberg Table page]`
> "The web app reads the **analytical** copy from Iceberg — same 476 rows, with the snapshot and S3 location shown."

`[Open the two Hue tabs, or just describe]`
> "In **Hue** I can query the exact same data two ways: **Phoenix over HBase** on COD for operational lookups —"
```sql
SELECT layer, COUNT(*) FROM geo_entity GROUP BY layer;        -- COD Hue (Phoenix → HBase)
```
> "— and **Hive or Impala over Iceberg** on the Data Hub for analytics —"
```sql
SELECT layer, COUNT(*) FROM geo.geo_entity GROUP BY layer;    -- Data Hub Hue (Hive/Impala → Iceberg)
```
> "Identical results, two engines, one governed dataset."

## 4:30 – 5:00 · Close
> "So: **one dataset**, governed once by **SDX**, served **operationally** by COD/HBase/Phoenix and **analytically** by Iceberg, **visualized** on a map, and **explained** through a storyboard that catches a spoofed vessel — and the whole platform is **one‑click deployable**. Questions?"

---

## Cheat sheet — "what does this service do?" (for Q&A)
| Service | One‑line role |
| --- | --- |
| **FreeIPA** (Environment) | Kerberos identity, LDAP, DNS for the whole environment |
| **SDX Data Lake** | Shared security + governance layer for every engine |
| **Ranger** | Centralized authorization policies + audit |
| **Atlas** | Metadata catalog + data lineage |
| **Hive Metastore (HMS)** | Shared table definitions used by Hive/Impala/Spark |
| **IDBroker** | Maps CDP users → AWS IAM roles for S3 access |
| **COD (HBase)** | Operational NoSQL store — fast key/rowkey access |
| **Phoenix** | SQL layer over HBase (JDBC/thin, used by COD Hue) |
| **Data Hub (Spark 3 on YARN)** | Compute — the Iceberg ingest + jobs run here |
| **Iceberg** | Open table format (Parquet + snapshots on S3) in HMS |
| **S3** | Object storage for the data lake, Iceberg, and audit/logs |
| **Hue** | Web SQL editor — Phoenix on COD, Hive/Impala on Data Hub |
| **GeoServer** (optional, local) | OGC WMS/WFS map layers from the same GeoJSON |
| **Web app** | Entity Map, Iceberg Table, Dashboard, Storyboard |

## Key numbers to drop
- **476** features / **16** layers, loaded into **both** HBase and Iceberg.
- **trk‑013**: Tug at **~39 kn** vs **~13 kn** max → **3.0×** over limit, **#1 of 16**.
- Regional context: **12** spoofing links, **32** anomaly points.
- Iceberg: partitioned by `layer`, format‑v2, on S3 under the SDX warehouse.
