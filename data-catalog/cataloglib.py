"""Shared catalog model: HBase table parsing, security assignment, and the assignment document."""

from __future__ import annotations

import random
from typing import Iterable

LEVELS = ("SECRET", "CUI", "UNCLASSIFIED")
USERS = {
    "SECRET": "user_S",
    "CUI": "user_C",
    "UNCLASSIFIED": "user_U",
}
ROLES = {
    "SECRET": "role_SECRET",
    "CUI": "role_CUI",
    "UNCLASSIFIED": "role_UNCLASSIFIED",
}
CLUSTER_NAME = "cdp-reduced-local"
RANGER_SERVICE = "cdp_hbase"
LOCKED_TABLES = ("hbase:meta", "hbase:namespace")
USER_PRODUCTS = (
    "catalog:personnel",
    "catalog:facilities",
    "catalog:notices",
    "catalog:supply",
)

LIVE_CDP_BLOCKER = (
    "No live CDP cluster is reachable from this environment. "
    "The CDP CLI is not installed, ~/.cdp does not exist, and no CDP access key is configured. "
    "The AWS, Azure, and GCP CLIs are not installed, so there is no cloud credential to inspect or create an environment with. "
    "The repo's parameters directory is gitignored and is not present, so cdp_create_all_the_things.sh has no parameter file to run. "
    "A full-size CDP environment (cloud network, data lake, and Operational Database) was not created. "
    "This assignment uses a reduced single-node cluster that runs HBase, Ranger, and Atlas only."
)


def parse_shell_block(shell_output: str, marker: str) -> list[str]:
    """Parse a named block from HBase shell output, such as TABLE or NAMESPACE."""
    found: list[str] = []
    capture = False
    for raw in shell_output.splitlines():
        line = raw.strip()
        if line == marker:
            capture = True
            found = []
            continue
        if not capture:
            continue
        if not line or line.startswith("Took "):
            continue
        if line.endswith("row(s)") or line.startswith("=>"):
            capture = False
            continue
        if any(token in line for token in ("INFO", "WARN", "ERROR", "SLF4J", "OpenJDK")):
            continue
        if " " in line or line.startswith("hbase("):
            continue
        found.append(line)
    return _unique(found)


def parse_hbase_tables(shell_output: str) -> list[str]:
    """Parse `list` output from the HBase shell.

    Prefers the TABLE block. Falls back to the Ruby array the shell prints
    after a non-interactive list.
    """
    tables = parse_shell_block(shell_output, "TABLE")
    if tables:
        return tables

    for raw in shell_output.splitlines():
        line = raw.strip()
        if line.startswith("=> [") and line.endswith("]"):
            inner = line[len("=> [") : -1]
            found = []
            for part in inner.split(","):
                name = part.strip().strip('"').strip("'")
                if name:
                    found.append(name)
            if found:
                return _unique(found)
    return []


