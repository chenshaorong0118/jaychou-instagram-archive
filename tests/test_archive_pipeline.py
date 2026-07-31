from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "tools"))

from aggregate_batches import AggregateError, validate_batch  # noqa: E402
from archive_index import build_outputs, normalize_search_text  # noqa: E402
from opencc import OpenCC  # noqa: E402


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, payload: object) -> bytes:
    data = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


class BatchFixture:
    def __init__(
        self,
        root: Path,
        *,
        pk: str = "1234567890123456789",
    ) -> None:
        self.root = root
        self.index_root = root / "index-payload"
        self.media_root = root / "media-payload"
        self.client_id = str(uuid.uuid4())
        self.batch_id = str(uuid.uuid4())
        self.branch = f"archive-batch/{self.client_id}/{self.batch_id}"
        self.pk = pk
        self.item_path = (
            "posts/2026/07/30/"
            f"20260730T120000+0800_{self.pk}"
        )
        self.image = b"\xff\xd8\xff\xe0archive-fixture"
        self.webp = b"RIFF\x08\x00\x00\x00WEBPVP8 "
        self.metadata = {
            "schema_version": 2,
            "pk": self.pk,
            "item_type": "post",
            "published_at_utc": "2026-07-30T04:00:00Z",
            "published_at_taipei": "2026-07-30T12:00:00+08:00",
            "caption": "繁體音樂",
            "text": "週杰倫",
            "shared_post": None,
            "music": None,
            "has_image": True,
            "has_video": False,
            "has_audio": False,
            "media": [
                {
                    "index": 1,
                    "kind": "image",
                    "assets": [
                        {
                            "type": "image",
                            "filename": "01-image.jpg",
                            "mime_type": "image/jpeg",
                            "width": 100,
                            "height": 50,
                            "bytes": len(self.image),
                            "sha256": digest(self.image),
                        },
                        {
                            "type": "thumbnail",
                            "filename": "01-thumbnail.webp",
                            "mime_type": "image/webp",
                            "width": 100,
                            "height": 50,
                            "bytes": len(self.webp),
                            "sha256": digest(self.webp),
                        },
                    ],
                }
            ],
        }
        media_item = (
            self.media_root / "incoming" / self.batch_id / self.item_path
        )
        media_item.mkdir(parents=True)
        (media_item / "01-image.jpg").write_bytes(self.image)
        (media_item / "01-thumbnail.webp").write_bytes(self.webp)
        metadata_data = write_json(media_item / "metadata.json", self.metadata)
        assets = [
            self.asset(
                "image",
                "01-image.jpg",
                "image/jpeg",
                self.image,
                width=100,
                height=50,
            ),
            self.asset(
                "thumbnail",
                "01-thumbnail.webp",
                "image/webp",
                self.webp,
                width=100,
                height=50,
            ),
            self.asset(
                "metadata",
                "metadata.json",
                "application/json",
                metadata_data,
            ),
        ]
        self.batch = {
            "schema_version": 1,
            "batch_id": self.batch_id,
            "client_id": self.client_id,
            "created_at_utc": "2026-07-30T04:02:00Z",
            "index_repository": (
                "chenshaorong0118/jaychou-instagram-archive"
            ),
            "media_repository": (
                "chenshaorong0118/"
                "jaychou-instagram-archive-media-0001"
            ),
            "branch": self.branch,
            "items": [
                {
                    "pk": self.pk,
                    "item_type": "post",
                    "published_at_utc": "2026-07-30T04:00:00Z",
                    "published_at_taipei": "2026-07-30T12:00:00+08:00",
                    "path": self.item_path,
                    "media_count": 1,
                    "has_image": True,
                    "has_video": False,
                    "has_audio": False,
                    "metadata": self.metadata,
                    "assets": assets,
                }
            ],
        }
        write_json(
            self.index_root
            / "batches"
            / "2026"
            / "07"
            / f"{self.batch_id}.json",
            self.batch,
        )
        write_json(
            self.media_root
            / "incoming"
            / self.batch_id
            / "manifest.json",
            self.batch,
        )

    def asset(
        self,
        asset_type: str,
        filename: str,
        mime_type: str,
        data: bytes,
        *,
        width: int | None = None,
        height: int | None = None,
    ) -> dict[str, object]:
        row: dict[str, object] = {
            "type": asset_type,
            "payload_path": (
                f"incoming/{self.batch_id}/{self.item_path}/{filename}"
            ),
            "target_path": f"{self.item_path}/{filename}",
            "mime_type": mime_type,
            "bytes": len(data),
            "sha256": digest(data),
        }
        if width is not None:
            row["width"] = width
        if height is not None:
            row["height"] = height
        return row

    def rewrite_manifests(self) -> None:
        write_json(
            self.index_root
            / "batches"
            / "2026"
            / "07"
            / f"{self.batch_id}.json",
            self.batch,
        )
        write_json(
            self.media_root
            / "incoming"
            / self.batch_id
            / "manifest.json",
            self.batch,
        )

    def install_media_main(self, destination: Path) -> None:
        source = (
            self.media_root / "incoming" / self.batch_id / self.item_path
        )
        target = destination / self.item_path
        target.mkdir(parents=True)
        for path in source.iterdir():
            if path.is_file():
                target.joinpath(path.name).write_bytes(path.read_bytes())


