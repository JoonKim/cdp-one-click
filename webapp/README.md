# Entity Map web app

A small Flask + Leaflet web app that renders the initial GeoJSON datasets from
the **`entity`** directory on a map, with a button to publish them as a
**GeoServer** map layer (backed by the GeoMesa/COD HBase store).

## Run

```bash
cd webapp
pip3 install -r requirements.txt
python3 app.py
# open http://127.0.0.1:8888
```

By default it serves the bundled sample datasets in `sample-data/entity/`. Point
it at your real data with `ENTITY_DIR`:

```bash
ENTITY_DIR=/path/to/geomesa-hbase-geojson-demo/data/entity python3 app.py
```

## GeoServer layer button

The **Create GeoServer Layer** button calls GeoServer's REST API to (idempotently)
create the workspace, a GeoMesa HBase datastore pointing at your COD catalog, and
publish the `entity` feature type. Configure it with environment variables:

| Variable | Purpose | Default |
| --- | --- | --- |
| `GEOSERVER_URL` | Base GeoServer URL, e.g. `https://host/geoserver` | _(required to publish)_ |
| `GEOSERVER_USER` / `GEOSERVER_PASSWORD` | GeoServer admin credentials | `admin` / `geoserver` |
| `GEOSERVER_WORKSPACE` | Workspace to create/use | `geomesa` |
| `GEOSERVER_DATASTORE` | Datastore name to create/use | `geomesa_hbase` |
| `GEOMESA_CATALOG` | GeoMesa HBase catalog table (from the ingest step) | `<workspace>` |
| `GEOMESA_ZOOKEEPERS` | COD HBase ZooKeeper quorum | _(empty)_ |

If `GEOSERVER_URL` is unset the button returns a clear "not configured" message
instead of failing, so the map still works for exploring the datasets.

## API

| Endpoint | Description |
| --- | --- |
| `GET /api/config` | entity dir + GeoServer status |
| `GET /api/datasets` | list datasets (name, file, feature count) |
| `GET /api/datasets/<name>` | a dataset's GeoJSON FeatureCollection |
| `POST /api/geoserver/layer` | create/publish the GeoServer layer |

## How it fits the CDP geospatial flow

1. Provision env + COD: `cdp_create_all_the_things.sh parameters_sample/parameters_aws_geospatial.json`
2. Ingest GeoJSON into COD/HBase: `demo-scripts/ingest_geojson_geomesa.sh ...`
3. Explore + publish with this app (`ENTITY_DIR` for the map, GeoServer env vars for the layer).
