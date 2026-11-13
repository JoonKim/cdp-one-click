#!/usr/bin/env python3
"""Serve the HBase data-product catalog.

The server reads the recorded assignment and the files under static/.
It does not proxy visitor-chosen URLs and it does not read credentials.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
ASSIGNMENT = ROOT / "assignment.json"
HOST = os.environ.get("CATALOG_HOST", "127.0.0.1")
PORT = int(os.environ.get("CATALOG_PORT", "8765"))

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}


def static_file(url_path: str) -> Path | None:
    relative = url_path.split("?", 1)[0].lstrip("/")
    if relative in ("", "index.html"):
        relative = "index.html"
    if relative.startswith(".") or "/" in relative or "\\" in relative:
        return None
    candidate = (STATIC / relative).resolve()
    if candidate.parent != STATIC.resolve():
        return None
    if candidate.is_file():
        return candidate
    return None


class CatalogHandler(BaseHTTPRequestHandler):
    server_version = "HBaseCatalog/1.0"

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/api/catalog":
            self.send_catalog()
            return
        target = static_file(path)
        if target is None:
            self.send_error(404, "Not found")
            return
        payload = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def send_catalog(self) -> None:
        if not ASSIGNMENT.is_file():
            body = json.dumps(
                {"error": "The security assignment has not been recorded yet."}
            ).encode("utf-8")
            self.send_response(404)
        else:
            body = ASSIGNMENT.read_bytes()
            self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        sys_stderr = __import__("sys").stderr
        sys_stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), CatalogHandler)
    print(f"HBase data catalog at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
