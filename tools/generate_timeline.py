#!/usr/bin/env python3
"""Generate deterministic monthly timelines from items.jsonl and pinned metadata."""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def encoded_path(value: str) -> str:
    return "/".join(urllib.parse.quote(part, safe="") for part in value.split("/"))


def raw_url(item: dict, file_path: str) -> str:
    return (
        f"https://raw.githubusercontent.com/{item['repository']}/"
        f"{item['media_commit']}/{encoded_path(file_path)}"
    )


def blob_url(item: dict, file_path: str) -> str:
    return (
        f"https://github.com/{item['repository']}/blob/"
        f"{item['media_commit']}/{encoded_path(file_path)}"
    )


def directory_url(item: dict) -> str:
    return (
        f"https://github.com/{item['repository']}/tree/"
        f"{item['media_commit']}/{encoded_path(item['path'])}"
    )


def load_metadata(item: dict, metadata_root: Path | None = None) -> dict:
    if metadata_root is not None:
        metadata = json.loads(
            metadata_root.joinpath(
                item["path"],
                "metadata.json",
            ).read_text(encoding="utf-8")
        )
    else:
        url = raw_url(item, f"{item['path']}/metadata.json")
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "jaychou-instagram-archive-timeline/1"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            metadata = json.loads(response.read().decode("utf-8"))
    if metadata.get("pk") != item.get("pk"):
        raise ValueError(f"metadata PK mismatch: {item.get('pk')}")
    return metadata


def quote(value: str) -> str:
    return "\n".join(f"> {line}" for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n"))


def image_preview(source: str, href: str, alt: str, width: int) -> str:
    safe_source = html.escape(source, quote=True)
    safe_href = html.escape(href, quote=True)
    safe_alt = html.escape(alt, quote=True)
    return "\n".join(
        [
            f'<a href="{safe_href}">',
            f'  <img src="{safe_source}" alt="{safe_alt}" width="{width}">',
            "</a>",
        ]
    )


def append_block(output: list[str], lines: list[str]) -> None:
    if output and output[-1] != "":
        output.append("")
    for index, line in enumerate(lines):
        if index > 0 and output[-1] != "":
            output.append("")
        output.append(line)
    if output and output[-1] != "":
        output.append("")


def write_text_if_changed(path: Path, content: str) -> None:
    encoded = content.encode("utf-8")
    if path.exists() and path.read_bytes() == encoded:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        delete=False,
    ) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def display_asset(item: dict, position: dict) -> list[str]:
    base = f"{item['path']}/"
    width = 360 if item["item_type"] == "story" else 720
    assets = position["assets"]
    video = next(
        (asset for asset in assets if asset.get("role") in {"playable_video", "primary_video"}),
        None,
    )
    image = next((asset for asset in assets if asset.get("role") == "image"), None)
    poster = next((asset for asset in assets if asset.get("role") == "video_poster"), None)
    if position["presentation_kind"] == "image" and image:
        source = raw_url(item, f"{base}{image['filename']}")
        label = "Story" if item["item_type"] == "story" else "Post"
        return [
            image_preview(
                source=source,
                href=source,
                alt=f"{label} media {position['media_index']}",
                width=width,
            )
        ]
    if position["presentation_kind"] == "image_with_audio" and image and video:
        image_source = raw_url(item, f"{base}{image['filename']}")
        video_page = blob_url(item, f"{base}{video['filename']}")
        direct_video = raw_url(item, f"{base}{video['filename']}")
        return [
            image_preview(
                source=image_source,
                href=video_page,
                alt="点击播放带声音版本 / Play with sound",
                width=width,
            ),
            f"[▶ 播放带声音版本 / Play with sound]({video_page}) · "
            f"[直接文件 / Direct file]({direct_video})",
        ]
    if video:
        video_page = blob_url(item, f"{base}{video['filename']}")
        direct_video = raw_url(item, f"{base}{video['filename']}")
        lines: list[str] = []
        if poster:
            poster_source = raw_url(item, f"{base}{poster['filename']}")
            lines.append(
                image_preview(
                    source=poster_source,
                    href=video_page,
                    alt="点击播放视频 / Play video",
                    width=width,
                )
            )
        lines.append(
            f"[▶ 播放视频 / Play video]({video_page}) · "
            f"[直接文件 / Direct file]({direct_video})"
        )
        return lines
    raise ValueError(
        f"timeline preview missing: {item['pk']}:{position.get('media_index')}"
    )


def render(month: str, rows: list[tuple[dict, dict]]) -> str:
    output = [
        f"# {month} 时间线 / Timeline",
        "",
        "按 Asia/Taipei 发布时间倒序排列。Posts and Stories are mixed in reverse chronological order.",
        "",
    ]
    rows = sorted(
        rows,
        key=lambda pair: (pair[0]["published_at_taipei"], pair[0]["pk"]),
        reverse=True,
    )
    for item, metadata in rows:
        label = "Post" if item["item_type"] == "post" else "Story"
        output.extend([f"## {label} · {item['published_at_taipei']}", ""])
        if metadata.get("caption"):
            output.extend(["**Caption**", "", quote(metadata["caption"]), ""])
        if metadata.get("visible_text"):
            output.extend(
                ["**画面文字 / Visible text**", "", quote(metadata["visible_text"]), ""]
            )
        music = metadata.get("music")
        if music and (music.get("title") or music.get("artist")):
            text = " — ".join(
                value for value in [music.get("title"), music.get("artist")] if value
            )
            output.extend([f"**音乐 / Music:** {text}", ""])
        shared = metadata.get("shared_post")
        if shared:
            values = []
            if shared.get("owner_username"):
                values.append(f"@{shared['owner_username']}")
            if shared.get("shortcode"):
                values.append(shared["shortcode"])
            shared_label = " · ".join(values) or "Shared Post"
            output.extend(
                [f"**转发 / Shared:** [{shared_label}]({shared['url']})", ""]
            )
        for position in metadata["media"]:
            append_block(output, display_asset(item, position))
        output.extend(
            [
                f"[归档目录 / Archive]({directory_url(item)})",
                "",
                f"PK: `{item['pk']}`",
                "",
                "---",
                "",
            ]
        )
    return "\n".join(output).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--month")
    parser.add_argument("--metadata-root")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    metadata_root = (
        Path(args.metadata_root).resolve() if args.metadata_root else None
    )
    items = [
        json.loads(line)
        for line in root.joinpath("index/items.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    months: dict[str, list[tuple[dict, dict]]] = {}
    for item in items:
        month = item["published_at_taipei"][:7]
        if args.month and month != args.month:
            continue
        metadata = load_metadata(item, metadata_root)
        months.setdefault(month, []).append((item, metadata))
    expected_files = {f"{month}.md" for month in months}
    actual_files = {path.name for path in root.joinpath("timeline").glob("*.md")}
    if args.check and not args.month and actual_files != expected_files:
        raise ValueError("timeline month files mismatch")
    root.joinpath("timeline").mkdir(parents=True, exist_ok=True)
    for month, rows in sorted(months.items()):
        expected = render(month, rows)
        target = root.joinpath("timeline", f"{month}.md")
        if args.check:
            if target.read_bytes() != expected.encode("utf-8"):
                raise ValueError(f"timeline differs: {target.name}")
        else:
            write_text_if_changed(target, expected)
    print(json.dumps({"ok": True, "months": len(months), "check": args.check}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        raise SystemExit(1)
