/* Anomaly storyboard for trk-013.
 *
 * A multi-page narrative that walks through an abnormal AIS movement pattern:
 * it pulls the same datasets shown on the Entity Map and in the Iceberg Table,
 * derives the anomaly (a Tug sustaining an impossible speed), and presents it
 * on a map and as "visual mode" charts of the Iceberg geo_entity data.
 */

const KM2KN = 0.539957;
const SUBJECT_ID = "trk-013";

// Plausible sustained max speed (knots) by declared AIS vessel type.
const TYPEMAX = {
  Tug: 13, Fishing: 15, "Offshore Supply": 14, Naval: 32, "Bulk Carrier": 26,
  "Crude Oil Tanker": 17, "Product Tanker": 18, "LNG Carrier": 21,
  "LPG Carrier": 19, "General Cargo": 22, "Container Ship": 26,
};
const DEFAULT_TYPEMAX = 25;

function haversine(a, b) {
  const R = 6371.0;
  const [lon1, lat1] = a, [lon2, lat2] = b;
  const p1 = (lat1 * Math.PI) / 180, p2 = (lat2 * Math.PI) / 180;
  const dphi = ((lat2 - lat1) * Math.PI) / 180;
  const dl = ((lon2 - lon1) * Math.PI) / 180;
  const x = Math.sin(dphi / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
}

function trackStats(feature) {
  const co = feature.geometry.coordinates;
  const segs = [];
  for (let i = 1; i < co.length; i++) {
    const km = haversine(co[i - 1], co[i]);
    segs.push({ i, km, kn: km * KM2KN, from: co[i - 1], to: co[i] });
  }
  const speeds = segs.map((s) => s.kn);
  const avg = speeds.reduce((a, b) => a + b, 0) / (speeds.length || 1);
  const type = feature.properties.vessel_type || feature.properties.type || "Unknown";
  const typemax = TYPEMAX[type] || DEFAULT_TYPEMAX;
  return {
    id: feature.properties.id,
    name: feature.properties.name,
    type, typemax, coords: co, segs,
    avg, max: Math.max(...speeds), ratio: avg / typemax,
  };
}

const EL = (id) => document.getElementById(id);

/* ---------- small HTML bar chart ---------- */
function barChart(items, opts = {}) {
  const max = opts.max || Math.max(...items.map((i) => i.value)) * 1.05;
  const unit = opts.unit || "";
  let thr = "";
  if (opts.threshold != null) {
    const pct = Math.min(100, (opts.threshold / max) * 100);
    thr = `<div class="vbar-threshold" style="left:calc(${pct}% )">
             <span>${opts.thresholdLabel || opts.threshold + unit}</span></div>`;
  }
  const rows = items
    .map((it) => {
      const pct = Math.max(1.5, Math.min(100, (it.value / max) * 100));
      const cls = it.highlight ? "vbar-fill hi" : "vbar-fill";
      const color = it.color ? `background:${it.color};` : "";
      return `<div class="vbar-row${it.highlight ? " row-hi" : ""}">
        <div class="vbar-label" title="${it.label}">${it.label}</div>
        <div class="vbar-track"><div class="${cls}" style="width:${pct}%;${color}"></div></div>
        <div class="vbar-val">${it.valueLabel ?? it.value.toFixed(1) + unit}</div>
      </div>`;
    })
    .join("");
  return `<div class="vbar-chart">${thr}${rows}</div>`;
}

/* ---------- map helpers ---------- */
let map, overlay;
function ensureMap() {
  if (map) return;
  map = L.map("map", { zoomControl: true, attributionControl: true }).setView([13, 113], 6);
  // Esri World Imagery: key-free and renders in screenshots (OSM tile servers
  // block non-interactive requests).
  L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 19, attribution: "Tiles &copy; Esri, Maxar, Earthstar Geographics" }
  ).addTo(map);
  L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 19, opacity: 0.9 }
  ).addTo(map);
  overlay = L.layerGroup().addTo(map);
}
function clearOverlay() { if (overlay) overlay.clearLayers(); }
function toLatLngs(coords) { return coords.map((c) => [c[1], c[0]]); }

