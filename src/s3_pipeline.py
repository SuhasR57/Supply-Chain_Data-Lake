"""Process a small raw batch and publish an S3 completion manifest."""

import base64
import hashlib
import json
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from botocore.exceptions import ClientError

from scripts.transform_batch import transform_batch
from scripts.validate_batch import validate_batch


LOG = logging.getLogger(__name__)

MAX_MANIFEST_BYTES = 64 * 1024
MAX_FILE_BYTES = 10 * 1024 * 1024

EXPECTED_FILES = {
    "orders": "orders.csv",
    "order_items": "order_items.csv",
}


def read_bytes(s3, bucket, key, limit):
    response = s3.get_object(
        Bucket=bucket,
        Key=key,
    )

    body = response["Body"]

    try:
        if response["ContentLength"] > limit:
            raise ValueError(
                f"Object exceeds size limit: {key}"
            )

        contents = body.read(limit + 1)

        if len(contents) > limit:
            raise ValueError(
                f"Object exceeds size limit: {key}"
            )

        if len(contents) != response["ContentLength"]:
            raise ValueError(
                f"Incomplete object download: {key}"
            )

        return contents

    finally:
        body.close()


def read_commit(s3, bucket, key):
    try:
        contents = read_bytes(
            s3,
            bucket,
            key,
            MAX_MANIFEST_BYTES,
        )
        return json.loads(contents)

    except ClientError as error:
        status = error.response["ResponseMetadata"][
            "HTTPStatusCode"
        ]

        if status == 404:
            return None

        raise


def put_bytes(s3, bucket, key, contents, content_type):
    digest = hashlib.sha256(contents).digest()

    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=contents,
        ContentType=content_type,
        ChecksumAlgorithm="SHA256",
        ChecksumSHA256=base64.b64encode(
            digest
        ).decode("ascii"),
        IfNoneMatch="*",
    )

    return {
        "s3_bucket": bucket,
        "s3_key": key,
        "size_bytes": len(contents),
        "sha256": digest.hex(),
    }


def check_commit(commit, batch_id, source_hash):
    if (
        commit.get("schema_version") != 1
        or commit.get("status") != "complete"
        or commit.get("batch_id") != batch_id
        or commit.get("source_manifest_sha256") != source_hash
        or commit.get("processing_version") != "1"
    ):
        raise ValueError(
            "Existing completion manifest does not "
            "match this input/version"
        )


