/* Services dashboard: render the service catalog + architecture diagram,
 * with an optional live reachability check. */

const TYPE_COLORS = {
  UI: "#38bdf8", API: "#a78bfa", Gateway: "#f97316", Identity: "#f43f5e",
  Service: "#22c55e", Engine: "#22c55e", Storage: "#eab308",
};

function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
}

let INVENTORY = null;

function renderStats(data) {
  const svcs = data.categories.flatMap((c) => c.services);
  const uis = svcs.filter((s) => s.type === "UI").length;
  const withUrl = svcs.filter((s) => s.url).length;
  const stats = [
    ["Services", svcs.length],
    ["Categories", data.categories.length],
    ["Web UIs", uis],
    ["Endpoints", withUrl],
  ];
  const box = document.getElementById("stats");
  box.innerHTML = "";
  stats.forEach(([label, val]) => {
    const card = el("div", "stat");
    card.appendChild(el("div", "stat-val", String(val)));
    card.appendChild(el("div", "stat-label", label));
    box.appendChild(card);
  });
}

function serviceCard(svc) {
  const card = el("div", "svc-card");
  card.id = `svc-${svc.id}`;
  const color = TYPE_COLORS[svc.type] || "#94a3b8";

  const head = el("div", "svc-head");
  const dot = el("span", "status-dot unknown");
  dot.title = "reachability unknown";
  head.appendChild(dot);
  head.appendChild(el("span", "svc-name", svc.name));
  const badge = el("span", "type-badge", svc.type);
  badge.style.borderColor = color;
  badge.style.color = color;
  head.appendChild(badge);
  if (svc.state === "optional") head.appendChild(el("span", "opt-badge", "optional"));
  card.appendChild(head);

  card.appendChild(el("p", "svc-desc", svc.desc || ""));

  const foot = el("div", "svc-foot");
  if (svc.url) {
    const a = el("a", "svc-link");
    a.href = svc.url; a.target = "_blank"; a.rel = "noopener";
    a.textContent = svc.url.length > 60 ? svc.url.slice(0, 57) + "…" : svc.url;
    a.title = svc.url;
    foot.appendChild(a);
  } else {
    foot.appendChild(el("span", "muted small", "no direct web endpoint"));
  }
  card.appendChild(foot);
  return card;
}

function renderCatalog(data) {
  const root = document.getElementById("catalog");
  root.innerHTML = "";
  data.categories.forEach((cat) => {
    const group = el("div", "cat-group");
    group.appendChild(el("h3", "cat-title", cat.name));
    const grid = el("div", "svc-grid");
    cat.services.forEach((s) => grid.appendChild(serviceCard(s)));
    group.appendChild(grid);
    root.appendChild(group);
  });
}

async function init() {
  try {
    INVENTORY = await (await fetch("/api/services")).json();
  } catch (e) {
    document.getElementById("catalog").innerHTML = '<p class="muted">Failed to load services.</p>';
    return;
  }
  document.getElementById("env-name").textContent = INVENTORY.environment || "environment";
  document.getElementById("cloud-name").textContent = INVENTORY.cloud ? `· ${INVENTORY.cloud}` : "";
  renderStats(INVENTORY);
  renderCatalog(INVENTORY);
}

async function runHealth() {
  const btn = document.getElementById("check-health");
  const spin = btn.querySelector(".spinner");
  const label = btn.querySelector(".btn-label");
  btn.disabled = true; spin.hidden = false; label.textContent = "Checking…";
  try {
    const health = await (await fetch("/api/health")).json();
    INVENTORY.categories.flatMap((c) => c.services).forEach((svc) => {
      const dot = document.querySelector(`#svc-${svc.id} .status-dot`);
      if (!dot) return;
      const h = health[svc.id];
      if (!svc.url) { dot.className = "status-dot na"; dot.title = "no endpoint"; return; }
      if (h && h.reachable) { dot.className = "status-dot up"; dot.title = `up (HTTP ${h.status})`; }
      else { dot.className = "status-dot down"; dot.title = "unreachable"; }
    });
  } catch (e) {
    /* ignore */
  } finally {
    spin.hidden = true; label.textContent = "Check reachability"; btn.disabled = false;
  }
}

document.getElementById("check-health").addEventListener("click", runHealth);

init().then(() => runHealth());
