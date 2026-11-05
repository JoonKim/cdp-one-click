"""Tile acquisition. HTTP is mocked; a failed response does not leave a file."""

from __future__ import annotations

from pathlib import Path

import pytest
import requests

from lidar_catalog.acquire import download_tile, materialize_source, object_name


class _Response:
    def __init__(self, body: bytes = b"laz", status: int = 200) -> None:
        self.body = body
        self.status = status

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status} for tile")

    def iter_content(self, chunk_size: int = 1024) -> object:
        del chunk_size
        yield self.body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def test_local_path(tmp_path: Path) -> None:
    tile = tmp_path / "tile.copc.laz"
    tile.write_bytes(b"laz")
    local, catalog_path = materialize_source(str(tile), None)
    assert local == tile
    assert catalog_path == str(tile.resolve())


def test_missing_local_path(tmp_path: Path) -> None:
    missing = tmp_path / "missing.laz"
    with pytest.raises(FileNotFoundError):
        materialize_source(str(missing), None)


def test_url_download(monkeypatch, tmp_path: Path) -> None:
    def fake_get(url: str, **kwargs: object) -> _Response:
        assert url == "https://example.com/lidar/tile.copc.laz?token=1"
        assert kwargs["stream"] is True
        return _Response(b"copc-bytes")

    monkeypatch.setattr("lidar_catalog.acquire.requests.get", fake_get)
    local, catalog_path = materialize_source(
        "https://example.com/lidar/tile.copc.laz?token=1",
        tmp_path,
    )
    assert local == tmp_path / "tile.copc.laz"
    assert local.read_bytes() == b"copc-bytes"
    assert catalog_path == "https://example.com/lidar/tile.copc.laz?token=1"


def test_http_error_does_not_leave_a_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "lidar_catalog.acquire.requests.get",
        lambda *args, **kwargs: _Response(status=404),
    )
    with pytest.raises(requests.HTTPError):
        download_tile("https://example.com/missing.laz", tmp_path / "missing.laz")
    assert list(tmp_path.iterdir()) == []


def test_empty_download_raises(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "lidar_catalog.acquire.requests.get",
        lambda *args, **kwargs: _Response(body=b""),
    )
    with pytest.raises(ValueError, match="empty"):
        download_tile("https://example.com/empty.laz", tmp_path / "empty.laz")
    assert list(tmp_path.iterdir()) == []


def test_object_storage_uri_is_not_a_source() -> None:
    with pytest.raises(ValueError, match="object-path"):
        materialize_source("s3://bucket/tile.copc.laz", None)


def test_object_name_from_storage_uri() -> None:
    assert object_name("ofs://ozone/bucket/lidar/tile.copc.laz") == "tile.copc.laz"
