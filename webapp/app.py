"""
Entity Map — a small Flask web app for the cdp-one-click geospatial workflow.

It renders the initial GeoJSON datasets found in the "entity" directory on an
interactive map, and provides a button that publishes those datasets as a
GeoServer map layer (backed by the GeoMesa/COD HBase store) via GeoServer's
REST API.

Configuration (all optional; sensible defaults for local demos):

  ENTITY_DIR            Directory of GeoJSON datasets to display.
                        Default: ./sample-data/entity (bundled sample data).
                        Point this at your real data, e.g.
                        /path/to/geomesa-hbase-geojson-demo/data/entity

  GEOSERVER_URL         Base GeoServer URL, e.g. https://host/geoserver
  GEOSERVER_USER        GeoServer admin user (default: admin)
  GEOSERVER_PASSWORD    GeoServer admin password (default: geoserver)
  GEOSERVER_WORKSPACE   Workspace to create/use (default: geomesa)
  GEOSERVER_DATASTORE   Datastore name to create/use (default: geomesa_hbase)

  GEOMESA_CATALOG       GeoMesa HBase catalog table (default: <workspace>)
  GEOMESA_ZOOKEEPERS    HBase ZooKeeper quorum for the COD cluster

The GeoServer button degrades gracefully: if GEOSERVER_URL is not set it returns
a clear, actionable message instead of failing.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_ENTITY_DIR = BASE_DIR / "sample-data" / "entity"

app = Flask(__name__, static_folder="static", template_folder="templates")


def entity_dir() -> Path:
    return Path(os.environ.get("ENTITY_DIR", str(DEFAULT_ENTITY_DIR))).expanduser()


def geoserver_config() -> dict:
    url = os.environ.get("GEOSERVER_URL", "").rstrip("/")
    workspace = os.environ.get("GEOSERVER_WORKSPACE", "geomesa")
    return {
        "url": url,
        "user": os.environ.get("GEOSERVER_USER", "admin"),
        "password": os.environ.get("GEOSERVER_PASSWORD", "geoserver"),
        "workspace": workspace,
        "datastore": os.environ.get("GEOSERVER_DATASTORE", "geomesa_hbase"),
        "catalog": os.environ.get("GEOMESA_CATALOG", workspace),
        "zookeepers": os.environ.get("GEOMESA_ZOOKEEPERS", ""),
        "configured": bool(url),
    }


def _list_geojson_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    files: list[Path] = []
    for pattern in ("*.geojson", "*.json"):
        files.extend(sorted(directory.glob(pattern)))
    return files


def _load_featurecollection(path: Path) -> dict | None:
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("type") == "FeatureCollection":
        return data
    if data.get("type") == "Feature":
        return {"type": "FeatureCollection", "features": [data]}
    return None


@app.get("/")
def index():
    return send_from_directory(app.template_folder, "index.html")


@app.get("/api/config")
def api_config():
    gs = geoserver_config()
    return jsonify(
        {
            "entityDir": str(entity_dir()),
            "geoserverConfigured": gs["configured"],
            "geoserverWorkspace": gs["workspace"],
        }
    )


@app.get("/api/datasets")
def api_datasets():
    directory = entity_dir()
    datasets = []
    for path in _list_geojson_files(directory):
        fc = _load_featurecollection(path)
        if fc is None:
            continue
        datasets.append(
            {
                "name": path.stem,
                "file": path.name,
                "featureCount": len(fc.get("features", [])),
            }
        )
    return jsonify({"entityDir": str(directory), "datasets": datasets})


@app.get("/api/datasets/<name>")
def api_dataset(name: str):
    directory = entity_dir()
    for path in _list_geojson_files(directory):
        if path.stem == name:
            fc = _load_featurecollection(path)
            if fc is None:
                return jsonify({"error": f"'{path.name}' is not valid GeoJSON"}), 422
            return jsonify(fc)
    return jsonify({"error": f"dataset '{name}' not found"}), 404


def _gs_request(method: str, url: str, gs: dict, **kwargs) -> requests.Response:
    return requests.request(
        method,
        url,
        auth=(gs["user"], gs["password"]),
        timeout=30,
        **kwargs,
    )


def _ensure_workspace(gs: dict, log: list[str]) -> None:
    url = f"{gs['url']}/rest/workspaces"
    resp = _gs_request(
        "POST", url, gs,
        headers={"Content-Type": "application/json"},
        data=json.dumps({"workspace": {"name": gs["workspace"]}}),
    )
    if resp.status_code in (200, 201):
        log.append(f"created workspace '{gs['workspace']}'")
    elif resp.status_code in (401, 403):
        raise PermissionError("GeoServer rejected the credentials (check GEOSERVER_USER/PASSWORD)")
    elif resp.status_code == 409 or "already exists" in resp.text.lower():
        log.append(f"workspace '{gs['workspace']}' already exists")
    else:
        raise RuntimeError(f"workspace create failed ({resp.status_code}): {resp.text[:200]}")


def _ensure_datastore(gs: dict, log: list[str]) -> None:
    url = f"{gs['url']}/rest/workspaces/{gs['workspace']}/datastores"
    payload = {
        "dataStore": {
            "name": gs["datastore"],
            "type": "HBase (GeoMesa)",
            "connectionParameters": {
                "entry": [
                    {"@key": "hbase.catalog", "$": gs["catalog"]},
                    {"@key": "hbase.zookeepers", "$": gs["zookeepers"]},
                ]
            },
        }
    }
    resp = _gs_request(
        "POST", url, gs,
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload),
    )
    if resp.status_code in (200, 201):
        log.append(f"created datastore '{gs['datastore']}' (GeoMesa HBase, catalog '{gs['catalog']}')")
    elif resp.status_code == 409 or "already exists" in resp.text.lower():
        log.append(f"datastore '{gs['datastore']}' already exists")
    else:
        raise RuntimeError(f"datastore create failed ({resp.status_code}): {resp.text[:200]}")


def _publish_featuretype(gs: dict, layer: str, log: list[str]) -> None:
    url = f"{gs['url']}/rest/workspaces/{gs['workspace']}/datastores/{gs['datastore']}/featuretypes"
    resp = _gs_request(
        "POST", url, gs,
        headers={"Content-Type": "application/json"},
        data=json.dumps({"featureType": {"name": layer}}),
    )
    if resp.status_code in (200, 201):
        log.append(f"published layer '{gs['workspace']}:{layer}'")
    elif resp.status_code == 409 or "already exists" in resp.text.lower():
        log.append(f"layer '{gs['workspace']}:{layer}' already exists")
    else:
        raise RuntimeError(f"featuretype publish failed ({resp.status_code}): {resp.text[:200]}")


@app.post("/api/geoserver/layer")
def api_create_layer():
    gs = geoserver_config()
    body = request.get_json(silent=True) or {}
    layer = body.get("layer", "entity")

    if not gs["configured"]:
        return (
            jsonify(
                {
                    "ok": False,
                    "message": (
                        "GeoServer is not configured. Set GEOSERVER_URL (and "
                        "GEOMESA_ZOOKEEPERS for the COD HBase store) to enable "
                        "layer publishing."
                    ),
                }
            ),
            400,
        )

    log: list[str] = []
    try:
        _ensure_workspace(gs, log)
        _ensure_datastore(gs, log)
        _publish_featuretype(gs, layer, log)
    except PermissionError as exc:
        return jsonify({"ok": False, "message": str(exc), "log": log}), 502
    except requests.RequestException as exc:
        return jsonify({"ok": False, "message": f"could not reach GeoServer: {exc}", "log": log}), 502
    except RuntimeError as exc:
        return jsonify({"ok": False, "message": str(exc), "log": log}), 502

    qualified = f"{gs['workspace']}:{layer}"
    wms_url = (
        f"{gs['url']}/{gs['workspace']}/wms?service=WMS&version=1.1.0&request=GetMap"
        f"&layers={qualified}&styles=&format=image/png&transparent=true"
        f"&srs=EPSG:4326&width=768&height=576&bbox=-180,-90,180,90"
    )
    return jsonify(
        {
            "ok": True,
            "message": f"GeoServer layer '{qualified}' is ready.",
            "layer": qualified,
            "wmsBaseUrl": f"{gs['url']}/{gs['workspace']}/wms",
            "wmsExampleUrl": wms_url,
            "log": log,
        }
    )


@app.get("/static/<path:filename>")
def static_files(filename: str):
    return send_from_directory(app.static_folder, filename)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8888"))
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=port, debug=True)
