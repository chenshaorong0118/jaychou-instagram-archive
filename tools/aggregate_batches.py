#!/usr/bin/env python3
"""Consume write-only archive batch refs and update both public repositories."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from archive_index import (
    build_outputs,
    read_items,
    safe,
    safe_metadata,
    sha256,
    update_shards,
    validate_media_item,
    write_json,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BRANCH_RE = re.compile(
    r"^archive-batch/([0-9a-f-]{36})/([0-9a-f-]{36})$"
)
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
ALLOWED_MIME = {
    "application/json",
    "image/jpeg",
    "image/png",
    "image/webp",
    "video/mp4",
    "audio/mp4",
    "audio/mpeg",
}


class AggregateError(RuntimeError):
    pass


@dataclass(frozen=True)
class PendingBatch:
    branch: str
    batch_id: str
    index_root: Path
    media_root: Path
    payload: dict[str, Any]


def run(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise AggregateError(detail or f"command failed: {args[0]}")
    return completed


def git(
    root: Path,
    *args: str,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return run(
        [
            "git",
            "-c",
            f"safe.directory={root.resolve().as_posix()}",
            "-C",
            str(root),
            *args,
        ],
        env=env,
        check=check,
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def list_batch_branches(index_root: Path) -> list[str]:
    completed = git(
        index_root,
        "ls-remote",
        "--heads",
        "origin",
        "refs/heads/archive-batch/*",
    )
    branches: list[str] = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        _, reference = line.split(None, 1)
        branch = reference.removeprefix("refs/heads/")
        if BRANCH_RE.fullmatch(branch):
            branches.append(branch)
    return sorted(set(branches))


def clone_branch(repository: str, branch: str, destination: Path) -> None:
    run(
        [
            "git",
            "clone",
            "--quiet",
            "--depth",
            "1",
            "--single-branch",
            "--branch",
            branch,
            f"https://github.com/{repository}.git",
            str(destination),
        ]
    )


def _declared_file_set(batch: dict[str, Any]) -> set[str]:
    return {
        str(asset["payload_path"])
        for item in batch["items"]
        for asset in item["assets"]
    }


def validate_batch(
    batch: dict[str, Any],
    *,
    branch: str,
    index_payload_root: Path,
    media_payload_root: Path,
) -> None:
    batch_schema = json.loads(
        (REPOSITORY_ROOT / "schema" / "batch.schema.json").read_text(
            encoding="utf-8"
        )
    )
    item_schema = json.loads(
        (REPOSITORY_ROOT / "schema" / "item.schema.json").read_text(
            encoding="utf-8"
        )
    )
    batch_schema["$defs"]["item"]["properties"]["metadata"] = item_schema
    try:
        Draft202012Validator(
            batch_schema,
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        ).validate(batch)
    except ValidationError as error:
        location = "/".join(str(part) for part in error.absolute_path)
        raise AggregateError(
            f"batch schema invalid at {location or '<root>'}: {error.message}"
        ) from error
    match = BRANCH_RE.fullmatch(branch)
    if not match:
        raise AggregateError("invalid branch")
    client_id, batch_id = match.groups()
    if (
        batch.get("schema_version") != 1
        or batch.get("batch_id") != batch_id
        or batch.get("client_id") != client_id
        or batch.get("branch") != branch
    ):
        raise AggregateError("batch identity mismatch")
    files = list(index_payload_root.glob("batches/*/*/*.json"))
    if len(files) != 1 or files[0].stem != batch_id:
        raise AggregateError("index batch payload shape invalid")
    media_manifest = media_payload_root / "incoming" / batch_id / "manifest.json"
    if json.loads(media_manifest.read_text(encoding="utf-8")) != batch:
        raise AggregateError("media/index batch manifests differ")
    items = batch.get("items")
    if not isinstance(items, list) or not items:
        raise AggregateError("batch items missing")
    seen: set[str] = set()
    for item in items:
        pk = str(item.get("pk") or "")
        if not pk or pk in seen:
            raise AggregateError(f"duplicate/invalid PK: {pk}")
        seen.add(pk)
        path = str(item.get("path") or "")
        if not path.endswith(f"_{pk}"):
            raise AggregateError(f"item path/PK mismatch: {pk}")
        metadata = item.get("metadata")
        if not isinstance(metadata, dict) or str(metadata.get("pk")) != pk:
            raise AggregateError(f"metadata identity mismatch: {pk}")
        safe_metadata(metadata)
        for field in ("has_image", "has_video", "has_audio"):
            if not isinstance(item.get(field), bool):
                raise AggregateError(f"missing batch media flag: {pk}:{field}")
        assets = item.get("assets")
        if not isinstance(assets, list) or not assets:
            raise AggregateError(f"assets missing: {pk}")
        thumbnail_count = 0
        for asset in assets:
            payload_path = str(asset.get("payload_path") or "")
            target_path = str(asset.get("target_path") or "")
            mime = str(asset.get("mime_type") or "")
            expected_bytes = asset.get("bytes")
            expected_sha = str(asset.get("sha256") or "")
            if (
                mime not in ALLOWED_MIME
                or not isinstance(expected_bytes, int)
                or expected_bytes <= 0
                or not SHA256_RE.fullmatch(expected_sha)
                or not target_path.startswith(f"{path}/")
            ):
                raise AggregateError(f"asset declaration invalid: {pk}")
            source = safe(media_payload_root, payload_path)
            if source.stat().st_size != expected_bytes or sha256(source) != expected_sha:
                raise AggregateError(f"asset integrity mismatch: {pk}")
            if asset.get("type") == "thumbnail":
                thumbnail_count += 1
                if mime != "image/webp" or not re.match(
                    b"^RIFF....WEBP", source.read_bytes()[:12], re.DOTALL
                ):
                    raise AggregateError(f"invalid thumbnail: {pk}")
        if thumbnail_count != int(item.get("media_count") or 0):
            raise AggregateError(f"thumbnail coverage mismatch: {pk}")
    actual_files = {
        path.relative_to(media_payload_root).as_posix()
        for path in media_payload_root.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }
    expected_files = _declared_file_set(batch)
    expected_files.add(f"incoming/{batch_id}/manifest.json")
    if actual_files != expected_files:
        raise AggregateError("undeclared or missing media payload files")


def load_pending_batch(
    *,
    index_repository: str,
    media_repository: str,
    branch: str,
    temp_root: Path,
) -> PendingBatch:
    batch_id = branch.rsplit("/", 1)[-1]
    index_payload = temp_root / f"index-{batch_id}"
    media_payload = temp_root / f"media-{batch_id}"
    clone_branch(index_repository, branch, index_payload)
    clone_branch(media_repository, branch, media_payload)
    files = list(index_payload.glob("batches/*/*/*.json"))
    if len(files) != 1:
        raise AggregateError("index batch file missing/duplicate")
    batch = json.loads(files[0].read_text(encoding="utf-8"))
    validate_batch(
        batch,
        branch=branch,
        index_payload_root=index_payload,
        media_payload_root=media_payload,
    )
    return PendingBatch(
        branch=branch,
        batch_id=batch_id,
        index_root=index_payload,
        media_root=media_payload,
        payload=batch,
    )


def same_existing_item(
    item: dict[str, Any],
    existing_row: dict[str, Any],
    media_root: Path,
) -> bool:
    existing_metadata = validate_media_item(media_root, existing_row)
    if safe_metadata(item["metadata"]) != existing_metadata:
        return False
    old_hashes = sorted(
        asset["sha256"]
        for position in existing_metadata["media"]
        for asset in position["assets"]
        if asset.get("type") != "thumbnail"
    )
    new_hashes = sorted(
        asset["sha256"]
        for position in item["metadata"]["media"]
        for asset in position["assets"]
        if asset.get("type") != "thumbnail"
    )
    return old_hashes == new_hashes


def copy_batch_media(batch: PendingBatch, media_main: Path) -> int:
    copied = 0
    for item in batch.payload["items"]:
        source = batch.media_root / "incoming" / batch.batch_id / item["path"]
        target = media_main / item["path"]
        if target.exists():
            for asset in item["assets"]:
                existing = safe(media_main, asset["target_path"])
                if (
                    existing.stat().st_size != asset["bytes"]
                    or sha256(existing) != asset["sha256"]
                ):
                    raise AggregateError(
                        f"existing media conflicts: {item['pk']}"
                    )
            continue
        shutil.copytree(source, target)
        copied += len(item["assets"])
    return copied


def update_media_generated(media_root: Path, items: list[dict[str, Any]]) -> None:
    manifest_path = media_root / "manifest.jsonl"
    existing = {
        str(row["pk"]): row
        for row in (
            json.loads(line)
            for line in manifest_path.read_text(encoding="utf-8").splitlines()
            if line
        )
    }
    for item in items:
        existing.setdefault(
            str(item["pk"]),
            {
                "pk": str(item["pk"]),
                "item_type": item["item_type"],
                "published_at_taipei": item["published_at_taipei"],
                "path": item["path"],
                "media_count": int(item["media_count"]),
            },
        )
    rows = sorted(
        existing.values(),
        key=lambda row: (
            str(row["published_at_taipei"]),
            str(row["pk"]),
        ),
    )
    manifest_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
        newline="\n",
    )
    checksum_rows = []
    for path in sorted(
        (
            value
            for value in media_root.rglob("*")
            if value.is_file()
            and ".git" not in value.parts
            and value.name != "SHA256SUMS"
        ),
        key=lambda value: value.relative_to(media_root).as_posix(),
    ):
        checksum_rows.append(
            f"{sha256(path)}  {path.relative_to(media_root).as_posix()}"
        )
    media_root.joinpath("SHA256SUMS").write_text(
        "\n".join(checksum_rows) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def configure_git_identity(root: Path) -> None:
    git(root, "config", "user.name", "github-actions[bot]")
    git(
        root,
        "config",
        "user.email",
        "41898282+github-actions[bot]@users.noreply.github.com",
    )


def commit_if_changed(root: Path, message: str) -> bool:
    if not git(root, "status", "--porcelain").stdout.strip():
        return False
    git(root, "add", "--all")
    git(root, "commit", "-m", message)
    return True


def git_auth_environment(token: str, temp_root: Path) -> dict[str, str]:
    helper = temp_root / "askpass.sh"
    helper.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in *Username*) printf '%s\\n' x-access-token;; "
        "*) printf '%s\\n' \"$ARCHIVE_MEDIA_TOKEN\";; esac\n",
        encoding="utf-8",
    )
    helper.chmod(0o700)
    env = os.environ.copy()
    env["ARCHIVE_MEDIA_TOKEN"] = token
    env["GIT_ASKPASS"] = str(helper)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def clone_media_main(
    repository: str,
    destination: Path,
    token: str,
    temp_root: Path,
) -> dict[str, str]:
    env = git_auth_environment(token, temp_root)
    run(
        [
            "git",
            "clone",
            "--quiet",
            f"https://github.com/{repository}.git",
            str(destination),
        ],
        env=env,
    )
    return env


def processed_path(index_root: Path, batch: PendingBatch) -> Path:
    date = str(batch.payload["created_at_utc"])
    return (
        index_root
        / "processed"
        / date[:4]
        / date[5:7]
        / f"{batch.batch_id}.json"
    )


def rejected_path(index_root: Path, batch_id: str) -> Path:
    now = utc_now()
    return index_root / "rejected" / now[:4] / now[5:7] / f"{batch_id}.json"


def public_rejection_reason(error: str) -> str:
    value = error.casefold()
    if "duplicate" in value or "existing media conflicts" in value:
        return "content_conflict"
    if "schema" in value:
        return "schema_invalid"
    if "path" in value or "branch" in value:
        return "path_invalid"
    if any(
        marker in value
        for marker in ("asset", "thumbnail", "mime", "hash", "sha")
    ):
        return "asset_invalid"
    return "batch_invalid"


def process(args: argparse.Namespace) -> dict[str, Any]:
    index_root = Path(args.index_root).resolve()
    branches = list_batch_branches(index_root)
    if not branches:
        return {
            "pending": 0,
            "accepted": 0,
            "rejected": 0,
            "nothing_to_process": True,
        }
    media_token = os.environ.get(args.media_token_env, "").strip()
    if not media_token:
        raise AggregateError(f"missing secret: {args.media_token_env}")
    index_repository = args.index_repository
    media_repository = args.media_repository
    accepted: list[PendingBatch] = []
    rejected: list[tuple[str, str, str]] = []
    with tempfile.TemporaryDirectory(prefix="archive-aggregate-") as temp:
        temp_root = Path(temp)
        media_main = temp_root / "media-main"
        media_env = clone_media_main(
            media_repository,
            media_main,
            media_token,
            temp_root,
        )
        configure_git_identity(media_main)
        existing = {str(row["pk"]): row for row in read_items(index_root)}
        accepted_pks: dict[str, dict[str, Any]] = {}
        for branch in branches:
            batch_id = branch.rsplit("/", 1)[-1]
            try:
                batch = load_pending_batch(
                    index_repository=index_repository,
                    media_repository=media_repository,
                    branch=branch,
                    temp_root=temp_root,
                )
                if processed_path(index_root, batch).is_file():
                    accepted.append(batch)
                    continue
                for item in batch.payload["items"]:
                    pk = str(item["pk"])
                    if pk in existing:
                        if not same_existing_item(item, existing[pk], media_main):
                            raise AggregateError(f"conflicting duplicate PK: {pk}")
                    elif pk in accepted_pks and accepted_pks[pk] != item:
                        raise AggregateError(f"cross-batch duplicate conflict: {pk}")
                accepted.append(batch)
                for item in batch.payload["items"]:
                    accepted_pks.setdefault(str(item["pk"]), item)
            except Exception as error:
                rejected.append((branch, batch_id, str(error)))

        new_items: list[dict[str, Any]] = []
        for batch in accepted:
            if processed_path(index_root, batch).is_file():
                continue
            copy_batch_media(batch, media_main)
            for item in batch.payload["items"]:
                if str(item["pk"]) not in existing:
                    new_items.append(item)
        update_media_generated(media_main, new_items)
        configure_git_identity(media_main)
        media_changed = commit_if_changed(
            media_main,
            f"Aggregate {len(accepted)} archive batch(es)",
        )
        if media_changed:
            git(media_main, "push", "origin", "main", env=media_env)
        media_commit = git(media_main, "rev-parse", "HEAD").stdout.strip()
        if not re.fullmatch(r"[a-f0-9]{40}", media_commit):
            raise AggregateError("invalid media commit")

        new_rows = [
            {
                "pk": str(item["pk"]),
                "item_type": item["item_type"],
                "published_at_utc": item["published_at_utc"],
                "published_at_taipei": item["published_at_taipei"],
                "repository": media_repository,
                "media_commit": media_commit,
                "thumbnail_commit": media_commit,
                "path": item["path"],
                "media_count": int(item["media_count"]),
            }
            for item in new_items
        ]
        for batch in accepted:
            if processed_path(index_root, batch).is_file():
                continue
            write_json(
                processed_path(index_root, batch),
                {
                    "schema_version": 1,
                    "status": "processed",
                    "processed_at_utc": utc_now(),
                    "batch_id": batch.batch_id,
                    "media_commit": media_commit,
                    "item_pks": [
                        str(item["pk"]) for item in batch.payload["items"]
                    ],
                    "batch_sha256": hashlib.sha256(
                        json.dumps(
                            batch.payload,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest(),
                },
            )
        for _, batch_id, error in rejected:
            path = rejected_path(index_root, batch_id)
            if not path.exists():
                write_json(
                    path,
                    {
                        "schema_version": 1,
                        "status": "rejected",
                        "rejected_at_utc": utc_now(),
                        "batch_id": batch_id,
                        "reason": public_rejection_reason(error),
                    },
                )
        outputs = build_outputs(
            index_root,
            media_main,
            new_rows=new_rows,
            thumbnail_commit=media_commit,
        )
        update_shards(index_root, media_main, outputs)
        configure_git_identity(index_root)
        index_changed = commit_if_changed(
            index_root,
            f"Aggregate {len(accepted)} archive batch(es)",
        )
        if index_changed:
            git(index_root, "push", "origin", "main")
        for batch in accepted:
            git(
                index_root,
                "push",
                "origin",
                "--delete",
                batch.branch,
                check=False,
            )
            git(
                media_main,
                "push",
                "origin",
                "--delete",
                batch.branch,
                env=media_env,
                check=False,
            )
        result = {
            "pending": len(branches),
            "accepted": len(accepted),
            "rejected": len(rejected),
            "media_commit": media_commit,
            "items": len(outputs),
            "index_changed": index_changed,
            "media_changed": media_changed,
        }
        if rejected:
            print(json.dumps(result, ensure_ascii=False))
            raise AggregateError(f"rejected batches: {len(rejected)}")
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index-root", default=".")
    parser.add_argument(
        "--index-repository",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
    )
    parser.add_argument(
        "--media-repository",
        default="chenshaorong0118/jaychou-instagram-archive-media-0001",
    )
    parser.add_argument("--media-token-env", default="ARCHIVE_MEDIA_PAT")
    args = parser.parse_args()
    if not args.index_repository:
        raise AggregateError("index repository missing")
    print(json.dumps(process(args), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, AggregateError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        raise SystemExit(1)
