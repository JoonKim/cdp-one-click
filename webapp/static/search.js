/* Semantic search UI: query -> ranked geo_entity hits + a knowledge graph of the
 * hits. Self-contained SVG force graph (no external libs; renders in screenshots). */

const SVGNS = "http://www.w3.org/2000/svg";
const CLASS_COLOR = {
  Vessel: "#38bdf8", AisTrack: "#22d3ee", SpoofLink: "#fb7185", Route: "#818cf8",
  Place: "#60a5fa", Zone: "#2dd4bf",
  VesselType: "#a78bfa", Flag: "#34d399", Region: "#2dd4bf", Mmsi: "#f59e0b",
  AnomalyType: "#ef4444",
};
const REL_COLOR = {
  sharesIdentityWith: "#ef4444", broadcasts: "#f59e0b", classifiedAs: "#f472b6",
  hasType: "#a78bfa", flaggedAs: "#34d399", operatesIn: "#60a5fa",
};
const EXAMPLES = [
  "a ship pretending to be someone else",
  "impossible speed anomaly",
  "dark / zombie vessels",
  "oil tankers near the Strait of Hormuz",
  "identity theft in the South China Sea",
  "incidents in San Francisco",
];
const W = 900, H = 760;

const $ = (id) => document.getElementById(id);
const svg = () => $("kg-svg");
function el(name, attrs = {}) {
  const e = document.createElementNS(SVGNS, name);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
}

function layout(nodes, edges) {
  const n = nodes.length || 1;
  nodes.forEach((d, i) => {
    const a = (i / n) * Math.PI * 2;
    d.x = W / 2 + Math.cos(a) * 260; d.y = H / 2 + Math.sin(a) * 260; d.vx = d.vy = 0;
  });
  const kRep = 6000, rest = 64, kSpring = 0.02, kCenter = 0.003, damp = 0.85;
  for (let it = 0; it < 380; it++) {
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
      const a = nodes[i], b = nodes[j];
      let dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy + 0.01, d = Math.sqrt(d2), f = kRep / d2;
      a.vx += (dx / d) * f; a.vy += (dy / d) * f; b.vx -= (dx / d) * f; b.vy -= (dy / d) * f;
    }
    edges.forEach((e) => {
      if (!e.s || !e.t) return;
      let dx = e.t.x - e.s.x, dy = e.t.y - e.s.y, d = Math.sqrt(dx * dx + dy * dy) + 0.01, f = kSpring * (d - rest);
      e.s.vx += (dx / d) * f; e.s.vy += (dy / d) * f; e.t.vx -= (dx / d) * f; e.t.vy -= (dy / d) * f;
    });
    for (let i = 0; i < n; i++) {
      const d = nodes[i];
      d.vx += (W / 2 - d.x) * kCenter; d.vy += (H / 2 - d.y) * kCenter;
      d.vx *= damp; d.vy *= damp;
      d.x += Math.max(-24, Math.min(24, d.vx)); d.y += Math.max(-24, Math.min(24, d.vy));
    }
  }
}

