"""Publication tests using an in-memory S3 client."""

import base64
import hashlib
import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
from botocore.exceptions import ClientError

from scripts.generate_batches import generate_batches
from src.s3_pipeline import process_batch


ROOT = Path(__file__).resolve().parents[1]


def s3_error(status, code):
    return ClientError(
        {
            "Error": {
                "Code": code,
                "Message": code,
            },
            "ResponseMetadata": {
                "HTTPStatusCode": status,
            },
        },
        "S3Operation",
    )


class MemoryS3:
    def __init__(self):
        self.objects = {}
        self.writes = []
        self.fail_on_item_parquet = False
        self.competing_commit = False

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise s3_error(404, "NoSuchKey")

        contents = self.objects[(Bucket, Key)]

        return {
            "ContentLength": len(contents),
            "Body": io.BytesIO(contents),
        }

    def put_object(self, **kwargs):
        bucket = kwargs["Bucket"]
        key = kwargs["Key"]
        contents = kwargs["Body"]

        if (
            self.fail_on_item_parquet
            and "/order_items/" in key
        ):
            raise RuntimeError(
                "Simulated object upload failure"
            )

        if (
            self.competing_commit
            and key.startswith("manifests/")
        ):
            self.objects[(bucket, key)] = contents
            raise s3_error(412, "PreconditionFailed")

        if (
            kwargs.get("IfNoneMatch") == "*"
            and (bucket, key) in self.objects
        ):
            raise s3_error(412, "PreconditionFailed")

        expected = base64.b64encode(
            hashlib.sha256(contents).digest()
        ).decode("ascii")

        if kwargs["ChecksumSHA256"] != expected:
            raise s3_error(400, "BadDigest")

        self.objects[(bucket, key)] = contents
        self.writes.append((bucket, key))

        return {}


class TestS3Pipeline(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

        self.workspace = Path(self.temporary.name)
        self.s3 = MemoryS3()

        self.buckets = {
            "raw": "test-raw",
            "curated": "test-curated",
            "quarantine": "test-quarantine",
        }

        self.batch_id = "olist-2018-01-01"

        with redirect_stdout(io.StringIO()):
            generate_batches(
                ROOT / "data" / "sample",
                self.workspace / "batches",
                date(2018, 1, 1),
                1,
            )

        batch = (
            self.workspace / "batches" / self.batch_id
        )

        self.manifest = json.loads(
            (batch / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.manifest["s3_bucket"] = self.buckets["raw"]

        for entry in self.manifest["files"]:
            entry["s3_key"] = (
                f"batches/{self.batch_id}/attempts/"
                f"{'a' * 32}/{entry['file_name']}"
            )

            self.s3.objects[
                (self.buckets["raw"], entry["s3_key"])
            ] = (batch / entry["file_name"]).read_bytes()

        self.save_manifest()

        self.commit = (
            self.buckets["curated"],
            f"manifests/{self.batch_id}.json",
        )

    def save_manifest(self):
        key = (
            self.buckets["raw"],
            f"batches/{self.batch_id}/manifest.json",
        )

        self.s3.objects[key] = json.dumps(
            self.manifest
        ).encode("utf-8")

    def run_batch(self):
        with redirect_stdout(io.StringIO()):
            return process_batch(
                self.batch_id,
                self.s3,
                self.buckets,
                temporary_root=self.workspace,
            )

    def test_completion_is_uploaded_last(self):
        result = self.run_batch()

        self.assertEqual(result["status"], "complete")
        self.assertEqual(
            result["rows"],
            {
                "orders": 1,
                "order_items": 2,
                "shipments": 1,
            },
        )
        self.assertEqual(
            self.s3.writes[-1],
            self.commit,
        )

        commit = json.loads(
            self.s3.objects[self.commit]
        )

        for location in commit["datasets"].values():
            contents = self.s3.objects[
                (
                    location["s3_bucket"],
                    location["s3_key"],
                )
            ]

            self.assertEqual(
                hashlib.sha256(contents).hexdigest(),
                location["sha256"],
            )

    def test_repeat_invocation_performs_no_writes(self):
        self.run_batch()
        before = len(self.s3.writes)

        result = self.run_batch()

        self.assertEqual(
            result["status"],
            "already_processed",
        )
        self.assertEqual(len(self.s3.writes), before)

    def test_corrupt_raw_file_is_not_published(self):
        entry = self.manifest["files"][0]
        key = (
            self.buckets["raw"],
            entry["s3_key"],
        )

        self.s3.objects[key] += b"\n"

        with self.assertRaises(ValueError):
            self.run_batch()

        self.assertNotIn(
            self.commit,
            self.s3.objects,
        )
        self.assertEqual(self.s3.writes, [])

    def test_record_rejection_is_saved_to_quarantine(self):
        entry = next(
            entry
            for entry in self.manifest["files"]
            if entry["dataset"] == "order_items"
        )

        key = (
            self.buckets["raw"],
            entry["s3_key"],
        )

        frame = pd.read_csv(
            io.BytesIO(self.s3.objects[key]),
            dtype=str,
            keep_default_na=False,
        )
        frame.loc[0, "price"] = "-1.00"

        contents = frame.to_csv(
            index=False,
            lineterminator="\n",
        ).encode("utf-8")

        self.s3.objects[key] = contents

        entry.update({
            "size_bytes": len(contents),
            "sha256": hashlib.sha256(
                contents
            ).hexdigest(),
        })

        self.save_manifest()
        result = self.run_batch()

        self.assertEqual(
            result["rows"]["order_items"],
            1,
        )
        self.assertEqual(
            result["rejected_rows"]["order_items"],
            1,
        )

        commit = json.loads(
            self.s3.objects[self.commit]
        )
        location = commit["quarantine"]["order_items"]

        rejected = self.s3.objects[
            (
                location["s3_bucket"],
                location["s3_key"],
            )
        ]

        self.assertIn(b"INVALID_PRICE", rejected)

    def test_failed_upload_does_not_create_completion_manifest(self):
        self.s3.fail_on_item_parquet = True

        with self.assertRaises(RuntimeError):
            self.run_batch()

        self.assertNotIn(
            self.commit,
            self.s3.objects,
        )
        self.assertTrue(self.s3.writes)

        self.s3.fail_on_item_parquet = False

        self.assertEqual(
            self.run_batch()["status"],
            "complete",
        )

    def test_manifest_cannot_reference_another_batch(self):
        self.manifest["files"][0]["s3_key"] = (
            "batches/other/attempts/orders.csv"
        )
        self.save_manifest()

        with self.assertRaises(ValueError):
            self.run_batch()

        self.assertEqual(self.s3.writes, [])

    def test_competing_matching_completion_is_handled(self):
        self.s3.competing_commit = True

        self.assertEqual(
            self.run_batch()["status"],
            "already_processed",
        )
        self.assertIn(
            self.commit,
            self.s3.objects,
        )

    def test_changed_source_manifest_cannot_reuse_completion(self):
        self.run_batch()
        before = len(self.s3.writes)

        self.manifest["created_at_utc"] = "changed"
        self.save_manifest()

        with self.assertRaises(ValueError):
            self.run_batch()

        self.assertEqual(len(self.s3.writes), before)


if __name__ == "__main__":
    unittest.main()