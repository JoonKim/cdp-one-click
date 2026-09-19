/* Entity Map — loads GeoJSON datasets from the entity directory and renders them
 * on a Leaflet map, with a button to publish them as a GeoServer layer. */

const PALETTE = ["#38bdf8", "#f97316", "#a78bfa", "#22c55e", "#f43f5e", "#eab308"];

const map = L.map("map", { zoomControl: true }).setView([37.7793, -122.4098], 13);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

const layers = {}; // name -> { layer, color }
const allBounds = L.latLngBounds([]);

function log(message, kind) {
  const el = document.getElementById("log");
  const li = document.createElement("li");
  if (kind) li.className = kind;
  const time = new Date().toLocaleTimeString();
  li.textContent = `${time}  ${message}`;
  el.prepend(li);
}

function toast(message, kind) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.className = `toast ${kind || ""}`;
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.hidden = true; }, 6000);
}

function popupHtml(feature) {
  const props = feature.properties || {};
  const rows = Object.keys(props)
    .map((k) => `<div><b>${k}</b>: ${props[k]}</div>`)
    .join("");
  return rows || "<i>no properties</i>";
}

function styleFor(color) {
  return {
    color,
    weight: 2,
    fillColor: color,
    fillOpacity: 0.25,
  };
}

async function loadDataset(name, color) {
  const resp = await fetch(`/api/datasets/${encodeURIComponent(name)}`);
  if (!resp.ok) {
    log(`failed to load '${name}'`, "err");
    return;
  }
  const geojson = await resp.json();
  const layer = L.geoJSON(geojson, {
    style: () => styleFor(color),
    pointToLayer: (_f, latlng) =>
      L.circleMarker(latlng, { radius: 7, ...styleFor(color), fillOpacity: 0.85 }),
    onEachFeature: (feature, lyr) => lyr.bindPopup(popupHtml(feature)),
  }).addTo(map);

  layers[name] = { layer, color };
  const b = layer.getBounds();
  if (b.isValid()) {
    allBounds.extend(b);
    map.fitBounds(allBounds.pad(0.15));
  }
}

function addDatasetItem(ds, color) {
  const list = document.getElementById("dataset-list");
  const li = document.createElement("li");
  li.className = "dataset-item";
  li.innerHTML = `
    <input type="checkbox" checked data-name="${ds.name}" />
    <span class="swatch" style="background:${color}"></span>
    <span class="dataset-meta">
      <span class="dataset-name">${ds.name}</span>
      <span class="dataset-count">${ds.featureCount} feature${ds.featureCount === 1 ? "" : "s"}</span>
    </span>`;
  li.querySelector("input").addEventListener("change", (e) => {
    const entry = layers[ds.name];
    if (!entry) return;
    if (e.target.checked) entry.layer.addTo(map);
    else map.removeLayer(entry.layer);
  });
  list.appendChild(li);
}

async function init() {
  document.getElementById("create-layer").disabled = false;
  // Config / GeoServer status.
  try {
    const cfg = await (await fetch("/api/config")).json();
    document.getElementById("entity-dir").textContent = cfg.entityDir;
    const badge = document.getElementById("gs-badge");
    if (cfg.geoserverConfigured) {
      badge.textContent = `GeoServer: ${cfg.geoserverWorkspace}`;
      badge.className = "badge badge-ok";
    } else {
      badge.textContent = "GeoServer: not configured";
      badge.className = "badge badge-off";
    }
  } catch (e) {
    log("could not read config", "err");
  }

  // Datasets.
  const list = document.getElementById("dataset-list");
  list.innerHTML = "";
  let data;
  try {
    data = await (await fetch("/api/datasets")).json();
  } catch (e) {
    list.innerHTML = '<li class="empty">Failed to load datasets.</li>';
    return;
  }
  if (!data.datasets.length) {
    list.innerHTML = '<li class="empty">No GeoJSON datasets found in the entity directory.</li>';
    return;
  }
  for (let i = 0; i < data.datasets.length; i++) {
    const ds = data.datasets[i];
    const color = PALETTE[i % PALETTE.length];
    addDatasetItem(ds, color);
    await loadDataset(ds.name, color);
    log(`loaded '${ds.name}' (${ds.featureCount} features)`);
  }
}

document.getElementById("create-layer").addEventListener("click", async () => {
  const btn = document.getElementById("create-layer");
  const label = btn.querySelector(".btn-label");
  const spinner = btn.querySelector(".spinner");
  btn.disabled = true;
  spinner.hidden = false;
  label.textContent = "Publishing…";
  try {
    const resp = await fetch("/api/geoserver/layer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ layer: "entity" }),
    });
    const result = await resp.json();
    (result.log || []).forEach((line) => log(line, result.ok ? "ok" : undefined));
    if (result.ok) {
      toast(result.message, "ok");
      log(`WMS: ${result.wmsBaseUrl}`, "ok");
    } else {
      toast(result.message, "err");
      log(result.message, "err");
    }
  } catch (e) {
    toast(`Request failed: ${e}`, "err");
    log(`request failed: ${e}`, "err");
  } finally {
    spinner.hidden = true;
    label.textContent = "Create GeoServer Layer";
    btn.disabled = false;
  }
});

init();