def _unique(names: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def table_kind(table_name: str) -> str:
    if table_name.startswith("hbase:"):
        return "system"
    return "product"


def assign_tables(tables: list[str], seed: int) -> list[dict]:
    """Assign each table to exactly one security level.

    The same seed always produces the same assignment. The caller must persist
    the result before creating Ranger policies or Atlas objects.
    """
    rng = random.Random(seed)
    rows = []
    for name in tables:
        level = rng.choice(LEVELS)
        rows.append(_row(name, level))
    return rows


def _row(name: str, level: str) -> dict:
    return {
        "name": name,
        "namespace": namespace_of(name),
        "kind": table_kind(name),
        "level": level,
        "user": USERS[level],
        "role": ROLES[level],
        "ranger_policy": f"hbase-level-{level}",
        "atlas_classification": level,
        "lineage": {
            "input": f"namespace:{namespace_of(name)}",
            "process": f"register:{name}",
            "output": name,
        },
    }


def assign_new_tables(existing_rows: list[dict], new_names: list[str], seed: int) -> tuple[list[dict], int]:
    """Randomly assign only new tables.

    Existing rows are not modified. Draws are repeated until CUI and
    UNCLASSIFIED each have at least one table in the combined catalog.
    The returned seed is the draw that satisfied that constraint.
    """
    known = {row["name"] for row in existing_rows}
    locked = [name for name in new_names if name in LOCKED_TABLES or name in known]
    if locked:
        raise ValueError("Refusing to reassign " + ", ".join(locked))
    if not new_names:
        return [], seed

    rng = random.Random(seed)
    draw_seed = seed
    for _ in range(10000):
        rows = assign_tables(new_names, draw_seed)
        combined = list(existing_rows) + rows
        if tables_for_level(combined, "CUI") and tables_for_level(combined, "UNCLASSIFIED"):
            return rows, draw_seed
        draw_seed = rng.randrange(1, 2**31) or 1
    raise RuntimeError("Could not draw an assignment that covers CUI and UNCLASSIFIED.")


def namespace_of(table_name: str) -> str:
    if ":" in table_name:
        return table_name.split(":", 1)[0]
    return "default"


def tables_for_level(rows: list[dict], level: str) -> list[str]:
    return [row["name"] for row in rows if row["level"] == level]


def render_assignment_doc(doc: dict) -> str:
    cluster = doc["cluster"]
    rows = doc["tables"]
    lines = [
        "---",
        'cursor:',
        '  subagentId: "bc-19f828a0-a9c2-56a8-ac16-273db5a9db25"',
        "---",
        "",
        "# HBase security assignment",
        "",
        "Each HBase table is one data product. It has exactly one security level, and exactly one principal can access it.",
        "",
        "## Cluster",
        "",
        f"- Name: `{cluster['name']}`",
        f"- Mode: {cluster['mode']}",
        f"- Recorded at: {doc['recorded_at']}",
        f"- Assignment seed: `{doc['seed']}`",
        f"- Apply status: {doc.get('status', 'recorded')}",
    ]
    if doc.get("extension_seed"):
        lines.append(f"- User-table seed: `{doc['extension_seed']}`")
        lines.append(f"- User tables recorded at: {doc.get('extended_at', '')}")
    lines.extend(
        [
        "",
        "### Live CDP",
        "",
        cluster["live_cdp"]["blocker"],
        "",
        "### Reduced cluster",
        "",
        "HBase, Ranger, and Atlas run as separate containers on one Docker network named `cdp-reduced`. No cloud data lake and no full CDP environment were created.",
        "",
        f"- HBase master UI: {cluster['services']['hbase']['ui']}",
        f"- Ranger Admin: {cluster['services']['ranger']['ui']}",
        f"- Apache Atlas: {cluster['services']['atlas']['ui']}",
        "",
        "## Assignment",
        "",
        "Each row was recorded before the Ranger policy and Atlas lineage for that table were applied.",
        "`hbase:meta` and `hbase:namespace` keep the original SECRET assignment. Those two tables were not drawn again.",
        "",
        "| Table | Kind | Level | User who can access it |",
        "| --- | --- | --- | --- |",
        ]
    )
    for row in rows:
        kind = "System table" if table_kind(row["name"]) == "system" else "Data product"
        lines.append(f"| `{row['name']}` | {kind} | {row['level']} | {row['user']} |")
    if not rows:
        lines.append("| _none listed_ |  |  |  |")
    if doc.get("inventory_note"):
        lines.extend(["", doc["inventory_note"]])

    lines.extend(
        [
            "",
            "## Access story",
            "",
            "user_S can access only SECRET tables. user_C can access only CUI tables. user_U can access only UNCLASSIFIED tables.",
            "",
        ]
    )
    for level in LEVELS:
        user = USERS[level]
        names = tables_for_level(rows, level)
        shown = ", ".join(f"`{name}`" for name in names) if names else "_none_"
        lines.append(f"- **{user}** ({level}): {shown}")

    lines.extend(["", "## Ranger", ""])
    ranger = doc.get("ranger") or {}
    lines.append(
        f"Ranger service `{ranger.get('service', RANGER_SERVICE)}` on {cluster['services']['ranger']['ui']}."
    )
    lines.append(
        "Open Ranger Admin, then Service Manager, then the HBase service. Each policy allows one role and denies the other two users."
    )
    lines.append("")
    policies = ranger.get("policies") or []
    if policies:
        lines.append("| Policy | Level | Role | Tables | Ranger id |")
        lines.append("| --- | --- | --- | --- | --- |")
        for policy in policies:
            table_list = ", ".join(f"`{name}`" for name in policy.get("tables") or []) or "_none_"
            lines.append(
                f"| `{policy['name']}` | {policy['level']} | {policy['role']} | {table_list} | {policy.get('id', '')} |"
            )
    else:
        lines.append("Policies are not applied yet. The names reserved for them are `hbase-level-SECRET`, `hbase-level-CUI`, and `hbase-level-UNCLASSIFIED`.")
    if ranger.get("note"):
        lines.extend(["", ranger["note"]])

    lines.extend(["", "## Atlas", ""])
    atlas = doc.get("atlas") or {}
    lines.append(f"Atlas UI: {cluster['services']['atlas']['ui']}.")
    lines.append(
        "Classifications `SECRET`, `CUI`, and `UNCLASSIFIED` are Atlas classification types. Each table entity carries the classification for its level."
    )
    lines.append(
        "Lineage for a table is namespace → `register:<table>` process → the table data product. Open the table entity in Atlas and choose the Lineage tab, or call the lineage API path below."
    )
    lines.append("")
    entities = atlas.get("entities") or []
    if entities:
        lines.append("| Table | Classification | Entity guid | Lineage API |")
        lines.append("| --- | --- | --- | --- |")
        for entity in entities:
            lines.append(
                f"| `{entity['table']}` | {entity['classification']} | `{entity.get('guid', '')}` | `{entity.get('lineage_api', '')}` |"
            )
    else:
        lines.append("Atlas entities are not applied yet. The catalog still shows the lineage that will be created for each table.")
    if atlas.get("note"):
        lines.extend(["", atlas["note"]])

    lines.extend(
        [
            "",
            "## Dashboard",
            "",
            "From the repository root:",
            "",
            "```",
            "python3 data-catalog/server.py",
            "```",
            "",
            "Then open http://127.0.0.1:8765 . The page lists every table, its level, the user who can access it, the Ranger policy, and the Atlas lineage. Choose user_S, user_C, or user_U to see only the products that principal is allowed to open.",
            "",
        ]
    )
    if doc.get("error"):
        lines.extend(["## Apply error", "", doc["error"], ""])
    return "\n".join(lines)