function drawContextTracks(S) {
  S.allTracks.forEach((t) => {
    if (t.id === SUBJECT_ID) return;
    L.polyline(toLatLngs(t.coords), { color: "#475569", weight: 1.5, opacity: 0.5 }).addTo(overlay);
  });
}
function drawSubject(S, withLabels) {
  const t = S.subject;
  L.polyline(toLatLngs(t.coords), { color: "#38bdf8", weight: 4, opacity: 0.95 }).addTo(overlay);
  t.coords.forEach((c, idx) => {
    L.marker([c[1], c[0]], {
      icon: L.divIcon({ className: "pt-icon", html: `<span>${idx}</span>`, iconSize: [22, 22] }),
    }).addTo(overlay);
  });
  if (withLabels) {
    t.segs.forEach((s) => {
      const mid = [(s.from[1] + s.to[1]) / 2, (s.from[0] + s.to[0]) / 2];
      L.marker(mid, {
        icon: L.divIcon({
          className: "seg-icon",
          html: `<span>${s.km.toFixed(0)} km · ${s.kn.toFixed(0)} kn</span>`,
          iconSize: [92, 18],
        }),
      }).addTo(overlay);
    });
  }
}
function fitTo(coords) {
  const b = L.latLngBounds(toLatLngs(coords));
  map.fitBounds(b.pad(0.4));
}

function showMap() {
  EL("visual").hidden = true;
  EL("map").style.display = "block";
  ensureMap();
  setTimeout(() => map.invalidateSize(), 50);
}
function showVisual(html) {
  EL("map").style.display = "none";
  const v = EL("visual");
  v.hidden = false;
  v.innerHTML = html;
}

