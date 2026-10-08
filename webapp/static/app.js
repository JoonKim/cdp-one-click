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
const ALERT = []; // {lyr, color, isPoint} for features matching an alert rule

// Predefined regions for the "Zoom to region" control: [[S,W],[N,E]].
const REGIONS = {
  sf: L.latLngBounds([[37.70, -122.52], [37.83, -122.35]]),
  hormuz: L.latLngBounds([[25.0, 55.9], [27.3, 57.1]]),
  scs: L.latLngBounds([[1.0, 103.5], [22.5, 121.5]]),
};

// An "alert" feature: sensor alert/warning, high-severity or open incident.
function isAlert(p) {
  if (!p) return false;
  const status = String(p.status || "").toLowerCase();
  const severity = String(p.severity || "").toLowerCase();
  // alert_type flags spoofing/zombie (AIS identity theft) anomalies.
  return Boolean(p.alert_type) || status === "alert" || status === "warning" ||
    severity === "high" || p.open === true;
}

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
    onEachFeature: (feature, lyr) => {
      lyr.bindPopup(popupHtml(feature));
      if (isAlert(feature.properties)) {
        ALERT.push({ lyr, color, isPoint: feature.geometry.type === "Point" });
      }
    },
  }).addTo(map);
  const badge = document.getElementById("alert-count");
  if (badge) badge.textContent = String(ALERT.length);

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

// ---- Region zoom control ----
document.getElementById("region-select").addEventListener("change", (e) => {
  const v = e.target.value;
  if (v === "all") {
    if (allBounds.isValid()) map.fitBounds(allBounds.pad(0.1));
  } else if (REGIONS[v]) {
    map.fitBounds(REGIONS[v].pad(0.05));
  }
});

// ---- Alert highlighting ----
let alertsOn = false;
function setAlert(on) {
  ALERT.forEach(({ lyr, color, isPoint }) => {
    if (on) {
      lyr.setStyle({ color: "#ef4444", weight: 3, fillColor: "#ef4444", fillOpacity: isPoint ? 0.9 : 0.4 });
      if (isPoint && lyr.setRadius) lyr.setRadius(11);
      if (lyr.bringToFront) lyr.bringToFront();
    } else if (isPoint) {
      lyr.setStyle({ color, weight: 2, fillColor: color, fillOpacity: 0.85 });
      if (lyr.setRadius) lyr.setRadius(7);
    } else {
      lyr.setStyle(styleFor(color));
    }
  });
}
document.getElementById("toggle-alerts").addEventListener("click", () => {
  alertsOn = !alertsOn;
  setAlert(alertsOn);
  const btn = document.getElementById("toggle-alerts");
  btn.setAttribute("aria-pressed", String(alertsOn));
  btn.classList.toggle("active", alertsOn);
  if (alertsOn && ALERT.length) {
    const grp = L.featureGroup(ALERT.map((a) => a.lyr));
    const b = grp.getBounds();
    if (b.isValid()) map.fitBounds(b.pad(0.25));
    toast(`${ALERT.length} alert feature(s) highlighted`, "err");
  }
});

// ---- Deep links: /?region=hormuz&alerts=1 ----
function applyUrlParams() {
  const q = new URLSearchParams(location.search);
  const region = q.get("region");
  if (region) {
    const sel = document.getElementById("region-select");
    sel.value = region;
    sel.dispatchEvent(new Event("change"));
  }
  if (q.get("alerts") === "1") document.getElementById("toggle-alerts").click();
}

init().then(applyUrlParams);
