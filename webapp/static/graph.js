/* Knowledge Graph view: renders the ontology/graph (nodes + edges) as a
 * self-contained SVG force-directed graph -- no external libraries, so it
 * always renders in screenshots / saved images. */

const SVGNS = "http://www.w3.org/2000/svg";
const REL_COLOR = {
  sharesIdentityWith: "#ef4444",
  broadcasts: "#f59e0b",
  classifiedAs: "#f472b6",
  hasType: "#a78bfa",
  flaggedAs: "#34d399",
  operatesIn: "#60a5fa",
};
const W = 1200, H = 820;

let DATA = null;         // raw {ontology,nodes,edges,stats}
let NODES = [], EDGES = [], NBYID = {};
let classColor = {};
let hidden = new Set();  // hidden class names
let focusId = "";
let hops = 2;
let view = { x: 0, y: 0, k: 1 };

const $ = (id) => document.getElementById(id);
const svg = () => $("kg-svg");

function el(name, attrs = {}) {
  const e = document.createElementNS(SVGNS, name);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
}

/* ---- force layout (settles synchronously, then renders) ---- */
function layout(nodes, edges) {
  const n = nodes.length;
  nodes.forEach((d, i) => {
    const a = (i / n) * Math.PI * 2;
    d.x = W / 2 + Math.cos(a) * 300 * (0.6 + 0.4 * ((i % 7) / 7));
    d.y = H / 2 + Math.sin(a) * 300 * (0.6 + 0.4 * ((i % 5) / 5));
    d.vx = d.vy = 0;
  });
  const kRep = 5200, rest = 70, kSpring = 0.02, kCenter = 0.0025, damp = 0.86;
  for (let it = 0; it < 420; it++) {
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        let d2 = dx * dx + dy * dy + 0.01;
        const f = kRep / d2;
        const d = Math.sqrt(d2);
        const fx = (dx / d) * f, fy = (dy / d) * f;
        a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
      }
    }
    edges.forEach((e) => {
      const a = e.s, b = e.t;
      if (!a || !b) return;
      let dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.sqrt(dx * dx + dy * dy) + 0.01;
      const f = kSpring * (d - rest);
      const fx = (dx / d) * f, fy = (dy / d) * f;
      a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
    });
    for (let i = 0; i < n; i++) {
      const d = nodes[i];
      d.vx += (W / 2 - d.x) * kCenter;
      d.vy += (H / 2 - d.y) * kCenter;
      d.vx *= damp; d.vy *= damp;
      d.x += Math.max(-25, Math.min(25, d.vx));
      d.y += Math.max(-25, Math.min(25, d.vy));
    }
  }
}

function neighborhood(id, maxHops) {
  if (!id) return null;
  const adj = {};
  DATA.edges.forEach((e) => {
    (adj[e.source] = adj[e.source] || []).push(e.target);
    (adj[e.target] = adj[e.target] || []).push(e.source);
  });
  const seen = { [id]: 0 };
  let frontier = [id];
  for (let h = 0; h < maxHops; h++) {
    const next = [];
    frontier.forEach((f) => (adj[f] || []).forEach((g) => {
      if (!(g in seen)) { seen[g] = h + 1; next.push(g); }
    }));
    frontier = next;
  }
  return new Set(Object.keys(seen));
}

function currentGraph() {
  const keep = neighborhood(focusId, hops);
  const nodes = DATA.nodes.filter(
    (nd) => !hidden.has(nd.type) && (!keep || keep.has(nd.id))
  );
  const ids = new Set(nodes.map((nd) => nd.id));
  const edges = DATA.edges.filter((e) => ids.has(e.source) && ids.has(e.target));
  return { nodes, edges };
}

function degreeMap(edges) {
  const deg = {};
  edges.forEach((e) => { deg[e.source] = (deg[e.source] || 0) + 1; deg[e.target] = (deg[e.target] || 0) + 1; });
  return deg;
}

