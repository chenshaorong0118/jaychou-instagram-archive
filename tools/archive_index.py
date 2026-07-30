"""Deterministic public index, search index, and metadata mirror generation."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

from opencc import OpenCC


COMMIT_RE = re.compile(r"^[a-f0-9]{40}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ENTRY_RE = re.compile(
    r"^(posts|stories)/\d{4}/\d{2}/\d{2}/"
    r"\d{8}T\d{6}\+0800_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
)
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
WEBP_RE = re.compile(b"^RIFF....WEBP", re.DOTALL)
SAFE_METADATA_FIELDS = {
    "schema_version",
    "pk",
    "item_type",
    "published_at_utc",
    "published_at_taipei",
    "display_timezone",
    "captured_at",
    "caption",
    "visible_text",
    "shared_post",
    "music",
    "media",
    "has_image",
    "has_video",
    "has_audio",
}
FORBIDDEN_KEYS = {
    "source_url",
    "cookie",
    "cookies",
    "headers",
    "authorization",
    "absolute_path",
    "local_dir",
    "run_id",
    "request",
    "response",
}


def fail(message: str) -> None:
    raise ValueError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe(root: Path, relative: str) -> Path:
    if (
        not relative
        or "\\" in relative
        or relative.startswith("/")
        or ".." in relative.split("/")
    ):
        fail(f"unsafe path: {relative}")
    result = (root / relative).resolve()
    if root != result and root not in result.parents:
        fail(f"path escapes root: {relative}")
    return result


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def read_items(root: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in root.joinpath("index/items.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]


def write_items(root: Path, items: Iterable[dict[str, Any]]) -> None:
    rows = sorted(
        items,
        key=lambda row: (
            str(row["published_at_utc"]),
            str(row["pk"]),
        ),
    )
    root.joinpath("index/items.jsonl").write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
        newline="\n",
    )


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key).casefold()
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    forbidden = FORBIDDEN_KEYS.intersection(_walk_keys(metadata))
    if forbidden:
        fail(f"forbidden metadata keys: {','.join(sorted(forbidden))}")
    return {
        key: metadata[key]
        for key in metadata
        if key in SAFE_METADATA_FIELDS
    }


def validate_media_item(
    media_root: Path,
    row: dict[str, Any],
) -> dict[str, Any]:
    pk = str(row.get("pk"))
    relative = str(row.get("path"))
    if not ENTRY_RE.fullmatch(relative):
        fail(f"invalid item path: {pk}")
    metadata_path = safe(media_root, f"{relative}/metadata.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if str(metadata.get("pk")) != pk or metadata.get("item_type") != row.get(
        "item_type"
    ):
        fail(f"metadata identity mismatch: {pk}")
    clean = safe_metadata(metadata)
    media = clean.get("media")
    if not isinstance(media, list) or len(media) != int(row.get("media_count") or 0):
        fail(f"media count mismatch: {pk}")
    for expected_index, position in enumerate(media, 1):
        if position.get("media_index") != expected_index:
            fail(f"media index mismatch: {pk}")
        assets = position.get("assets")
        if not isinstance(assets, list) or not assets:
            fail(f"media assets missing: {pk}")
        thumbnails = [
            asset for asset in assets if asset.get("role") == "thumbnail"
        ]
        if len(thumbnails) != 1:
            fail(f"thumbnail missing/duplicate: {pk}:{expected_index}")
        for asset in assets:
            filename = str(asset.get("filename") or "")
            expected_sha = str(asset.get("sha256") or "")
            expected_bytes = asset.get("bytes")
            if (
                "/" in filename
                or "\\" in filename
                or not SHA256_RE.fullmatch(expected_sha)
                or not isinstance(expected_bytes, int)
                or expected_bytes <= 0
            ):
                fail(f"asset metadata invalid: {pk}:{expected_index}")
            path = safe(media_root, f"{relative}/{filename}")
            if path.stat().st_size != expected_bytes or sha256(path) != expected_sha:
                fail(f"asset integrity mismatch: {pk}:{filename}")
            if asset.get("role") == "thumbnail":
                if (
                    asset.get("mime_type") != "image/webp"
                    or max(int(asset.get("width") or 0), int(asset.get("height") or 0))
                    > 640
                    or not WEBP_RE.match(path.read_bytes()[:12])
                ):
                    fail(f"invalid thumbnail: {pk}:{filename}")
    for field in ("has_image", "has_video", "has_audio"):
        if not isinstance(clean.get(field), bool):
            fail(f"missing media flag: {pk}:{field}")
    return clean


def normalize_search_text(value: str | None, converter: OpenCC) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    normalized = " ".join(normalized.split())
    return converter.convert(normalized)


def build_outputs(
    index_root: Path,
    media_root: Path,
    *,
    new_rows: Iterable[dict[str, Any]] = (),
    thumbnail_commit: str | None = None,
) -> list[dict[str, Any]]:
    existing = {str(row["pk"]): row for row in read_items(index_root)}
    for row in new_rows:
        pk = str(row["pk"])
        if pk in existing and existing[pk] != row:
            fail(f"conflicting index row: {pk}")
        existing.setdefault(pk, row)
    converter = OpenCC("t2s")
    enriched: list[dict[str, Any]] = []
    monthly: dict[str, dict[str, Any]] = {}
    search_rows: list[dict[str, Any]] = []
    for row in sorted(
        existing.values(),
        key=lambda value: (
            str(value["published_at_utc"]),
            str(value["pk"]),
        ),
    ):
        if not REPOSITORY_RE.fullmatch(str(row.get("repository"))):
            fail(f"invalid repository: {row.get('pk')}")
        if not COMMIT_RE.fullmatch(str(row.get("media_commit"))):
            fail(f"invalid media commit: {row.get('pk')}")
        resolved_thumbnail_commit = str(
            row.get("thumbnail_commit") or thumbnail_commit or ""
        )
        if not COMMIT_RE.fullmatch(resolved_thumbnail_commit):
            fail(f"invalid thumbnail commit: {row.get('pk')}")
        metadata = validate_media_item(media_root, row)
        first_position = metadata["media"][0]
        thumbnail = next(
            asset
            for asset in first_position["assets"]
            if asset["role"] == "thumbnail"
        )
        month = str(row["published_at_taipei"])[:7]
        metadata_shard = f"index/metadata/{month}.json"
        enriched_row = {
            "pk": str(row["pk"]),
            "item_type": row["item_type"],
            "published_at_utc": row["published_at_utc"],
            "published_at_taipei": row["published_at_taipei"],
            "repository": row["repository"],
            "media_commit": row["media_commit"],
            "thumbnail_commit": resolved_thumbnail_commit,
            "path": row["path"],
            "media_count": int(row["media_count"]),
            "has_image": metadata["has_image"],
            "has_video": metadata["has_video"],
            "has_audio": metadata["has_audio"],
            "thumbnail_path": f"{row['path']}/{thumbnail['filename']}",
            "metadata_shard": metadata_shard,
        }
        enriched.append(enriched_row)
        mirror = dict(metadata)
        mirror["repository"] = row["repository"]
        mirror["media_commit"] = row["media_commit"]
        mirror["thumbnail_commit"] = resolved_thumbnail_commit
        mirror["path"] = row["path"]
        monthly.setdefault(month, {})[str(row["pk"])] = mirror
        search_rows.append(
            {
                "pk": str(row["pk"]),
                "published_at_taipei": row["published_at_taipei"],
                "year_month": month,
                "item_type": row["item_type"],
                "caption": metadata.get("caption"),
                "media_count": int(row["media_count"]),
                "has_image": metadata["has_image"],
                "has_video": metadata["has_video"],
                "has_audio": metadata["has_audio"],
                "search_text_simplified": normalize_search_text(
                    "\n".join(
                        value
                        for value in (
                            metadata.get("caption"),
                            metadata.get("visible_text"),
                            str(row["pk"]),
                        )
                        if isinstance(value, str) and value
                    ),
                    converter,
                ),
            }
        )
    write_items(index_root, enriched)
    metadata_root = index_root / "index" / "metadata"
    metadata_root.mkdir(parents=True, exist_ok=True)
    expected_metadata = {f"{month}.json" for month in monthly}
    for stale in metadata_root.glob("*.json"):
        if stale.name not in expected_metadata:
            stale.unlink()
    for month, items in sorted(monthly.items()):
        write_json(
            metadata_root / f"{month}.json",
            {
                "schema_version": 1,
                "year_month": month,
                "items": items,
            },
        )
    write_json(
        index_root / "index" / "search-items.json",
        {
            "schema_version": 1,
            "items": search_rows,
        },
    )
    return enriched


def update_shards(index_root: Path, media_root: Path, items: list[dict[str, Any]]) -> None:
    shards_path = index_root / "index" / "shards.json"
    shards = json.loads(shards_path.read_text(encoding="utf-8"))
    media_bytes = sum(
        path.stat().st_size
        for path in media_root.rglob("*")
        if path.is_file() and ".git" not in path.parts
    )
    for shard in shards:
        rows = [
            item for item in items if item["repository"] == shard["repository"]
        ]
        if not rows:
            continue
        timestamps = [str(row["published_at_taipei"]) for row in rows]
        shard["item_count"] = len(rows)
        shard["media_bytes"] = media_bytes
        shard["first_published_at"] = min(timestamps)
        shard["last_published_at"] = max(timestamps)
    write_json(shards_path, shards)
