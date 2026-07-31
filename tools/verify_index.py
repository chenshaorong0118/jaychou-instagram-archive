#!/usr/bin/env python3
"""Verify deterministic public indexes without accessing raw media metadata."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from opencc import OpenCC

from archive_index import normalize_search_text


COMMIT_RE = re.compile(r"^[a-f0-9]{40}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
PATH_RE = re.compile(
    r"^(posts|stories)/\d{4}/\d{2}/\d{2}/"
    r"\d{8}T\d{6}\+0800_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
)
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
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
    "captured_at",
    "display_timezone",
    "visible_text",
    "origin",
    "derived_from",
}


def fail(message: str) -> None:
    raise ValueError(message)


def read_items(root: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in root.joinpath("index/items.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]


def verify_items(items: list[dict[str, Any]]) -> None:
    if len({str(item.get("pk")) for item in items}) != len(items):
        fail("duplicate PK")
    keys = [
        (str(item.get("published_at_utc")), str(item.get("pk")))
        for item in items
    ]
    if keys != sorted(keys):
        fail("items.jsonl is not deterministically sorted")
    for item in items:
        pk = str(item.get("pk"))
        if item.get("item_type") not in {"post", "story"}:
            fail(f"invalid item_type: {pk}")
        if not REPOSITORY_RE.fullmatch(str(item.get("repository"))):
            fail(f"invalid repository: {pk}")
        if not COMMIT_RE.fullmatch(str(item.get("media_commit"))):
            fail(f"invalid media commit: {pk}")
        if not COMMIT_RE.fullmatch(str(item.get("thumbnail_commit"))):
            fail(f"invalid thumbnail commit: {pk}")
        if not PATH_RE.fullmatch(str(item.get("path"))):
            fail(f"invalid media path: {pk}")
        if not str(item.get("thumbnail_path", "")).endswith(".webp"):
            fail(f"thumbnail path missing: {pk}")
        if item.get("metadata_shard") != (
            f"index/metadata/{str(item.get('published_at_taipei'))[:7]}.json"
        ):
            fail(f"metadata shard mismatch: {pk}")
        for field in ("has_image", "has_video", "has_audio"):
            if not isinstance(item.get(field), bool):
                fail(f"missing media flag: {pk}:{field}")


def _walk_keys(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key).casefold()
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def verify_metadata(root: Path, items: list[dict[str, Any]]) -> dict[str, dict]:
    expected_months = sorted(
        {str(item["published_at_taipei"])[:7] for item in items}
    )
    actual_files = sorted(
        path.name for path in root.joinpath("index/metadata").glob("*.json")
    )
    if actual_files != [f"{month}.json" for month in expected_months]:
        fail("metadata shard file set mismatch")
    by_pk: dict[str, dict] = {}
    expected_pks = {str(item["pk"]) for item in items}
    for month in expected_months:
        payload = json.loads(
            root.joinpath("index/metadata", f"{month}.json").read_text(
                encoding="utf-8"
            )
        )
        if payload.get("schema_version") != 2 or payload.get("year_month") != month:
            fail(f"metadata shard header mismatch: {month}")
        rows = payload.get("items")
        if not isinstance(rows, dict):
            fail(f"metadata shard items invalid: {month}")
        for pk, metadata in rows.items():
            if pk in by_pk or str(metadata.get("pk")) != pk:
                fail(f"metadata PK duplicate/mismatch: {pk}")
            forbidden = FORBIDDEN_KEYS.intersection(_walk_keys(metadata))
            if forbidden:
                fail(f"forbidden metadata key: {pk}:{sorted(forbidden)[0]}")
            if str(metadata.get("published_at_taipei", ""))[:7] != month:
                fail(f"metadata month mismatch: {pk}")
            if metadata.get("schema_version") != 2:
                fail(f"metadata schema mismatch: {pk}")
            if "text" not in metadata:
                fail(f"metadata text field missing: {pk}")
            for field in ("has_image", "has_video", "has_audio"):
                if not isinstance(metadata.get(field), bool):
                    fail(f"metadata media flag missing: {pk}:{field}")
            media = metadata.get("media")
            if not isinstance(media, list) or not media:
                fail(f"metadata media missing: {pk}")
            for expected_index, position in enumerate(media, 1):
                if position.get("index") != expected_index:
                    fail(f"metadata media index mismatch: {pk}")
                if position.get("kind") not in {
                    "image",
                    "video",
                    "image_with_audio",
                }:
                    fail(f"metadata media kind invalid: {pk}")
                assets = position.get("assets")
                if not isinstance(assets, list) or not assets:
                    fail(f"metadata assets missing: {pk}")
                if (
                    len(
                        [
                            asset
                            for asset in assets
                            if asset.get("type") == "thumbnail"
                        ]
                    )
                    != 1
                ):
                    fail(f"metadata thumbnail invalid: {pk}")
            by_pk[pk] = metadata
    if set(by_pk) != expected_pks:
        fail("metadata PK coverage mismatch")
    return by_pk


def verify_search(
    root: Path,
    items: list[dict[str, Any]],
    metadata: dict[str, dict],
) -> None:
    payload = json.loads(
        root.joinpath("index/search-items.json").read_text(encoding="utf-8")
    )
    if payload.get("schema_version") != 1 or not isinstance(
        payload.get("items"), list
    ):
        fail("search index header invalid")
    rows = payload["items"]
    if [str(row.get("pk")) for row in rows] != [str(item["pk"]) for item in items]:
        fail("search item order/coverage mismatch")
    converter = OpenCC("t2s")
    for item, row in zip(items, rows, strict=True):
        pk = str(item["pk"])
        source = metadata[pk]
        expected_text = normalize_search_text(
            "\n".join(
                value
                for value in (
                    source.get("caption"),
                    source.get("text"),
                    pk,
                )
                if isinstance(value, str) and value
            ),
            converter,
        )
        expected = {
            "pk": pk,
            "published_at_taipei": item["published_at_taipei"],
            "year_month": str(item["published_at_taipei"])[:7],
            "item_type": item["item_type"],
            "caption": source.get("caption"),
            "media_count": item["media_count"],
            "has_image": item["has_image"],
            "has_video": item["has_video"],
            "has_audio": item["has_audio"],
            "search_text_simplified": expected_text,
        }
        if row != expected:
            fail(f"search row mismatch: {pk}")


def verify_shards(root: Path, item_count: int) -> None:
    shards = json.loads(root.joinpath("index/shards.json").read_text(encoding="utf-8"))
    if not isinstance(shards, list) or not shards:
        fail("shards.json must be a non-empty array")
    if sum(int(shard.get("item_count") or 0) for shard in shards) != item_count:
        fail("shard item count mismatch")


def verify_receipts(root: Path) -> None:
    expected_keys = {
        "processed": {
            "schema_version",
            "status",
            "processed_at_utc",
            "batch_id",
            "media_commit",
            "item_pks",
            "batch_sha256",
        },
        "rejected": {
            "schema_version",
            "status",
            "rejected_at_utc",
            "batch_id",
            "reason",
        },
    }
    for status, directory in (("processed", "processed"), ("rejected", "rejected")):
        for path in root.joinpath(directory).glob("*/*/*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (
                payload.get("schema_version") != 1
                or payload.get("status") != status
                or payload.get("batch_id") != path.stem
                or not UUID_RE.fullmatch(path.stem)
            ):
                fail(f"invalid {status} receipt: {path}")
            if set(payload) != expected_keys[status]:
                fail(f"non-minimal {status} receipt: {path}")


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    items = read_items(root)
    verify_items(items)
    metadata = verify_metadata(root, items)
    verify_search(root, items, metadata)
    verify_shards(root, len(items))
    verify_receipts(root)
    print(
        json.dumps(
            {
                "ok": True,
                "items": len(items),
                "metadata_shards": len(
                    list(root.joinpath("index/metadata").glob("*.json"))
                ),
                "search_items": len(items),
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        raise SystemExit(1)
