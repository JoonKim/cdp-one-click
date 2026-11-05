"""Resolve a tile URL or a local COPC/LAZ path to a file PDAL can open.

A failed HTTP response raises. An empty body raises. Nothing here invents a
successful download.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

USER_AGENT = "lidar-catalog/0.1"


def materialize_source(source: str, download_dir: Path | None) -> tuple[Path, str]:
    """Return ``(local_file, catalog_file_path)``.

    ``catalog_file_path`` is the URL or the resolved local path. A temporary
    download path is not the catalog path. Pass ``--object-path`` at ingest
    time to record an Ozone or S3 URI instead.
    """
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        if not parsed.netloc:
            raise ValueError(f"invalid tile URL: {source}")
        if download_dir is None:
            raise ValueError("download_dir is required when source is a URL")
        name = Path(unquote(parsed.path)).name
        if not name or name in {".", ".."}:
            raise ValueError(f"tile URL has no file name: {source}")
        destination = download_dir / name
        download_tile(source, destination)
        return destination, source

    if parsed.scheme == "file":
        path = Path(unquote(parsed.path))
    elif parsed.scheme:
        raise ValueError(
            "source must be a local COPC/LAZ path or an http(s) URL. "
            "Record an Ozone or S3 URI with --object-path."
        )
    else:
        path = Path(source)

    if not path.is_file():
        raise FileNotFoundError(f"tile not found: {source}")
    return path, str(path.resolve())


def download_tile(url: str, destination: Path) -> None:
    """Stream ``url`` to ``destination``. Raise on HTTP errors and empty bodies."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".partial")
    try:
        with requests.get(
            url,
            stream=True,
            timeout=(30, 600),
            headers={"User-Agent": USER_AGENT},
        ) as response:
            response.raise_for_status()
            with partial.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        if not partial.is_file() or partial.stat().st_size == 0:
            raise ValueError(f"download was empty: {url}")
        partial.replace(destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def object_name(file_path: str) -> str:
    """Object name for ``file_name``, from a local path or a storage URI."""
    parsed = urlparse(file_path)
    raw = unquote(parsed.path) if parsed.scheme else file_path
    name = Path(raw).name
    if not name or name in {".", ".."}:
        raise ValueError(f"file_path has no object name: {file_path}")
    return name