def process_batch(
    batch_id,
    s3,
    buckets,
    temporary_root=None,
):
    if not isinstance(batch_id, str) or not re.fullmatch(
        r"olist-\d{4}-\d{2}-\d{2}",
        batch_id,
    ):
        raise ValueError(
            "Expected batch_id in the form olist-YYYY-MM-DD"
        )

    source_date = date.fromisoformat(
        batch_id.removeprefix("olist-")
    )

    if batch_id != f"olist-{source_date.isoformat()}":
        raise ValueError("Noncanonical batch date")

    raw_bucket = buckets["raw"]
    curated_bucket = buckets["curated"]
    quarantine_bucket = buckets["quarantine"]

    raw_key = f"batches/{batch_id}/manifest.json"
    commit_key = f"manifests/{batch_id}.json"

    source_bytes = read_bytes(
        s3,
        raw_bucket,
        raw_key,
        MAX_MANIFEST_BYTES,
    )

    source_hash = hashlib.sha256(
        source_bytes
    ).hexdigest()

    manifest = json.loads(source_bytes)

    if (
        manifest.get("schema_version") != 1
        or manifest.get("batch_id") != batch_id
        or manifest.get("source_date") != source_date.isoformat()
        or manifest.get("s3_bucket") != raw_bucket
    ):
        raise ValueError(
            "Raw manifest metadata does not match requested batch"
        )

    entries = manifest.get("files")

    if not isinstance(entries, list) or len(entries) != 2:
        raise ValueError(
            "Expected exactly two source file entries"
        )

    if {
        entry["dataset"] for entry in entries
    } != set(EXPECTED_FILES):
        raise ValueError(
            "Expected orders and order_items source datasets"
        )

    for entry in entries:
        filename = EXPECTED_FILES[entry["dataset"]]

        allowed_key = (
            rf"batches/{re.escape(batch_id)}/"
            rf"attempts/[a-f0-9]{{32}}/"
            rf"{re.escape(filename)}"
        )

        if (
            entry["file_name"] != filename
            or not re.fullmatch(
                allowed_key,
                entry["s3_key"],
            )
        ):
            raise ValueError(
                "Source object key is outside "
                "the expected batch path"
            )

        if (
            type(entry["size_bytes"]) is not int
            or not 0 <= entry["size_bytes"] <= MAX_FILE_BYTES
        ):
            raise ValueError("Invalid source file size")

    existing = read_commit(
        s3,
        curated_bucket,
        commit_key,
    )

    if existing is not None:
        check_commit(existing, batch_id, source_hash)

        LOG.info(
            "batch_id=%s status=already_processed",
            batch_id,
        )

        return {
            "status": "already_processed",
            "batch_id": batch_id,
            "manifest_key": commit_key,
        }

    run_id = uuid4().hex
    run_prefix = f"runs/{batch_id}/{run_id}"

    LOG.info(
        "batch_id=%s run_id=%s stage=download",
        batch_id,
        run_id,
    )

    with TemporaryDirectory(dir=temporary_root) as temporary:
        workspace = Path(temporary)
        local_batch = workspace / "raw" / batch_id
        local_batch.mkdir(parents=True)

        (local_batch / "manifest.json").write_bytes(
            source_bytes
        )

        for entry in entries:
            contents = read_bytes(
                s3,
                raw_bucket,
                entry["s3_key"],
                MAX_FILE_BYTES,
            )

            (
                local_batch / entry["file_name"]
            ).write_bytes(contents)

        # Existing stages verify integrity, validate records,
        # transform types, and verify Parquet round trips.
        validated_dir, validation_report = validate_batch(
            local_batch,
            workspace / "validated",
        )

        parquet_dir, transform_report = transform_batch(
            validated_dir,
            workspace / "parquet",
        )

        LOG.info(
            "batch_id=%s run_id=%s stage=upload",
            batch_id,
            run_id,
        )

        quarantine = {}

        for dataset in EXPECTED_FILES:
            quarantine[dataset] = put_bytes(
                s3,
                quarantine_bucket,
                f"{run_prefix}/{dataset}.csv",
                (
                    validated_dir
                    / "quarantine"
                    / f"{dataset}.csv"
                ).read_bytes(),
                "text/csv",
            )

            quarantine[dataset]["rejected_rows"] = (
                validation_report["tables"][dataset][
                    "rejected_rows"
                ]
            )

        validation_location = put_bytes(
            s3,
            quarantine_bucket,
            f"{run_prefix}/validation_report.json",
            (validated_dir / "report.json").read_bytes(),
            "application/json",
        )

        datasets = {}

        for dataset, details in (
            transform_report["datasets"].items()
        ):
            relative = details["relative_path"]

            datasets[dataset] = put_bytes(
                s3,
                curated_bucket,
                f"{run_prefix}/{relative}",
                (parquet_dir / relative).read_bytes(),
                "application/octet-stream",
            )

            datasets[dataset].update({
                "rows": details["rows"],
                "schema": details["schema"],
            })

        transform_location = put_bytes(
            s3,
            curated_bucket,
            f"{run_prefix}/transform_report.json",
            (
                parquet_dir / "transform_report.json"
            ).read_bytes(),
            "application/json",
        )

        completion = {
            "schema_version": 1,
            "processing_version": "1",
            "status": "complete",
            "batch_id": batch_id,
            "source_date": source_date.isoformat(),
            "run_id": run_id,
            "completed_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "source_manifest_key": raw_key,
            "source_manifest_sha256": source_hash,
            "datasets": datasets,
            "quarantine": quarantine,
            "validation_report": validation_location,
            "transform_report": transform_location,
        }

        payload = (
            json.dumps(completion, indent=2) + "\n"
        ).encode("utf-8")

        try:
            # Publish last; never overwrite a completed batch.
            put_bytes(
                s3,
                curated_bucket,
                commit_key,
                payload,
                "application/json",
            )

        except ClientError as error:
            status = error.response["ResponseMetadata"][
                "HTTPStatusCode"
            ]

            if status != 412:
                raise

            winner = read_commit(
                s3,
                curated_bucket,
                commit_key,
            )

            if winner is None:
                raise ValueError(
                    "Completion conflict without "
                    "a readable manifest"
                ) from error

            check_commit(winner, batch_id, source_hash)

            return {
                "status": "already_processed",
                "batch_id": batch_id,
                "manifest_key": commit_key,
            }

    LOG.info(
        "batch_id=%s run_id=%s status=complete",
        batch_id,
        run_id,
    )

    return {
        "status": "complete",
        "batch_id": batch_id,
        "manifest_key": commit_key,
        "rows": {
            name: item["rows"]
            for name, item in datasets.items()
        },
        "rejected_rows": {
            name: item["rejected_rows"]
            for name, item in quarantine.items()
        },
    }