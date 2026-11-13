const LEVELS = ["SECRET", "CUI", "UNCLASSIFIED"];
const USERS = { SECRET: "user_S", CUI: "user_C", UNCLASSIFIED: "user_U" };

const app = document.querySelector("#app");
const lede = document.querySelector("#lede");

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function stamp(level) {
  return el("span", `stamp ${level}`, level);
}

function visibleTo(row, principal) {
  return principal === "all" || row.user === principal;
}

function render(doc, principal) {
  app.replaceChildren();
  const cluster = doc.cluster || {};
  const rows = doc.tables || [];
  lede.textContent = `${cluster.name || "Cluster"} · ${rows.length} HBase table${rows.length === 1 ? "" : "s"} recorded as data products.`;

  const banner = el("section", "banner");
  const title = el("strong", null, cluster.mode === "reduced" ? "Reduced cluster" : "Cluster");
  banner.append(title, el("p", null, (cluster.live_cdp && cluster.live_cdp.blocker) || ""));
  if (doc.inventory_note) banner.append(el("p", null, doc.inventory_note));
  const meta = el("div", "meta");
  meta.append(
    el("span", null, `Status: ${doc.status || "recorded"}`),
    el("span", null, `Recorded: ${doc.recorded_at || ""}`),
    el("span", null, `Seed: ${doc.seed}`)
  );
  banner.append(meta);
  app.append(banner);

  const controls = el("section");
  controls.append(el("h2", null, "Browse the access story"));
  controls.append(el("p", null, "The assignment stays visible. Choosing a user shows which products that principal can open and marks the rest as outside their level."));
  const toolbar = el("div", "toolbar");
  const choices = [["all", "All principals"], ["user_S", "user_S · SECRET"], ["user_C", "user_C · CUI"], ["user_U", "user_U · UNCLASSIFIED"]];
  choices.forEach(([value, label]) => {
    const button = el("button", null, label);
    button.type = "button";
    button.setAttribute("aria-pressed", value === principal ? "true" : "false");
    button.addEventListener("click", () => {
      const url = new URL(location.href);
      if (value === "all") url.searchParams.delete("as");
      else url.searchParams.set("as", value);
      history.replaceState(null, "", url);
      render(doc, value);
    });
    toolbar.append(button);
  });
  controls.append(toolbar);
  app.append(controls);

  const assignment = el("section");
  assignment.append(el("h2", null, "Assignment"));
  const wrap = el("div", "table-wrap");
  const table = document.createElement("table");
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  ["Table", "Level", "User", "Ranger policy", "Atlas classification"].forEach((label) => {
    headRow.append(el("th", null, label));
  });
  head.append(headRow);
  table.append(head);
  const body = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    if (!visibleTo(row, principal)) tr.className = "dim";
    const name = el("td");
    name.append(el("code", null, row.name));
    const level = el("td");
    level.append(stamp(row.level));
    const user = el("td", null, row.user);
    const policy = el("td");
    policy.append(el("code", null, row.ranger_policy));
    const classification = el("td");
    classification.append(stamp(row.atlas_classification || row.level));
    tr.append(name, level, user, policy, classification);
    body.append(tr);
  });
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = el("td", null, "No HBase tables were listed.");
    td.colSpan = 5;
    tr.append(td);
    body.append(tr);
  }
  table.append(body);
  wrap.append(table);
  assignment.append(wrap);
  app.append(assignment);

  const story = el("section");
  story.append(el("h2", null, "Who sees which tables"));
  const stories = el("div", "stories");
  LEVELS.forEach((level) => {
    const user = USERS[level];
    const card = el("article", "story");
    const header = document.createElement("header");
    header.append(el("h3", null, user), stamp(level));
    card.append(header);
    const mine = rows.filter((row) => row.level === level);
    if (!mine.length) {
      card.append(el("p", "empty", "No table was assigned this level. This user sees an empty catalog."));
    } else {
      const list = document.createElement("ul");
      mine.forEach((row) => list.append(el("li", null, row.name)));
      card.append(list);
    }
    const denied = rows.filter((row) => row.level !== level).map((row) => row.name);
    card.append(el("p", null, denied.length ? `Cannot open: ${denied.join(", ")}` : "No tables sit outside this level."));
    stories.append(card);
  });
  story.append(stories);
  app.append(story);

  const products = el("section");
  products.append(el("h2", null, "Data products"));
  const grid = el("div", "products");
  rows.forEach((row) => {
    const card = el("article", visibleTo(row, principal) ? "card" : "card denied");
    const header = document.createElement("header");
    header.append(el("h3", null, row.name), stamp(row.level));
    card.append(header);
    const lineage = row.lineage || {};
    const track = el("ol", "lineage");
    [
      ["Source", lineage.input],
      ["Process", lineage.process],
      ["Product", lineage.output || row.name],
    ].forEach(([label, value], index) => {
      if (index) track.append(el("span", "arrow", "→"));
      const item = document.createElement("li");
      item.append(el("span", null, label), document.createTextNode(value || ""));
      track.append(item);
    });
    card.append(track);
    const facts = document.createElement("dl");
    const ranger = (doc.ranger && doc.ranger.policies || []).find((policy) => policy.name === row.ranger_policy);
    const atlas = (doc.atlas && doc.atlas.entities || []).find((entity) => entity.table === row.name);
    addFact(facts, "User", row.user);
    addFact(facts, "Role", row.role);
    addFact(facts, "Ranger policy", ranger ? `${ranger.name} (#${ranger.id})` : row.ranger_policy);
    addFact(facts, "Atlas", atlas && atlas.guid ? atlas.guid : "classification " + row.level);
    card.append(facts);
    if (atlas && atlas.ui) {
      const link = el("a", null, "Open lineage in Atlas");
      link.href = atlas.ui;
      link.rel = "noreferrer";
      card.append(link);
    }
    grid.append(card);
  });
  products.append(grid);
  app.append(products);

  const where = el("section", "panel");
  where.style.padding = "16px";
  where.append(el("h2", null, "Where the controls live"));
  const services = (cluster.services || {});
  const list = document.createElement("ul");
  list.append(el("li", null, `HBase: ${(services.hbase && services.hbase.ui) || ""}`));
  list.append(el("li", null, (doc.ranger && doc.ranger.where) || `Ranger: ${(services.ranger && services.ranger.ui) || ""}`));
  list.append(el("li", null, (doc.atlas && doc.atlas.where) || `Atlas: ${(services.atlas && services.atlas.ui) || ""}`));
  where.append(list);
  if (doc.ranger && doc.ranger.note) where.append(el("p", null, doc.ranger.note));
  if (doc.error) where.append(el("p", null, doc.error));
  app.append(where);
}

function addFact(list, label, value) {
  list.append(el("dt", null, label), el("dd", null, value || ""));
}

const principals = new Set(["all", "user_S", "user_C", "user_U"]);

function principalFromLocation() {
  const requested = new URLSearchParams(location.search).get("as") || "all";
  return principals.has(requested) ? requested : "all";
}

fetch("/api/catalog")
  .then((response) => {
    if (!response.ok) throw new Error("The assignment file is not available.");
    return response.json();
  })
  .then((doc) => render(doc, principalFromLocation()))
  .catch((error) => {
    app.replaceChildren(el("p", "banner", error.message));
  });
