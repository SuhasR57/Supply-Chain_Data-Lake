"""Verify and publish one small historical batch to Amazon S3."""

import argparse
import base64
import csv
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import boto3
from botocore.exceptions import BotoCoreError, ClientError


EXPECTED_FILES = {
    "orders": "orders.csv",
    "order_items": "order_items.csv",
}

MAX_FILE_BYTES = 10 * 1024 * 1024


def load_and_verify(batch_dir):
    manifest_path = batch_dir / "manifest.json"
    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )

    if manifest["schema_version"] != 1:
        raise ValueError("Unsupported manifest schema version")

    batch_id = manifest["batch_id"]

    if not re.fullmatch(r"olist-\d{4}-\d{2}-\d{2}", batch_id):
        raise ValueError("Invalid batch_id")

    if batch_id != f"olist-{manifest['source_date']}":
        raise ValueError("batch_id does not match source_date")

    if batch_dir.name != batch_id:
        raise ValueError("Folder name does not match batch_id")

    entries = manifest["files"]

    if not isinstance(entries, list) or len(entries) != 2:
        raise ValueError("Manifest must describe exactly two files")

    datasets = [entry["dataset"] for entry in entries]

    if set(datasets) != set(EXPECTED_FILES):
        raise ValueError(
            "Manifest must contain orders and order_items"
        )

    prepared = []

    for entry in entries:
        dataset = entry["dataset"]
        filename = EXPECTED_FILES[dataset]

        if entry["file_name"] != filename:
            raise ValueError(
                f"Unexpected filename for dataset {dataset}"
            )

        path = batch_dir / filename

        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError(
                f"{filename}: exceeds this uploader's 10 MiB limit"
            )

        # Keep verified bytes in memory and upload those same bytes.
        contents = path.read_bytes()

        if len(contents) > MAX_FILE_BYTES:
            raise ValueError(f"{filename}: file grew while reading")

        digest = hashlib.sha256(contents).digest()

        if len(contents) != entry["size_bytes"]:
            raise ValueError(f"{filename}: file size mismatch")

        if digest.hex() != entry["sha256"]:
            raise ValueError(f"{filename}: SHA-256 mismatch")

        text = contents.decode("utf-8-sig")
        reader = csv.DictReader(
            io.StringIO(text, newline=""),
            strict=True,
        )

        if not reader.fieldnames:
            raise ValueError(f"{filename}: missing CSV header")

        row_count = sum(1 for _ in reader)

        if row_count != entry["row_count"]:
            raise ValueError(f"{filename}: row count mismatch")

        prepared.append((dict(entry), contents, digest))

        print(
            f"VERIFIED {filename}: "
            f"{row_count} rows, {len(contents)} bytes"
        )

    return manifest, prepared


def object_exists(s3, bucket, key):
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as error:
        status = error.response["ResponseMetadata"][
            "HTTPStatusCode"
        ]

        if status == 404:
            return False

        # Permission failures and other errors must not be
        # interpreted as an absent object.
        raise


def publish_batch(manifest, prepared, bucket, profile, region):
    session = boto3.Session(
        profile_name=profile,
        region_name=region,
    )
    s3 = session.client("s3")

    batch_id = manifest["batch_id"]
    manifest_key = f"batches/{batch_id}/manifest.json"

    if object_exists(s3, bucket, manifest_key):
        print(
            f"SKIPPED {batch_id}: "
            "a published manifest already exists"
        )
        return

    attempt_id = uuid4().hex
    prefix = f"batches/{batch_id}/attempts/{attempt_id}"
    uploaded_entries = []

    for entry, contents, digest in prepared:
        key = f"{prefix}/{entry['file_name']}"

        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=contents,
            ContentType="text/csv",
            ChecksumAlgorithm="SHA256",
            ChecksumSHA256=base64.b64encode(
                digest
            ).decode("ascii"),
            Metadata={"sha256": digest.hex()},
            IfNoneMatch="*",
        )

        entry["s3_key"] = key
        uploaded_entries.append(entry)

        print(f"UPLOADED s3://{bucket}/{key}")

    published_manifest = {
        **manifest,
        "s3_bucket": bucket,
        "upload_attempt_id": attempt_id,
        "uploaded_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "files": uploaded_entries,
    }

    manifest_bytes = (
        json.dumps(published_manifest, indent=2) + "\n"
    ).encode("utf-8")

    # Publish last. Only the first successful publisher can
    # create the canonical manifest for this batch ID.
    s3.put_object(
        Bucket=bucket,
        Key=manifest_key,
        Body=manifest_bytes,
        ContentType="application/json",
        IfNoneMatch="*",
    )

    print(f"PUBLISHED s3://{bucket}/{manifest_key}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--batch-dir",
        type=Path,
        required=True,
    )
    parser.add_argument("--bucket")
    parser.add_argument(
        "--profile",
        default="supplychain",
    )
    parser.add_argument(
        "--region",
        default="us-east-2",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Verify local files without making AWS calls",
    )

    args = parser.parse_args()

    if not args.dry_run and not args.bucket:
        parser.error("--bucket is required unless using --dry-run")

    try:
        manifest, prepared = load_and_verify(
            args.batch_dir.resolve()
        )

        if args.dry_run:
            print(
                f"DRY RUN PASSED: {manifest['batch_id']}; "
                "no AWS calls made"
            )
            return

        publish_batch(
            manifest,
            prepared,
            args.bucket,
            args.profile,
            args.region,
        )

    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        csv.Error,
        BotoCoreError,
        ClientError,
    ) as error:
        parser.exit(1, f"Upload failed: {error}\n")


if __name__ == "__main__":
    main()