function renderGraph(graph) {
  const s = svg();
  s.innerHTML = "";
  s.setAttribute("viewBox", `0 0 ${W} ${H}`);
  if (!graph.nodes.length) {
    s.appendChild(Object.assign(el("text", { x: W / 2, y: H / 2, "text-anchor": "middle", class: "kg-label" }),
      { textContent: "" }));
    return;
  }
  const byId = {};
  const nodes = graph.nodes.map((d) => ({ ...d }));
  nodes.forEach((d) => (byId[d.id] = d));
  const edges = graph.edges.map((e) => ({ ...e, s: byId[e.source], t: byId[e.target] }));
  const deg = {};
  edges.forEach((e) => { deg[e.source] = (deg[e.source] || 0) + 1; deg[e.target] = (deg[e.target] || 0) + 1; });
  layout(nodes, edges);

  edges.forEach((e) => {
    if (!e.s || !e.t) return;
    s.appendChild(el("line", {
      x1: e.s.x, y1: e.s.y, x2: e.t.x, y2: e.t.y,
      stroke: REL_COLOR[e.rel] || "#475569",
      "stroke-width": e.rel === "sharesIdentityWith" ? 2.4 : 1,
      "stroke-opacity": 0.55,
      "stroke-dasharray": e.rel === "sharesIdentityWith" ? "5 4" : "",
    }));
  });
  nodes.forEach((d) => {
    const r = d.hit ? 11 : Math.max(5, Math.min(12, 4 + (deg[d.id] || 1)));
    const g = el("g", { class: "kg-node", transform: `translate(${d.x},${d.y})`, "data-id": d.id });
    const c = el("circle", {
      r, fill: CLASS_COLOR[d.type] || "#94a3b8",
      stroke: d.hit ? "#fff" : "#0b1220", "stroke-width": d.hit ? 2.5 : 1.3,
    });
    g.appendChild(c);
    if (d.hit || d.type !== "Vessel") {
      const t = el("text", { x: 0, y: -r - 4, "text-anchor": "middle", class: "kg-label" });
      t.textContent = d.label.length > 20 ? d.label.slice(0, 18) + "…" : d.label;
      g.appendChild(t);
    }
    const title = el("title"); title.textContent = `${d.label} (${d.type})`; g.appendChild(title);
    s.appendChild(g);
  });
}

function resultCard(r, rank) {
  const li = document.createElement("li");
  li.className = "result-item";
  const badge = r.alert_type
    ? `<span class="res-alert">${r.alert_type}</span>` : "";
  const bits = [r.layer, r.vtype, r.flag, r.region].filter(Boolean).join(" · ");
  li.innerHTML = `
    <div class="res-head">
      <span class="res-rank">${rank}</span>
      <span class="res-name" style="color:${CLASS_COLOR[r.cls] || "#e2e8f0"}">${r.name}</span>
      ${badge}
      <span class="res-score" title="relevance">${r.score.toFixed(3)}</span>
    </div>
    <div class="res-meta">${bits}</div>
    ${r.note ? `<div class="res-note">${r.note}</div>` : ""}`;
  return li;
}

let lastGraph = { nodes: [], edges: [] };
async function run(q) {
  if (!q.trim()) return;
  const btn = $("go"), spin = btn.querySelector(".spinner"), label = btn.querySelector(".btn-label");
  spin.hidden = false; label.textContent = "…"; btn.disabled = true;
  $("q").value = q;
  try {
    const data = await (await fetch(`/api/search?q=${encodeURIComponent(q)}&k=15`)).json();
    const list = $("results"); list.innerHTML = "";
    (data.results || []).forEach((r, i) => list.appendChild(resultCard(r, i + 1)));
    $("meta").textContent = data.count
      ? `${data.count} results for "${data.query}" · graph: ${data.graph.nodes.length} nodes / ${data.graph.edges.length} edges`
      : `No matches for "${data.query}".`;
    lastGraph = data.graph || { nodes: [], edges: [] };
    renderGraph(lastGraph);
    $("graph-caption").textContent = data.count
      ? `Knowledge graph of the results for "${data.query}"` : "Knowledge graph of the results";
  } catch (e) {
    $("meta").textContent = "Search failed.";
  } finally {
    spin.hidden = true; label.textContent = "Search"; btn.disabled = false;
  }
}

function init() {
  const ex = $("examples");
  EXAMPLES.forEach((q) => {
    const c = document.createElement("button");
    c.className = "chip"; c.textContent = q;
    c.addEventListener("click", () => run(q));
    ex.appendChild(c);
  });
  $("go").addEventListener("click", () => run($("q").value));
  $("q").addEventListener("keydown", (e) => { if (e.key === "Enter") run($("q").value); });
  window.addEventListener("resize", () => renderGraph(lastGraph));
  run(EXAMPLES[0]);
}

init();