function render() {
  const g = currentGraph();
  // fresh copies with positions
  NODES = g.nodes.map((d) => ({ ...d }));
  NBYID = {}; NODES.forEach((d) => (NBYID[d.id] = d));
  EDGES = g.edges.map((e) => ({ ...e, s: NBYID[e.source], t: NBYID[e.target] }));
  layout(NODES, EDGES);
  const deg = degreeMap(EDGES);

  const s = svg();
  s.innerHTML = "";
  s.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const vp = el("g", { id: "viewport" });
  s.appendChild(vp);

  // edges
  EDGES.forEach((e) => {
    if (!e.s || !e.t) return;
    const line = el("line", {
      x1: e.s.x, y1: e.s.y, x2: e.t.x, y2: e.t.y,
      stroke: REL_COLOR[e.rel] || "#475569",
      "stroke-width": e.rel === "sharesIdentityWith" ? 2.4 : 1,
      "stroke-opacity": 0.55,
      "stroke-dasharray": e.rel === "sharesIdentityWith" ? "5 4" : "",
    });
    vp.appendChild(line);
  });

  // nodes
  NODES.forEach((d) => {
    const r = d.featured ? 13 : Math.max(5, Math.min(14, 4 + (deg[d.id] || 1)));
    const grp = el("g", { class: "kg-node", transform: `translate(${d.x},${d.y})`, "data-id": d.id });
    const c = el("circle", {
      r, fill: classColor[d.type] || "#94a3b8",
      stroke: d.featured ? "#fff" : "#0b1220",
      "stroke-width": d.featured ? 3 : 1.5,
    });
    if (d.alert === "Spoofing" || d.type === "AnomalyType") c.setAttribute("stroke", "#fecaca");
    grp.appendChild(c);
    const showLabel = d.type !== "Vessel" || d.featured;
    if (showLabel) {
      const t = el("text", { x: 0, y: -r - 4, "text-anchor": "middle", class: "kg-label" });
      t.textContent = d.label.length > 22 ? d.label.slice(0, 20) + "…" : d.label;
      grp.appendChild(t);
    }
    const title = el("title"); title.textContent = `${d.label} (${d.type})`; grp.appendChild(title);
    grp.addEventListener("click", (ev) => { ev.stopPropagation(); showNode(d); });
    vp.appendChild(grp);
  });

  applyTransform();
  $("kg-stats").textContent =
    `Showing ${NODES.length} nodes · ${EDGES.length} edges` +
    (focusId ? ` · focus: ${NBYID[focusId] ? NBYID[focusId].label : focusId}` : ` · of ${DATA.stats.nodes}/${DATA.stats.edges} total`);
}

function applyTransform() {
  const vp = $("viewport");
  if (vp) vp.setAttribute("transform", `translate(${view.x},${view.y}) scale(${view.k})`);
}

function showNode(d) {
  const rels = DATA.edges
    .filter((e) => e.source === d.id || e.target === d.id)
    .map((e) => {
      const out = e.source === d.id;
      const other = NBYID[out ? e.target : e.source] ||
        DATA.nodes.find((n) => n.id === (out ? e.target : e.source));
      const name = other ? other.label : (out ? e.target : e.source);
      return out ? `<li><b>${e.rel}</b> → ${name}</li>` : `<li>${name} <b>${e.rel}</b> → this</li>`;
    });
  const props = Object.entries(d)
    .filter(([k]) => !["id", "type", "label", "x", "y", "vx", "vy"].includes(k))
    .map(([k, v]) => `<div class="kv"><span>${k}</span><b>${v}</b></div>`).join("");
  $("node-info").innerHTML = `
    <div class="kg-chip" style="background:${classColor[d.type]}1a;border-color:${classColor[d.type]}">
      ${d.type}</div>
    <h3 class="kg-node-name">${d.label}</h3>
    ${props}
    <div class="kg-rels"><div class="muted small">relationships (${rels.length})</div><ul>${rels.join("")}</ul></div>`;
}

