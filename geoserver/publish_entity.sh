#!/usr/bin/env bash
#
# Stand up a local GeoServer (Docker) and auto-publish the entity GeoJSON as
# direct WMS/WFS layers -- fully offline, no CDP/COD dependency.
#
# What it does:
#   1. Converts each entity GeoJSON into a Shapefile (ogr2ogr; uses a GDAL
#      container if ogr2ogr isn't installed on the host).
#   2. Starts GeoServer via docker compose.
#   3. Creates a workspace + a "directory of shapefiles" datastore and publishes
#      one layer per dataset (EPSG:4326).
#
# Usage:
#   ./publish_entity.sh                 # uses ../webapp/sample-data/entity
#   ENTITY_DIR=/path/to/data/entity ./publish_entity.sh
#
# Then open:  http://localhost:8080/geoserver  (admin / geoserver)
# Teardown:   docker compose down
set -euo pipefail

cd "$(dirname "$0")"

GS="http://localhost:8080/geoserver"
GS_USER="${GEOSERVER_USER:-admin}"
GS_PASS="${GEOSERVER_PASSWORD:-geoserver}"
WS="${GEOSERVER_WORKSPACE:-entity}"
STORE="${GEOSERVER_DATASTORE:-entity_dir}"
ENTITY_DIR="${ENTITY_DIR:-../webapp/sample-data/entity}"

ENTITY_ABS="$(cd "$ENTITY_DIR" && pwd)"
mkdir -p data

echo "==> Converting GeoJSON -> Shapefile (from $ENTITY_ABS)"
shopt -s nullglob
sources=("$ENTITY_ABS"/*.geojson "$ENTITY_ABS"/*.json)
if [ ${#sources[@]} -eq 0 ]; then
  echo "No GeoJSON files found in $ENTITY_ABS" >&2
  exit 1
fi
for f in "${sources[@]}"; do
  name="$(basename "${f%.*}")"
  if command -v ogr2ogr >/dev/null 2>&1; then
    ogr2ogr -f "ESRI Shapefile" "data/${name}.shp" "$f" -t_srs EPSG:4326 -overwrite
  else
    docker run --rm \
      -v "$PWD/data":/out \
      -v "$ENTITY_ABS":/in:ro \
      ghcr.io/osgeo/gdal:alpine-small-latest \
      ogr2ogr -f "ESRI Shapefile" "/out/${name}.shp" "/in/$(basename "$f")" -t_srs EPSG:4326 -overwrite
  fi
  echo "   - ${name}.shp"
done

echo "==> Starting GeoServer (docker compose up -d)"
if docker compose version >/dev/null 2>&1; then DC="docker compose"; else DC="docker-compose"; fi
$DC up -d

echo "==> Waiting for GeoServer REST API..."
for _ in $(seq 1 60); do
  if curl -sf -o /dev/null -u "$GS_USER:$GS_PASS" "$GS/rest/about/version"; then break; fi
  sleep 3
done

api() { curl -s -u "$GS_USER:$GS_PASS" -H "Content-Type: application/json" "$@"; }

echo "==> Creating workspace '$WS'"
api -XPOST "$GS/rest/workspaces" -d "{\"workspace\":{\"name\":\"$WS\"}}" >/dev/null || true

echo "==> Creating shapefile-directory datastore '$STORE'"
api -XPOST "$GS/rest/workspaces/$WS/datastores" -d "{
  \"dataStore\": {
    \"name\": \"$STORE\",
    \"type\": \"Directory of spatial files (shapefiles)\",
    \"connectionParameters\": { \"entry\": [
      { \"@key\": \"url\", \"\$\": \"file:/opt/entity_data\" },
      { \"@key\": \"charset\", \"\$\": \"UTF-8\" }
    ]}
  }
}" >/dev/null || true

echo "==> Publishing layers"
for shp in data/*.shp; do
  name="$(basename "${shp%.shp}")"
  api -XPOST "$GS/rest/workspaces/$WS/datastores/$STORE/featuretypes" -d "{
    \"featureType\": { \"name\": \"$name\", \"nativeName\": \"$name\", \"srs\": \"EPSG:4326\" }
  }" >/dev/null || true
  echo "   - $WS:$name  ->  $GS/$WS/wms?service=WMS&version=1.1.0&request=GetMap&layers=$WS:$name&bbox=-180,-90,180,90&width=768&height=384&srs=EPSG:4326&format=application/openlayers"
done

echo ""
echo "Done. GeoServer UI:  $GS/web/   (user: $GS_USER)"
echo "Layer preview:       $GS/web/wicket/bookmarkable/org.geoserver.web.demo.MapPreviewPage"
echo "Point the web app at it:  GEOSERVER_URL=$GS  in webapp/.env"