class BatchValidationTests(unittest.TestCase):
    def validate(self, fixture: BatchFixture) -> None:
        validate_batch(
            fixture.batch,
            branch=fixture.branch,
            index_payload_root=fixture.index_root,
            media_payload_root=fixture.media_root,
        )

    def test_has_audio_false_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = BatchFixture(Path(temporary))
            self.validate(fixture)

    def test_restricted_legacy_pk_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = BatchFixture(
                Path(temporary),
                pk="chrome_story_18438637231193087",
            )
            self.validate(fixture)

    def test_wrong_sha_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = BatchFixture(Path(temporary))
            fixture.batch["items"][0]["assets"][0]["sha256"] = "0" * 64
            fixture.rewrite_manifests()
            with self.assertRaisesRegex(
                AggregateError, "asset integrity mismatch"
            ):
                self.validate(fixture)

    def test_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = BatchFixture(Path(temporary))
            fixture.batch["items"][0]["assets"][0][
                "payload_path"
            ] = "../outside.jpg"
            fixture.rewrite_manifests()
            with self.assertRaisesRegex(
                AggregateError, "batch schema invalid"
            ):
                self.validate(fixture)

    def test_missing_thumbnail_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = BatchFixture(Path(temporary))
            item = fixture.batch["items"][0]
            item["assets"] = [
                asset
                for asset in item["assets"]
                if asset["type"] != "thumbnail"
            ]
            thumb = (
                fixture.media_root
                / "incoming"
                / fixture.batch_id
                / fixture.item_path
                / "01-thumbnail.webp"
            )
            thumb.unlink()
            fixture.rewrite_manifests()
            with self.assertRaisesRegex(
                AggregateError, "thumbnail coverage mismatch"
            ):
                self.validate(fixture)

    def test_collection_provenance_fields_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = BatchFixture(Path(temporary))
            fixture.metadata["captured_at"] = "2026-07-30T04:01:00Z"
            fixture.metadata["media"][0]["assets"][0]["origin"] = "instagram"
            fixture.rewrite_manifests()
            with self.assertRaisesRegex(AggregateError, "batch schema invalid"):
                self.validate(fixture)

    def test_ten_independent_batches_have_unique_refs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            branches: set[str] = set()
            batches: set[str] = set()
            for index in range(10):
                fixture = BatchFixture(root / str(index))
                self.validate(fixture)
                branches.add(fixture.branch)
                batches.add(fixture.batch_id)
            self.assertEqual(10, len(branches))
            self.assertEqual(10, len(batches))


class DeterministicIndexTests(unittest.TestCase):
    def test_rebuild_is_byte_identical_and_opencc_is_t2s(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = BatchFixture(root / "fixture")
            index_root = root / "index-main"
            media_root = root / "media-main"
            (index_root / "index").mkdir(parents=True)
            fixture.install_media_main(media_root)
            commit = "a" * 40
            base_row = {
                "pk": fixture.pk,
                "item_type": "post",
                "published_at_utc": "2026-07-30T04:00:00Z",
                "published_at_taipei": "2026-07-30T12:00:00+08:00",
                "repository": (
                    "chenshaorong0118/"
                    "jaychou-instagram-archive-media-0001"
                ),
                "media_commit": commit,
                "thumbnail_commit": commit,
                "path": fixture.item_path,
                "media_count": 1,
            }
            (index_root / "index" / "items.jsonl").write_text(
                json.dumps(base_row, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            build_outputs(index_root, media_root)
            paths = [
                index_root / "index" / "items.jsonl",
                index_root / "index" / "search-items.json",
                index_root / "index" / "metadata" / "2026-07.json",
            ]
            first = [path.read_bytes() for path in paths]
            build_outputs(index_root, media_root)
            self.assertEqual(first, [path.read_bytes() for path in paths])
            search = json.loads(paths[1].read_text(encoding="utf-8"))
            metadata = json.loads(paths[2].read_text(encoding="utf-8"))
            public_item = metadata["items"][fixture.pk]
            self.assertEqual(2, public_item["schema_version"])
            self.assertEqual("週杰倫", public_item["text"])
            self.assertNotIn("captured_at", public_item)
            self.assertNotIn("origin", public_item["media"][0]["assets"][0])
            simplified = search["items"][0]["search_text_simplified"]
            self.assertIn("繁体音乐", simplified)
            self.assertIn("周杰伦", simplified)
            self.assertEqual(
                "繁体音乐",
                normalize_search_text("繁體音樂", OpenCC("t2s")),
            )

    def test_conflicting_existing_pk_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "index").mkdir(parents=True)
            existing = {
                "pk": "1",
                "published_at_utc": "2026-07-30T04:00:00Z",
            }
            (root / "index" / "items.jsonl").write_text(
                json.dumps(existing) + "\n",
                encoding="utf-8",
            )
            conflict = copy.deepcopy(existing)
            conflict["published_at_utc"] = "2026-07-30T04:00:01Z"
            with self.assertRaisesRegex(ValueError, "conflicting index row"):
                build_outputs(
                    root,
                    root / "unused-media",
                    new_rows=[conflict],
                )


if __name__ == "__main__":
    unittest.main()
