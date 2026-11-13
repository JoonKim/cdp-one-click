#!/usr/bin/env python3
"""List HBase tables, record a random security assignment, then apply it.

The assignment file is written and fsynced before any Ranger or Atlas change.
Credentials are read from local env files or generated in memory. They are
never printed and never written into the assignment.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cataloglib import (  # noqa: E402
    CLUSTER_NAME,
    LEVELS,
    LIVE_CDP_BLOCKER,
    RANGER_SERVICE,
    ROLES,
    USERS,
    assign_tables,
    parse_hbase_tables,
    parse_shell_block,
    render_assignment_doc,
    tables_for_level,
)

ASSIGNMENT_PATH = ROOT / "assignment.json"
DEFAULT_DOC_PATH = Path(
    "/cursor/stores/bc-e6e42d84-dff1-4ee6-bb0e-28a1eb932ced/docs/hbase-security-assignment.md"
)
RANGER_URL = os.environ.get("RANGER_URL", "http://127.0.0.1:6080")
ATLAS_URL = os.environ.get("ATLAS_URL", "http://127.0.0.1:21000")
HBASE_CONTAINER = os.environ.get("HBASE_CONTAINER", "hbase")
ATLAS_CONTAINER = os.environ.get("ATLAS_CONTAINER", "atlas")
RANGER_ENV_FILE = Path(os.environ.get("RANGER_ENV_FILE", "/tmp/ranger-reduced.env"))


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def redact(text: str, hidden: list[str]) -> str:
    cleaned = text
    for secret in hidden:
        if secret:
            cleaned = cleaned.replace(secret, "***")
    return cleaned


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(payload, indent=2) + "\n"
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def load_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def cluster_block() -> dict:
    return {
        "name": CLUSTER_NAME,
        "mode": "reduced",
        "live_cdp": {"reachable": False, "blocker": LIVE_CDP_BLOCKER},
        "services": {
            "hbase": {
                "ui": "http://127.0.0.1:16010",
                "container": HBASE_CONTAINER,
                "image": "seatunnelhub/hbase-standalone:2.4.9",
            },
            "ranger": {
                "ui": RANGER_URL,
                "service": RANGER_SERVICE,
                "image": "apache/ranger:2.9.0",
            },
            "atlas": {
                "ui": ATLAS_URL,
                "image": "sburn/apache-atlas:2.3.0",
            },
        },
    }


def base_document(rows: list[dict], seed: int) -> dict:
    return {
        "cluster": cluster_block(),
        "seed": seed,
        "recorded_at": utc_now(),
        "status": "recorded",
        "levels": {level: USERS[level] for level in LEVELS},
        "roles": ROLES,
        "tables": rows,
        "ranger": {"service": RANGER_SERVICE, "policies": [], "note": ""},
        "atlas": {"entities": [], "note": ""},
    }


def hbase_shell(command: str) -> str:
    proc = subprocess.run(
        ["sudo", "docker", "exec", "-i", HBASE_CONTAINER, "/hbase/bin/hbase", "shell", "-n"],
        input=command + "\n",
        text=True,
        capture_output=True,
        timeout=180,
    )
    if proc.returncode != 0 and not proc.stdout:
        detail = (proc.stderr or "").strip().splitlines()
        raise RuntimeError(detail[-1] if detail else f"hbase shell exit {proc.returncode}")
    return proc.stdout


def list_hbase_tables(attempts: int = 20) -> list[str]:
    """Return every existing table, including HBase system tables.

    The shell `list` command hides the `hbase` namespace. Those tables still
    exist, so the inventory walks each namespace.
    """
    last_error = "HBase shell did not return a namespace list."
    for _ in range(attempts):
        try:
            namespaces = parse_shell_block(hbase_shell("list_namespace"), "NAMESPACE")
        except RuntimeError as exc:
            last_error = str(exc)
            time.sleep(4)
            continue
        if not namespaces:
            last_error = "HBase has not published namespaces yet."
            time.sleep(4)
            continue
        tables: list[str] = []
        for namespace in namespaces:
            short_names = parse_hbase_tables(hbase_shell(f"list_namespace_tables '{namespace}'"))
            for short_name in short_names:
                if namespace == "default":
                    tables.append(short_name)
                else:
                    tables.append(f"{namespace}:{short_name}")
        return tables
    raise RuntimeError(last_error)


class Api:
    def __init__(self, base: str, user: str, password: str):
        self.base = base.rstrip("/")
        self.user = user
        self.password = password

    def call(self, method: str, path: str, payload: dict | None = None, timeout: int = 60):
        url = self.base + path
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        token = base64.b64encode(f"{self.user}:{self.password}".encode()).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                body = json.loads(raw.decode("utf-8")) if raw else None
                return response.status, body
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", "replace")
            try:
                body = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                body = raw
            return error.code, body

    def wait_until_ready(self, path: str, label: str, attempts: int = 60) -> None:
        last = "no response"
        for _ in range(attempts):
            try:
                status, _body = self.call("GET", path, timeout=20)
            except Exception as exc:  # noqa: BLE001
                status = 0
                last = type(exc).__name__
            else:
                if status in (200, 401, 403):
                    return
                last = str(status)
            time.sleep(5)
        raise RuntimeError(f"{label} did not become ready ({last})")


def ranger_password() -> str:
    if os.environ.get("RANGER_ADMIN_PASSWORD"):
        return os.environ["RANGER_ADMIN_PASSWORD"]
    values = load_env_file(RANGER_ENV_FILE)
    password = values.get("RANGER_DB_PASSWORD", "")
    if not password:
        raise RuntimeError(
            "Ranger admin password is not available. Set RANGER_ADMIN_PASSWORD or provide the local Ranger env file."
        )
    return password


ATLAS_ENV_FILE = Path(os.environ.get("ATLAS_ENV_FILE", "/tmp/atlas-reduced.env"))


def ensure_atlas_user(password: str) -> str:
    """Add a catalog admin whose password is kept only in the local env file."""
    user = "catalog_admin"
    digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
    line = f"{user}=ADMIN::{digest}\n"
    proc = subprocess.run(
        [
            "sudo",
            "docker",
            "exec",
            "-i",
            ATLAS_CONTAINER,
            "tee",
            "-a",
            "/apache-atlas/conf/users-credentials.properties",
        ],
        input=line,
        text=True,
        capture_output=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError("Could not add an Atlas catalog user inside the Atlas container.")
    return user


def atlas_credentials() -> tuple[str, str]:
    saved = load_env_file(ATLAS_ENV_FILE)
    if saved.get("ATLAS_PASSWORD"):
        return saved.get("ATLAS_USER", "catalog_admin"), saved["ATLAS_PASSWORD"]
    password = secrets.token_urlsafe(18)
    user = ensure_atlas_user(password)
    ATLAS_ENV_FILE.write_text(f"ATLAS_USER={user}\nATLAS_PASSWORD={password}\n", encoding="utf-8")
    ATLAS_ENV_FILE.chmod(0o600)
    return user, password


def message_from(body, hidden: list[str]) -> str:
    if isinstance(body, dict):
        text = str(body.get("msgDesc") or body.get("message") or body.get("error") or body)
    else:
        text = str(body)
    text = redact(text, hidden)
    return text[:500]


def apply_ranger(doc: dict, hidden: list[str]) -> None:
    password = ranger_password()
    hidden.append(password)
    service_password = secrets.token_urlsafe(18)
    hidden.append(service_password)
    user_passwords = {USERS[level]: secrets.token_urlsafe(18) for level in LEVELS}
    hidden.extend(user_passwords.values())

    api = Api(RANGER_URL, "admin", password)
    api.wait_until_ready("/service/public/v2/api/servicedef/name/hbase", "Ranger")

    status, service_def = api.call("GET", "/service/public/v2/api/servicedef/name/hbase")
    if status != 200 or not isinstance(service_def, dict):
        raise RuntimeError(f"Ranger HBase service definition unavailable ({status})")
    access_types = [item["name"] for item in service_def.get("accessTypes") or []]
    resource_names = [item["name"] for item in service_def.get("resources") or []]
    if "table" not in resource_names:
        raise RuntimeError("Ranger HBase service definition has no table resource.")

    for level in LEVELS:
        username = USERS[level]
        created, body = api.call(
            "POST",
            "/service/xusers/secure/users",
            {
                "name": username,
                "password": user_passwords[username],
                "firstName": username,
                "lastName": level,
                "emailAddress": f"{username}@cdp-reduced.local",
                "description": f"Principal cleared for {level} HBase tables",
                "status": 1,
                "userRoleList": ["ROLE_USER"],
            },
        )
        if created not in (200, 201, 400):
            raise RuntimeError(f"Could not create {username} ({created}: {message_from(body, hidden)})")

        role_status, role_body = api.call(
            "POST",
            "/service/roles/roles",
            {
                "name": ROLES[level],
                "description": f"RBAC role for {level} HBase tables",
                "users": [{"name": username, "isAdmin": False}],
                "groups": [],
                "roles": [],
            },
        )
        if role_status not in (200, 201):
            existing, _existing_body = api.call("GET", f"/service/roles/roles/name/{ROLES[level]}")
            if existing != 200:
                raise RuntimeError(
                    f"Could not create {ROLES[level]} ({role_status}: {message_from(role_body, hidden)})"
                )

    service_payload = {
        "name": RANGER_SERVICE,
        "type": "hbase",
        "displayName": "CDP reduced HBase",
        "description": "HBase tables on cdp-reduced-local",
        "isEnabled": True,
        "configs": {
            "username": "hbase",
            "password": service_password,
            "hadoop.security.authentication": "simple",
            "hbase.security.authentication": "simple",
            "hadoop.security.authorization": "true",
            "hbase.zookeeper.property.clientPort": "2181",
            "hbase.zookeeper.quorum": HBASE_CONTAINER,
            "zookeeper.znode.parent": "/hbase",
            "policy.download.auth.users": "hbase",
        },
    }
    service_status, service_body = api.call("POST", "/service/public/v2/api/service", service_payload)
    if service_status not in (200, 201):
        lookup, lookup_body = api.call("GET", f"/service/public/v2/api/service/name/{RANGER_SERVICE}")
        if lookup != 200:
            raise RuntimeError(
                f"Could not create Ranger service {RANGER_SERVICE} "
                f"({service_status}: {message_from(service_body or lookup_body, hidden)})"
            )

    policies = []
    for level in LEVELS:
        names = tables_for_level(doc["tables"], level)
        if not names:
            continue
        resources = {}
        for resource_name in resource_names:
            values = names if resource_name == "table" else ["*"]
            resources[resource_name] = {
                "values": values,
                "isExcludes": False,
                "isRecursive": False,
            }
        other_users = [USERS[item] for item in LEVELS if item != level]
        payload = {
            "service": RANGER_SERVICE,
            "name": f"hbase-level-{level}",
            "policyType": 0,
            "description": f"Allow {USERS[level]} to access {level} HBase tables. Deny the other catalog users.",
            "isEnabled": True,
            "isAuditEnabled": True,
            "resources": resources,
            "policyItems": [
                {
                    "roles": [ROLES[level]],
                    "accesses": [{"type": access, "isAllowed": True} for access in access_types],
                }
            ],
            "denyPolicyItems": [
                {
                    "users": other_users,
                    "accesses": [{"type": access, "isAllowed": True} for access in access_types],
                }
            ],
            "allowExceptions": [],
            "denyExceptions": [],
        }
        status, body = api.call("POST", "/service/public/v2/api/policy", payload)
        if status not in (200, 201) or not isinstance(body, dict):
            lookup, lookup_body = api.call(
                "GET",
                f"/service/public/v2/api/service/{RANGER_SERVICE}/policy/{payload['name']}",
            )
            if lookup == 200 and isinstance(lookup_body, dict):
                body = lookup_body
            else:
                raise RuntimeError(
                    f"Could not create policy hbase-level-{level} ({status}: {message_from(body, hidden)})"
                )
        policies.append(
            {
                "name": body.get("name", payload["name"]),
                "id": body.get("id"),
                "level": level,
                "role": ROLES[level],
                "user": USERS[level],
                "tables": names,
                "deny_users": other_users,
                "service": RANGER_SERVICE,
            }
        )

    doc["ranger"] = {
        "service": RANGER_SERVICE,
        "ui": RANGER_URL,
        "where": (
            f"{RANGER_URL} → Service Manager → {RANGER_SERVICE}. "
            + (
                "Policies "
                + ", ".join(policy["name"] for policy in policies)
                + " grant the matching role and deny the other two users."
                if policies
                else "No resource policy was created because no tables were assigned."
            )
        ),
        "policies": policies,
        "note": (
            "The reduced HBase image does not load the Ranger HBase plugin, so these policies "
            "are enforced by Ranger's policy store and shown in the catalog. "
            "A full CDP Operational Database would push the same policies to RegionServers."
        ),
    }


def atlas_typedefs() -> dict:
    def string_attr(name: str) -> dict:
        return {
            "name": name,
            "typeName": "string",
            "isOptional": True,
            "isUnique": False,
            "isIndexable": True,
            "cardinality": "SINGLE",
        }

    return {
        "entityDefs": [
            {
                "name": "cdp_data_product",
                "superTypes": ["DataSet"],
                "serviceType": "cdp_catalog",
                "category": "ENTITY",
                "description": "HBase table published as a data product",
                "attributeDefs": [
                    string_attr("securityLevel"),
                    string_attr("authorizedUser"),
                ],
            },
            {
                "name": "cdp_catalog_process",
                "superTypes": ["Process"],
                "serviceType": "cdp_catalog",
                "category": "ENTITY",
                "description": "Registration of an HBase table into the data catalog",
                "attributeDefs": [],
            },
        ],
        "classificationDefs": [
            {
                "category": "CLASSIFICATION",
                "name": level,
                "description": f"Security level {level}. Only {USERS[level]} may access tables with this classification.",
                "attributeDefs": [],
            }
            for level in LEVELS
        ],
    }


def atlas_get_unique(api: Api, type_name: str, qualified_name: str):
    quoted = urllib.parse.quote(qualified_name, safe="")
    path = f"/api/atlas/v2/entity/uniqueAttribute/type/{type_name}?attr:qualifiedName={quoted}"
    status, body = api.call("GET", path)
    if status == 404:
        return None
    if status != 200 or not isinstance(body, dict):
        return None
    return body.get("entity")


def apply_atlas(doc: dict, hidden: list[str]) -> None:
    user, password = atlas_credentials()
    hidden.append(password)
    api = Api(ATLAS_URL, user, password)

    ready = False
    last = "no response"
    for _ in range(90):
        try:
            status, _body = api.call("GET", "/api/atlas/admin/version", timeout=20)
        except Exception as exc:  # noqa: BLE001
            status = 0
            last = type(exc).__name__
        else:
            last = str(status)
            if status == 200:
                ready = True
                break
            if status == 401:
                raise RuntimeError(
                    "Atlas rejected the catalog user. Add that user before the Atlas process starts. "
                    "Restarting this Atlas image does not bring the server back."
                )
        time.sleep(5)
    if not ready:
        raise RuntimeError(f"Atlas did not become ready ({last})")

    status, body = api.call("POST", "/api/atlas/v2/types/typedefs", atlas_typedefs())
    if status not in (200, 201):
        code = body.get("errorCode", "") if isinstance(body, dict) else ""
        if not str(code).startswith("ATLAS-409"):
            raise RuntimeError(f"Could not create Atlas types ({status}: {message_from(body, hidden)})")

    entities = []
    namespaces: dict[str, str] = {}
    for row in doc["tables"]:
        namespace = row["namespace"]
        ns_qn = f"namespace:{namespace}@{CLUSTER_NAME}"
        if namespace not in namespaces:
            existing = atlas_get_unique(api, "cdp_data_product", ns_qn)
            if existing is None:
                created, created_body = api.call(
                    "POST",
                    "/api/atlas/v2/entity",
                    {
                        "entity": {
                            "typeName": "cdp_data_product",
                            "status": "ACTIVE",
                            "attributes": {
                                "qualifiedName": ns_qn,
                                "name": f"namespace:{namespace}",
                                "description": f"HBase namespace {namespace} on {CLUSTER_NAME}",
                            },
                        }
                    },
                )
                if created not in (200, 201) or not isinstance(created_body, dict):
                    raise RuntimeError(
                        f"Could not create Atlas namespace {namespace} ({created}: {message_from(created_body, hidden)})"
                    )
                guid = (
                    (created_body.get("mutatedEntities") or {})
                    .get("CREATE", [{}])[0]
                    .get("guid")
                    or created_body.get("guidAssignments", {}).get("-1")
                )
                if not guid:
                    entity = atlas_get_unique(api, "cdp_data_product", ns_qn) or {}
                    guid = entity.get("guid")
            else:
                guid = existing.get("guid")
            namespaces[namespace] = guid

        table_qn = f"table:{row['name']}@{CLUSTER_NAME}"
        table_entity = atlas_get_unique(api, "cdp_data_product", table_qn)
        if table_entity is None:
            created, created_body = api.call(
                "POST",
                "/api/atlas/v2/entity",
                {
                    "entity": {
                        "typeName": "cdp_data_product",
                        "status": "ACTIVE",
                        "attributes": {
                            "qualifiedName": table_qn,
                            "name": row["name"],
                            "securityLevel": row["level"],
                            "authorizedUser": row["user"],
                            "description": (
                                f"HBase table {row['name']} classified {row['level']}. "
                                f"Accessible to {row['user']}."
                            ),
                        },
                        "classifications": [{"typeName": row["level"]}],
                    }
                },
            )
            if created not in (200, 201) or not isinstance(created_body, dict):
                raise RuntimeError(
                    f"Could not create Atlas entity for {row['name']} ({created}: {message_from(created_body, hidden)})"
                )
            table_guid = None
            created_list = (created_body.get("mutatedEntities") or {}).get("CREATE") or []
            for item in created_list:
                if item.get("typeName") == "cdp_data_product" and item.get("attributes", {}).get("name") == row["name"]:
                    table_guid = item.get("guid")
            if not table_guid and created_list:
                table_guid = created_list[-1].get("guid")
            if not table_guid:
                fetched = atlas_get_unique(api, "cdp_data_product", table_qn) or {}
                table_guid = fetched.get("guid")
        else:
            table_guid = table_entity.get("guid")

        process_qn = f"process:register:{row['name']}@{CLUSTER_NAME}"
        process = atlas_get_unique(api, "cdp_catalog_process", process_qn)
        if process is None:
            created, created_body = api.call(
                "POST",
                "/api/atlas/v2/entity",
                {
                    "entity": {
                        "typeName": "cdp_catalog_process",
                        "status": "ACTIVE",
                        "attributes": {
                            "qualifiedName": process_qn,
                            "name": f"register:{row['name']}",
                            "inputs": [{"guid": namespaces[namespace], "typeName": "cdp_data_product"}],
                            "outputs": [{"guid": table_guid, "typeName": "cdp_data_product"}],
                        },
                    }
                },
            )
            if created not in (200, 201):
                raise RuntimeError(
                    f"Could not create Atlas lineage for {row['name']} ({created}: {message_from(created_body, hidden)})"
                )
            process_guid = None
            if isinstance(created_body, dict):
                for item in (created_body.get("mutatedEntities") or {}).get("CREATE") or []:
                    if item.get("typeName") == "cdp_catalog_process":
                        process_guid = item.get("guid")
            if not process_guid:
                fetched = atlas_get_unique(api, "cdp_catalog_process", process_qn) or {}
                process_guid = fetched.get("guid")
        else:
            process_guid = process.get("guid")

        lineage_api = f"/api/atlas/v2/lineage/{table_guid}?direction=BOTH&depth=3"
        row["lineage"].update(
            {
                "input_guid": namespaces[namespace],
                "process_guid": process_guid,
                "output_guid": table_guid,
                "lineage_api": lineage_api,
            }
        )
        entities.append(
            {
                "table": row["name"],
                "classification": row["level"],
                "guid": table_guid,
                "process_guid": process_guid,
                "lineage_api": lineage_api,
                "ui": f"{ATLAS_URL}/index.html#!/detailPage/{table_guid}",
            }
        )

    doc["atlas"] = {
        "ui": ATLAS_URL,
        "classifications": list(LEVELS),
        "where": (
            f"{ATLAS_URL} → Search. Filter by classification SECRET, CUI, or UNCLASSIFIED. "
            "Open a table entity and select Lineage. The graph is namespace → register:<table> → table."
        ),
        "entities": entities,
        "note": "Classifications and lineage were created on the reduced Atlas instance.",
    }


def persist(doc: dict, doc_path: Path) -> None:
    write_json(ASSIGNMENT_PATH, doc)
    write_text(doc_path, render_assignment_doc(doc))


def main() -> int:
    parser = argparse.ArgumentParser(description="Record and apply the HBase security assignment.")
    parser.add_argument("--record-only", action="store_true", help="List tables and record the assignment, then stop.")
    parser.add_argument("--reassign", action="store_true", help="Draw a new random assignment. Default is to keep the recorded one.")
    parser.add_argument("--doc", default=str(DEFAULT_DOC_PATH), help="Assignment markdown path.")
    args = parser.parse_args()
    doc_path = Path(args.doc)
    hidden: list[str] = []

    if ASSIGNMENT_PATH.is_file() and not args.reassign:
        doc = json.loads(ASSIGNMENT_PATH.read_text(encoding="utf-8"))
        print(f"Using the assignment already recorded for {len(doc.get('tables') or [])} tables.")
        persist(doc, doc_path)
    else:
        print("Listing HBase tables on the reduced cluster.")
        tables = list_hbase_tables()
        seed = secrets.randbits(31) or 1
        rows = assign_tables(tables, seed)
        doc = base_document(rows, seed)
        user_tables = [name for name in tables if not name.startswith("hbase:")]
        if not user_tables:
            listed = ", ".join(f"`{name}`" for name in tables) or "_none_"
            doc["inventory_note"] = (
                "HBase `list` returns user tables only, and this cluster had none. "
                f"The assignment covers every existing table: {listed}."
            )
        persist(doc, doc_path)
        print(f"Recorded {len(rows)} tables at {ASSIGNMENT_PATH} before applying controls.")

    if args.record_only:
        return 0

    try:
        print("Applying Ranger roles and policies.")
        apply_ranger(doc, hidden)
        persist(doc, doc_path)
        print("Applying Atlas classifications and lineage.")
        apply_atlas(doc, hidden)
        doc.pop("error", None)
        doc["status"] = "applied"
        doc["applied_at"] = utc_now()
        persist(doc, doc_path)
        print(f"Applied assignment. status={doc['status']} tables={len(doc['tables'])}")
    except Exception as exc:  # noqa: BLE001
        doc["status"] = "apply_failed"
        doc["error"] = redact(str(exc), hidden)
        persist(doc, doc_path)
        print(f"Apply failed after the assignment was recorded: {doc['error']}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