/* ---------- slides ---------- */
const slides = [
  {
    title: "Briefing: a vessel that moves too fast",
    body: (S) => `
      <p>An analyst flags AIS track <b>${SUBJECT_ID}</b> in the <b>South China Sea</b>.
      It is one of <b>${S.allTracks.length}</b> tracks in the feed, stored in both the
      operational store (COD/HBase) and the analytical table (Iceberg).</p>
      <div class="story-card">
        <div class="kv"><span>ID</span><b>${S.subject.id}</b></div>
        <div class="kv"><span>Name</span><b>${S.subject.name}</b></div>
        <div class="kv"><span>Declared type</span><b>${S.subject.type}</b></div>
        <div class="kv"><span>AIS points</span><b>${S.subject.coords.length}</b></div>
      </div>
      <p class="muted small">Question: does ${SUBJECT_ID}'s movement match what its declared
      vessel type can physically do?</p>`,
    enter: (S) => { showMap(); clearOverlay(); drawContextTracks(S); fitTo([].concat(...S.allTracks.map((t) => t.coords))); },
  },
  {
    title: "The subject track",
    body: (S) => `
      <p>${SUBJECT_ID} reports <b>${S.subject.coords.length}</b> positions (numbered 0–${S.subject.coords.length - 1}).
      The legs are long and evenly spaced — consistent with a fast transit, not a harbour tug.</p>
      <table class="mini-table"><thead><tr><th>#</th><th>lon</th><th>lat</th></tr></thead><tbody>
      ${S.subject.coords.map((c, i) => `<tr><td>${i}</td><td>${c[0].toFixed(4)}</td><td>${c[1].toFixed(4)}</td></tr>`).join("")}
      </tbody></table>`,
    enter: (S) => { showMap(); clearOverlay(); drawContextTracks(S); drawSubject(S, false); fitTo(S.subject.coords); },
  },
  {
    title: "The abnormal pattern: impossible speed",
    body: (S) => {
      const t = S.subject;
      return `
      <p>Assuming hourly AIS pings, each leg implies ~<b>${t.avg.toFixed(0)} knots</b>
      (peak <b>${t.max.toFixed(0)} kn</b>). A <b>${t.type}</b> realistically tops out near
      <b>${t.typemax} kn</b>.</p>
      <div class="verdict bad">Observed ≈ ${t.avg.toFixed(0)} kn vs ${t.type} max ≈ ${t.typemax} kn
        → <b>${t.ratio.toFixed(1)}× over</b> the physical limit.</div>
      ${barChart(
        t.segs.map((s) => ({ label: `leg ${s.i - 1}→${s.i}`, value: s.kn, highlight: true, valueLabel: s.kn.toFixed(0) + " kn" })),
        { max: Math.max(t.max, t.typemax) * 1.15, unit: " kn", threshold: t.typemax, thresholdLabel: `${t.type} max ${t.typemax} kn` }
      )}
      <p class="muted small">Every leg sits far right of the red limit — a sustained impossibility,
      the signature of position/identity spoofing.</p>`;
    },
    enter: (S) => { showMap(); clearOverlay(); drawSubject(S, true); fitTo(S.subject.coords); },
  },
  {
    title: "Visual mode — ranked against the fleet",
    body: (S) => `
      <p>Scoring every South China Sea track by <b>impossibility ratio</b>
      (observed speed ÷ plausible max for its declared type) puts <b>${SUBJECT_ID}</b> at
      <b>#${S.rank}</b> of ${S.allTracks.length}.</p>
      <p class="muted small">Regional context from the same Iceberg table:
      <b>${S.spoofCount}</b> spoofing links and <b>${S.anomalyCount}</b> flagged anomaly points.</p>`,
    visual: (S) => `
      <div class="visual-head"><h3>Impossibility ratio by track</h3>
        <span class="muted small">observed avg speed ÷ plausible type max · 1.0× = physical limit</span></div>
      ${barChart(
        S.ranking.map((r) => ({
          label: `${r.id} · ${r.type}`,
          value: r.ratio,
          highlight: r.id === SUBJECT_ID,
          valueLabel: r.ratio.toFixed(2) + "×",
        })),
        { max: Math.max(...S.ranking.map((r) => r.ratio)) * 1.1, threshold: 1, thresholdLabel: "1.0× limit" }
      )}`,
    enter: (S, slide) => { showVisual(slide.visual(S)); },
  },
  {
    title: "The Iceberg table — visual mode",
    body: (S) => `
      <p>The same records live in the Iceberg table <code>${S.iceberg.table || "geo.geo_entity"}</code>
      (<b>${S.iceberg.rowCount || "?"}</b> rows / <b>${S.iceberg.perLayer ? Object.keys(S.iceberg.perLayer).length : "?"}</b> layers)
      on S3, queried via Spark3 — no new servers.</p>
      <div class="story-card">
        <div class="kv"><span>Format</span><b>${(S.iceberg.format || "iceberg").toUpperCase()}</b></div>
        <div class="kv"><span>Snapshot</span><b class="mono">${S.iceberg.snapshotId || "—"}</b></div>
        <div class="kv"><span>${SUBJECT_ID} row</span><b>${S.icebergRow ? `${S.icebergRow.layer} · ${S.icebergRow.name}` : "—"}</b></div>
      </div>
      <p class="muted small mono">${S.iceberg.location || ""}</p>`,
    visual: (S) => {
      const layers = S.iceberg.perLayer || {};
      const items = Object.keys(layers).sort((a, b) => layers[b] - layers[a]).map((k) => ({
        label: k, value: layers[k],
        highlight: k === "scs_vessel_tracks",
        valueLabel: String(layers[k]),
      }));
      return `<div class="visual-head"><h3>Iceberg <code>geo_entity</code> — features per layer</h3>
        <span class="muted small">${SUBJECT_ID} lives in the highlighted <b>scs_vessel_tracks</b> layer</span></div>
        ${barChart(items, { max: Math.max(...items.map((i) => i.value)) * 1.1 })}`;
    },
    enter: (S, slide) => { showVisual(slide.visual(S)); },
  },
  {
    title: "Verdict & data lineage",
    body: (S) => `
      <div class="verdict bad">Anomaly confirmed — <b>Impossible Speed</b> for declared type
        (<b>${S.subject.ratio.toFixed(1)}×</b> over limit). Consistent with AIS spoofing.</div>
      <ul class="story-list">
        <li><b>Detect</b>: speed-vs-type rule flags ${SUBJECT_ID} (#${S.rank}/${S.allTracks.length}).</li>
        <li><b>Corroborate</b>: ${S.spoofCount} spoof links + ${S.anomalyCount} anomaly points in the region.</li>
        <li><b>Act</b>: raise alert, cross-check identity/MMSI, task follow-up.</li>
      </ul>
      <div class="lineage">
        <span>GeoJSON feed</span><span class="arrow">→</span>
        <span>COD · HBase/Phoenix</span><span class="arrow">+</span>
        <span>Iceberg · Hive/S3</span><span class="arrow">→</span>
        <span>Map · Table · Storyboard</span>
      </div>`,
    enter: (S) => {
      showMap(); clearOverlay(); drawContextTracks(S); drawSubject(S, false);
      S.spoof.features.forEach((f) => {
        if (f.geometry.type === "LineString") {
          L.polyline(toLatLngs(f.geometry.coordinates), { color: "#ef4444", weight: 1.5, opacity: 0.6, dashArray: "5 5" }).addTo(overlay);
        }
      });
      fitTo(S.subject.coords);
    },
  },
];

