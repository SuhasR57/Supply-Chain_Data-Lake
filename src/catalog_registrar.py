"""Register only dataset locations named by a completed batch manifest."""

import copy
import json
import re
from datetime import date

from botocore.exceptions import ClientError


DATASETS = ("orders", "order_items", "shipments")

TYPE_MAP = {
    "string": "string",
    "int64": "bigint",
    "timestamp[us]": "timestamp",
    "decimal128(18, 2)": "decimal(18,2)",
}


def descriptor_signature(descriptor):
    return (
        descriptor["Location"],
        {
            column["Name"]: column["Type"]
            for column in descriptor["Columns"]
        },
        descriptor["InputFormat"],
        descriptor["OutputFormat"],
        descriptor["SerdeInfo"]["SerializationLibrary"],
    )


def get_partition(glue, database, dataset, source_date):
    try:
        return glue.get_partition(
            DatabaseName=database,
            TableName=dataset,
            PartitionValues=[source_date],
        )["Partition"]

    except ClientError as error:
        if error.response["Error"]["Code"] == "EntityNotFoundException":
            return None

        raise


def require_matching(existing, expected, dataset):
    if descriptor_signature(existing["StorageDescriptor"]) != (
        descriptor_signature(expected)
    ):
        raise ValueError(
            f"{dataset}: existing partition conflicts with commit"
        )


def register_batch(
    batch_id,
    s3,
    glue,
    curated_bucket,
    database,
    dry_run=False,
):
    if not isinstance(batch_id, str) or not re.fullmatch(
        r"olist-\d{4}-\d{2}-\d{2}",
        batch_id,
    ):
        raise ValueError("Expected batch_id: olist-YYYY-MM-DD")

    source_date = date.fromisoformat(batch_id[6:]).isoformat()

    if batch_id != f"olist-{source_date}":
        raise ValueError("Noncanonical batch date")

    response = s3.get_object(
        Bucket=curated_bucket,
        Key=f"manifests/{batch_id}.json",
    )

    body = response["Body"]

    try:
        payload = body.read(65537)
    finally:
        body.close()

    if len(payload) > 65536:
        raise ValueError("Completion manifest exceeds 64 KiB")

    commit = json.loads(payload)

    if (
        commit.get("schema_version") != 1
        or commit.get("processing_version") != "1"
        or commit.get("status") != "complete"
        or commit.get("batch_id") != batch_id
        or commit.get("source_date") != source_date
        or not re.fullmatch(
            r"[a-f0-9]{32}",
            commit.get("run_id", ""),
        )
        or set(commit.get("datasets", {})) != set(DATASETS)
    ):
        raise ValueError("Invalid or unsupported completion manifest")

    # Preflight every dataset before creating any partitions.
    planned = []

    for dataset in DATASETS:
        entry = commit["datasets"][dataset]

        directory = (
            f"runs/{batch_id}/{commit['run_id']}/{dataset}/"
            f"source_date={source_date}/"
        )

        if (
            entry["s3_bucket"] != curated_bucket
            or entry["s3_key"] != directory + "part-00000.parquet"
        ):
            raise ValueError(
                f"{dataset}: unexpected committed object location"
            )

        metadata = s3.head_object(
            Bucket=curated_bucket,
            Key=entry["s3_key"],
        )

        if metadata["ContentLength"] != entry["size_bytes"]:
            raise ValueError(
                f"{dataset}: committed object size differs"
            )

        table = glue.get_table(
            DatabaseName=database,
            Name=dataset,
        )["Table"]

        keys = [
            (key["Name"], key["Type"])
            for key in table["PartitionKeys"]
        ]

        if keys != [("source_date", "string")]:
            raise ValueError(
                f"{dataset}: unexpected partition keys"
            )

        descriptor = copy.deepcopy(table["StorageDescriptor"])

        expected_columns = {
            name: TYPE_MAP[kind]
            for name, kind in entry["schema"].items()
        }

        actual_columns = {
            column["Name"]: column["Type"]
            for column in descriptor["Columns"]
        }

        if actual_columns != expected_columns:
            raise ValueError(
                f"{dataset}: catalog schema differs from commit"
            )

        descriptor["Location"] = (
            f"s3://{curated_bucket}/{directory}"
        )

        existing = get_partition(
            glue,
            database,
            dataset,
            source_date,
        )

        if existing is not None:
            require_matching(existing, descriptor, dataset)

        planned.append(
            (dataset, descriptor, existing, entry["rows"])
        )

    results = []

    for dataset, descriptor, existing, rows in planned:
        status = (
            "already_registered"
            if existing is not None
            else "created"
        )

        if existing is None and dry_run:
            status = "would_create"

        elif existing is None:
            try:
                glue.create_partition(
                    DatabaseName=database,
                    TableName=dataset,
                    PartitionInput={
                        "Values": [source_date],
                        "StorageDescriptor": descriptor,
                    },
                )

            except ClientError as error:
                if (
                    error.response["Error"]["Code"]
                    != "AlreadyExistsException"
                ):
                    raise

                # Another execution may have registered it.
                winner = get_partition(
                    glue,
                    database,
                    dataset,
                    source_date,
                )

                if winner is None:
                    raise ValueError(
                        "Partition conflict without a readable winner"
                    )

                require_matching(winner, descriptor, dataset)
                status = "already_registered"

        results.append({
            "dataset": dataset,
            "source_date": source_date,
            "status": status,
            "expected_rows": rows,
            "location": descriptor["Location"],
        })

    return {
        "batch_id": batch_id,
        "partitions": results,
    }