function buildLegend() {
  const ul = $("legend"); ul.innerHTML = "";
  DATA.ontology.classes.forEach((c) => {
    classColor[c.name] = c.color;
    const n = (DATA.stats.byClass || {})[c.name] || 0;
    const li = document.createElement("li");
    li.className = "kg-legend-item";
    li.innerHTML = `<span class="sw" style="background:${c.color}"></span>
      <span class="nm">${c.name}</span><span class="ct">${n}</span>`;
    li.title = c.desc + " — click to toggle";
    li.addEventListener("click", () => {
      if (hidden.has(c.name)) hidden.delete(c.name); else hidden.add(c.name);
      li.classList.toggle("off", hidden.has(c.name));
      render();
    });
    ul.appendChild(li);
  });
}

function buildFocusOptions() {
  const sel = $("focus-select");
  const notable = DATA.nodes
    .filter((n) => n.featured || ["AnomalyType", "Region", "Mmsi"].includes(n.type))
    .sort((a, b) => (b.featured ? 1 : 0) - (a.featured ? 1 : 0));
  notable.forEach((n) => {
    const o = document.createElement("option");
    o.value = n.id; o.textContent = `${n.label} (${n.type})`;
    sel.appendChild(o);
  });
}

function wirePanZoom() {
  const s = svg();
  let dragging = null, moved = false, start = null;
  s.addEventListener("wheel", (e) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.1 : 0.9;
    view.k = Math.max(0.3, Math.min(4, view.k * factor));
    applyTransform();
  }, { passive: false });
  s.addEventListener("mousedown", (e) => {
    const node = e.target.closest(".kg-node");
    dragging = node ? { node, id: node.getAttribute("data-id") } : { pan: true };
    start = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y }; moved = false;
  });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    moved = true;
    if (dragging.pan) {
      view.x = start.vx + (e.clientX - start.x);
      view.y = start.vy + (e.clientY - start.y);
      applyTransform();
    } else {
      const nd = NBYID[dragging.id];
      const rect = s.getBoundingClientRect();
      const scaleX = W / rect.width;
      nd.x += (e.movementX * scaleX) / view.k;
      nd.y += (e.movementY * scaleX) / view.k;
      dragging.node.setAttribute("transform", `translate(${nd.x},${nd.y})`);
      redrawEdges();
    }
  });
  window.addEventListener("mouseup", () => { dragging = null; });
}

function redrawEdges() {
  const lines = svg().querySelectorAll("#viewport line");
  lines.forEach((ln, i) => {
    const e = EDGES[i];
    if (!e || !e.s || !e.t) return;
    ln.setAttribute("x1", e.s.x); ln.setAttribute("y1", e.s.y);
    ln.setAttribute("x2", e.t.x); ln.setAttribute("y2", e.t.y);
  });
}

async function init() {
  try {
    DATA = await (await fetch("/api/graph")).json();
  } catch (e) {
    $("kg-stats").textContent = "Failed to load knowledge graph.";
    return;
  }
  buildLegend();
  buildFocusOptions();
  // Honor ?focus=<id>&hops=<n>&embed=1 (used by the storyboard to embed a subgraph).
  const q = new URLSearchParams(location.search);
  if (q.get("embed")) document.body.classList.add("embed");
  focusId = q.get("focus") || "";
  if (q.get("hops")) { hops = parseInt(q.get("hops"), 10); $("hops-select").value = String(hops); }
  if (focusId) $("focus-select").value = focusId;
  render();
  const feat = DATA.nodes.find((n) => n.id === focusId) || DATA.nodes.find((n) => n.featured);
  if (feat) showNode(feat);

  $("focus-select").addEventListener("change", (e) => { focusId = e.target.value; render(); });
  $("hops-select").addEventListener("change", (e) => { hops = parseInt(e.target.value, 10); render(); });
  svg().addEventListener("click", () => {});
  wirePanZoom();
}

init();
