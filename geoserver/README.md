# Local GeoServer for the entity demo

Stands up a local **GeoServer** (Docker) and auto-publishes the `entity` GeoJSON
as direct **WMS/WFS** layers — fully offline, with no CDP/COD dependency. This is
the reliable visual path (GeoServer → COD/GeoMesa HBase is blocked by CDP's
TLS-secured ZooKeeper).

## Prerequisites
- Docker + Docker Compose (the same Docker you already use locally).
- No GDAL needed on the host — if `ogr2ogr` isn't installed, the script converts
  via a GDAL container automatically.

## Run

```bash
cd geoserver
./publish_entity.sh
# or point at your own data:
# ENTITY_DIR=/path/to/geomesa-hbase-geojson-demo/data/entity ./publish_entity.sh
```

Then open:
- GeoServer UI: http://localhost:8080/geoserver  (admin / geoserver)
- **Layer Preview** → `entity:stations`, `entity:zones`, `entity:routes` (OpenLayers / WMS)

Each layer is also a WMS endpoint, e.g.:
```
http://localhost:8080/geoserver/entity/wms?service=WMS&version=1.1.0&request=GetMap&layers=entity:stations&bbox=-180,-90,180,90&width=768&height=384&srs=EPSG:4326&format=application/openlayers
```

## Hook it into the dashboard / map
Set this in `webapp/.env` so the Services Dashboard shows GeoServer as reachable:
```
GEOSERVER_URL=http://localhost:8080/geoserver
GEOSERVER_USER=admin
GEOSERVER_PASSWORD=geoserver
```

## Teardown
```bash
docker compose down
```

The generated `data/` shapefiles are git-ignored.
