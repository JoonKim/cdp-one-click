/* Iceberg table viewer: loads the Spark3/Iceberg export and renders it as a
 * sortable, filterable, paginated table. */

const PAGE_SIZE = 25;
const NUM_COLS = new Set([
  "center_lon", "center_lat", "min_lon", "min_lat", "max_lon", "max_lat", "sog",
]);

let DATA = { columns: [], rows: [] };
let view = [];
let page = 0;
let sortCol = null;
let sortDir = 1;

function fmt(col, val) {
  if (val === null || val === undefined || val === "") return "";
  if (NUM_COLS.has(col) && typeof val === "number") {
    return col === "sog" ? val.toFixed(1) : val.toFixed(5);
  }
  return String(val);
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function buildHead() {
  const row = document.getElementById("head-row");
  row.innerHTML = "";
  DATA.columns.forEach((col) => {
    const th = el("th", "sortable", col);
    th.addEventListener("click", () => {
      if (sortCol === col) sortDir = -sortDir;
      else { sortCol = col; sortDir = 1; }
      applyFilters();
    });
    if (sortCol === col) th.classList.add(sortDir > 0 ? "asc" : "desc");
    row.appendChild(th);
  });
}

function applyFilters() {
  const q = document.getElementById("filter").value.trim().toLowerCase();
  const layer = document.getElementById("layer-select").value;
  const alertsOnly = document.getElementById("alerts-only").checked;

  view = DATA.rows.filter((r) => {
    if (layer && r.layer !== layer) return false;
    if (alertsOnly && !r.alert_type) return false;
    if (!q) return true;
    return DATA.columns.some((c) => String(r[c] ?? "").toLowerCase().includes(q));
  });

  if (sortCol) {
    view.sort((a, b) => {
      const x = a[sortCol], y = b[sortCol];
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      if (x < y) return -1 * sortDir;
      if (x > y) return 1 * sortDir;
      return 0;
    });
  }
  page = 0;
  buildHead();
  renderPage();
}

function renderPage() {
  const body = document.getElementById("body");
  body.innerHTML = "";
  const start = page * PAGE_SIZE;
  const slice = view.slice(start, start + PAGE_SIZE);
  slice.forEach((r) => {
    const tr = el("tr");
    if (r.alert_type) tr.classList.add("alert-row");
    DATA.columns.forEach((c) => {
      const td = el("td", NUM_COLS.has(c) ? "num" : null, fmt(c, r[c]));
      if (c === "alert_type" && r.alert_type) td.classList.add("alert-cell");
      tr.appendChild(td);
    });
    body.appendChild(tr);
  });
  const pages = Math.max(1, Math.ceil(view.length / PAGE_SIZE));
  document.getElementById("page-info").textContent =
    `Page ${page + 1} / ${pages}`;
  document.getElementById("row-count").textContent =
    `${view.length} of ${DATA.rows.length} rows`;
  document.getElementById("prev").disabled = page <= 0;
  document.getElementById("next").disabled = page >= pages - 1;
}

function fillMeta() {
  document.getElementById("m-rows").textContent = DATA.rowCount ?? DATA.rows.length;
  document.getElementById("m-layers").textContent =
    DATA.perLayer ? Object.keys(DATA.perLayer).length : "—";
  document.getElementById("m-files").textContent = DATA.dataFiles ?? "—";
  document.getElementById("m-format").textContent = (DATA.format || "iceberg").toUpperCase();
  document.getElementById("t-name").textContent = DATA.table || "geo.geo_entity";
  const bits = [];
  if (DATA.catalog) bits.push(DATA.catalog);
  if (DATA.snapshotId) bits.push(`snapshot ${DATA.snapshotId}`);
  document.getElementById("t-sub").textContent = bits.join(" · ");
  document.getElementById("t-location").textContent = DATA.location || "";

  const sel = document.getElementById("layer-select");
  Object.keys(DATA.perLayer || {}).sort().forEach((l) => {
    const o = el("option", null, `${l} (${DATA.perLayer[l]})`);
    o.value = l;
    sel.appendChild(o);
  });
}

async function init() {
  try {
    DATA = await (await fetch("/api/iceberg")).json();
  } catch (e) {
    document.getElementById("body").innerHTML =
      '<tr><td>Failed to load Iceberg export.</td></tr>';
    return;
  }
  if (DATA.error) {
    document.getElementById("t-sub").textContent = DATA.error;
  }
  fillMeta();
  buildHead();
  applyFilters();

  document.getElementById("filter").addEventListener("input", applyFilters);
  document.getElementById("layer-select").addEventListener("change", applyFilters);
  document.getElementById("alerts-only").addEventListener("change", applyFilters);
  document.getElementById("prev").addEventListener("click", () => { if (page > 0) { page--; renderPage(); } });
  document.getElementById("next").addEventListener("click", () => {
    const pages = Math.ceil(view.length / PAGE_SIZE);
    if (page < pages - 1) { page++; renderPage(); }
  });
}

init();
