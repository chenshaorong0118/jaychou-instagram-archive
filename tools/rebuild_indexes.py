#!/usr/bin/env python3
"""Rebuild deterministic index outputs from local repository checkouts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from archive_index import build_outputs, update_shards


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index-root", default=".")
    parser.add_argument("--media-root", required=True)
    parser.add_argument("--thumbnail-commit", required=True)
    args = parser.parse_args()
    index_root = Path(args.index_root).resolve()
    media_root = Path(args.media_root).resolve()
    items = build_outputs(
        index_root,
        media_root,
        thumbnail_commit=args.thumbnail_commit,
    )
    update_shards(index_root, media_root, items)
    print(json.dumps({"ok": True, "items": len(items)}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        raise SystemExit(1)
