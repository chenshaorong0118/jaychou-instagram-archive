#!/usr/bin/env python3
"""Verify the public cross-repository index without third-party packages."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


COMMIT_RE = re.compile(r"^[a-f0-9]{40}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
PATH_RE = re.compile(
    r"^(posts|stories)/\d{4}/\d{2}/\d{2}/\d{8}T\d{6}\+0800_\d+$"
)


def fail(message: str) -> None:
    raise ValueError(message)


def read_items(root: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in root.joinpath("index/items.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]


def verify_items(items: list[dict]) -> None:
    if len({item.get("pk") for item in items}) != len(items):
        fail("duplicate PK")
    for item in items:
        if item.get("item_type") not in {"post", "story"}:
            fail(f"invalid item_type: {item.get('pk')}")
        if not REPOSITORY_RE.fullmatch(str(item.get("repository"))):
            fail(f"invalid repository: {item.get('pk')}")
        if not COMMIT_RE.fullmatch(str(item.get("media_commit"))):
            fail(f"invalid media commit: {item.get('pk')}")
        if not PATH_RE.fullmatch(str(item.get("path"))):
            fail(f"invalid media path: {item.get('pk')}")
        if "source_url" in item:
            fail(f"source_url must not be public: {item.get('pk')}")


def verify_shards(root: Path) -> list[dict]:
    shards = json.loads(root.joinpath("index/shards.json").read_text(encoding="utf-8"))
    if not isinstance(shards, list):
        fail("shards.json must be an array")
    ids: set[str] = set()
    for shard in shards:
        shard_id = shard.get("id")
        if not re.fullmatch(r"media-\d{4}", str(shard_id)) or shard_id in ids:
            fail(f"invalid/duplicate shard id: {shard_id}")
        ids.add(shard_id)
        if not REPOSITORY_RE.fullmatch(str(shard.get("repository"))):
            fail(f"invalid shard repository: {shard_id}")
        if shard.get("sealed") and not COMMIT_RE.fullmatch(str(shard.get("sealed_commit"))):
            fail(f"sealed commit missing: {shard_id}")
        if not shard.get("sealed") and shard.get("sealed_commit") is not None:
            fail(f"active shard has sealed commit: {shard_id}")
    return shards


def verify_timelines(root: Path, items: list[dict]) -> int:
    months: dict[str, list[dict]] = {}
    for item in items:
        months.setdefault(item["published_at_taipei"][:7], []).append(item)
    files = sorted(path.name for path in root.joinpath("timeline").glob("*.md"))
    expected_files = [f"{month}.md" for month in sorted(months)]
    if files != expected_files:
        fail("timeline month files mismatch")
    mutable_raw = re.compile(r"raw\.githubusercontent\.com/[^/\s]+/[^/\s]+/(main|master)/")
    mutable_page = re.compile(r"github\.com/[^/\s]+/[^/\s]+/(blob|tree)/(main|master)/")
    all_pks = {item["pk"] for item in items}
    image_block = re.compile(
        r'(?m)^<a href="[^"]+">\n'
        r'  <img src="[^"]+" alt="[^"]+" width="(360|720)">\n'
        r"</a>$"
    )
    for filename in files:
        month = filename[:7]
        text = root.joinpath("timeline", filename).read_text(encoding="utf-8")
        if mutable_raw.search(text) or mutable_page.search(text):
            fail(f"mutable branch URL: {filename}")
        expected = sorted(
            months[month],
            key=lambda item: (item["published_at_taipei"], item["pk"]),
            reverse=True,
        )
        headings = re.findall(r"^## (?:Post|Story) · (.+)$", text, re.MULTILINE)
        if headings != [item["published_at_taipei"] for item in expected]:
            fail(f"timeline order mismatch: {filename}")
        for item in expected:
            if text.count(f"PK: `{item['pk']}`") != 1:
                fail(f"timeline PK mismatch: {filename}:{item['pk']}")
            if item["media_commit"] not in text:
                fail(f"timeline commit missing: {filename}:{item['pk']}")
        for found in re.findall(r"PK: `(\d+)`", text):
            if found not in all_pks:
                fail(f"unknown timeline PK: {filename}:{found}")
        for match in image_block.finditer(text):
            before = text[: match.start()]
            after = text[match.end() :]
            if not before.endswith("\n\n") or not after.startswith("\n\n"):
                fail(f"HTML image block spacing invalid: {filename}")
        if text.count("<img ") != len(image_block.findall(text)):
            fail(f"HTML image block invalid: {filename}")
        for item in expected:
            section_start = text.index(
                f"## {'Post' if item['item_type'] == 'post' else 'Story'} · "
                f"{item['published_at_taipei']}"
            )
            section_end = text.find("\n---\n", section_start)
            section = text[section_start : section_end if section_end >= 0 else None]
            expected_width = "720" if item["item_type"] == "post" else "360"
            for width in re.findall(r'<img [^>]* width="(\d+)"', section):
                if width != expected_width:
                    fail(f"timeline image width mismatch: {filename}:{item['pk']}")
    return len(files)


def verify_readme(root: Path, items: list[dict]) -> None:
    readme = root.joinpath("README.md").read_text(encoding="utf-8")
    months = sorted({item["published_at_taipei"][:7] for item in items})
    for month in months:
        if f"timeline/{month}.md" not in readme:
            fail(f"README month missing: {month}")


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    items = read_items(root)
    verify_items(items)
    shards = verify_shards(root)
    timelines = verify_timelines(root, items)
    verify_readme(root, items)
    print(
        json.dumps(
            {"ok": True, "items": len(items), "shards": len(shards), "timelines": timelines}
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        raise SystemExit(1)