/* ---------- controller ---------- */
let STATE = null;
let idx = 0;

function render() {
  const slide = slides[idx];
  EL("step-badge").textContent = `Page ${idx + 1} / ${slides.length}`;
  EL("story-title").textContent = slide.title;
  EL("story-body").innerHTML = slide.body(STATE);
  slide.enter(STATE, slide);
  EL("story-bar").style.width = `${((idx + 1) / slides.length) * 100}%`;
  EL("prev").disabled = idx === 0;
  EL("next").disabled = idx === slides.length - 1;
  document.querySelectorAll(".story-dots .dot").forEach((d, i) =>
    d.classList.toggle("active", i === idx));
}
function go(n) { idx = Math.max(0, Math.min(slides.length - 1, n)); render(); }

async function init() {
  const dots = EL("dots");
  slides.forEach((_, i) => {
    const d = document.createElement("span");
    d.className = "dot";
    d.addEventListener("click", () => go(i));
    dots.appendChild(d);
  });
  EL("prev").addEventListener("click", () => go(idx - 1));
  EL("next").addEventListener("click", () => go(idx + 1));
  document.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight") go(idx + 1);
    if (e.key === "ArrowLeft") go(idx - 1);
  });

  const fetchJSON = (u) => fetch(u).then((r) => r.json()).catch(() => ({ features: [] }));
  const [tracks, spoof, anomalies, iceberg] = await Promise.all([
    fetchJSON("/api/datasets/scs_vessel_tracks"),
    fetchJSON("/api/datasets/spoof_links"),
    fetchJSON("/api/datasets/vessel_anomalies"),
    fetchJSON("/api/iceberg"),
  ]);

  const allTracks = (tracks.features || []).map(trackStats);
  const subject = allTracks.find((t) => t.id === SUBJECT_ID) || allTracks[0];
  const ranking = [...allTracks].sort((a, b) => b.ratio - a.ratio);
  const rank = ranking.findIndex((t) => t.id === SUBJECT_ID) + 1;
  const icebergRow = (iceberg.rows || []).find(
    (r) => r.id === SUBJECT_ID && r.layer === "scs_vessel_tracks"
  );

  STATE = {
    allTracks, subject, ranking, rank,
    spoof, anomalies, iceberg, icebergRow,
    spoofCount: (spoof.features || []).length,
    anomalyCount: (anomalies.features || []).length,
  };
  const start = parseInt(new URLSearchParams(location.search).get("page") || "1", 10);
  go((Number.isFinite(start) ? start : 1) - 1);
}

init();
