"""Transform a validated local batch into verified Parquet datasets."""

import argparse
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
import sys

# Support both direct-script and python -m invocation.
if __package__ in {None, ""}:
    sys.path.insert(
        0,
        str(Path(__file__).resolve().parents[1]),
    )

from src.local_storage import publish_directory
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.parquet as pq

from scripts.validate_batch import read_frame
from src.data_transformer import (
    TransformationError,
    build_tables,
)


ROOT = Path(__file__).resolve().parents[1]


def transform_batch(validated_dir, output_root):
    report_path = validated_dir / "report.json"
    report_bytes = report_path.read_bytes()
    validation_report = json.loads(report_bytes)

    if validation_report["schema_version"] != 1:
        raise TransformationError(
            "Unsupported validation report schema"
        )

    if validation_report["validation_rules_version"] != "1":
        raise TransformationError(
            "Unsupported validation rules version"
        )

    if validation_report["status"] not in {
        "validated",
        "validated_with_rejections",
    }:
        raise TransformationError(
            "Input does not have a completed validation status"
        )

    source_date = date.fromisoformat(
        validation_report["source_date"]
    )
    batch_id = validation_report["batch_id"]

    if batch_id != f"olist-{source_date.isoformat()}":
        raise TransformationError(
            "Batch ID does not match source date"
        )

    if validated_dir.name != batch_id:
        raise TransformationError(
            "Input folder does not match batch ID"
        )

    destination = output_root / batch_id

    if destination.exists():
        raise FileExistsError(
            f"Transformation output already exists: {destination}"
        )

    frames = {}
    input_hashes = {}

    for name in ["orders", "order_items"]:
        path = validated_dir / "accepted" / f"{name}.csv"
        contents = path.read_bytes()

        frames[name] = read_frame(contents, path.name)
        input_hashes[name] = hashlib.sha256(
            contents
        ).hexdigest()

        expected_rows = validation_report["tables"][name][
            "accepted_rows"
        ]

        if len(frames[name]) != expected_rows:
            raise TransformationError(
                f"{name}: accepted row count differs "
                "from validation report"
            )

    tables = build_tables(
        frames["orders"],
        frames["order_items"],
    )

    purchase_times = tables["orders"][
        "order_purchase_timestamp"
    ].to_pylist()

    if any(
        timestamp.date() != source_date
        for timestamp in purchase_times
    ):
        raise TransformationError(
            "An order purchase date differs from the batch source_date"
        )

    output_root.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(dir=output_root) as temporary:
        staging = Path(temporary) / batch_id
        staging.mkdir()

        dataset_reports = {}

        for name, table in tables.items():
            relative_path = (
                Path(name)
                / f"source_date={source_date.isoformat()}"
                / "part-00000.parquet"
            )

            path = staging / relative_path
            path.parent.mkdir(parents=True)

            pq.write_table(
                table,
                path,
                compression="snappy",
                version="1.0",
                coerce_timestamps="us",
                allow_truncated_timestamps=False,
            )

            # Read the exact file, without inferring partitions
            # from its parent directories.
            with path.open("rb") as handle:
                restored = pq.ParquetFile(handle).read()

            if not table.equals(restored):
                raise TransformationError(
                    f"{name}: Parquet round-trip verification failed"
                )

            contents = path.read_bytes()

            dataset_reports[name] = {
                "rows": table.num_rows,
                "relative_path": relative_path.as_posix(),
                "size_bytes": len(contents),
                "sha256": hashlib.sha256(
                    contents
                ).hexdigest(),
                "schema": {
                    field.name: str(field.type)
                    for field in table.schema
                },
            }

        transform_report = {
            "schema_version": 1,
            "transformation_version": "1",
            "batch_id": batch_id,
            "source_date": source_date.isoformat(),
            "transformed_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": "transformed",
            "partition_column": "source_date",
            "validation_report_sha256": hashlib.sha256(
                report_bytes
            ).hexdigest(),
            "accepted_input_sha256": input_hashes,
            "datasets": dataset_reports,
        }

        (staging / "transform_report.json").write_text(
            json.dumps(transform_report, indent=2) + "\n",
            encoding="utf-8",
        )

        publish_directory(staging, destination)

    return destination, transform_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--validated-dir",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "data" / "local" / "parquet",
    )

    args = parser.parse_args()

    try:
        destination, report = transform_batch(
            args.validated_dir.resolve(),
            args.output_root.resolve(),
        )

        print(f"TRANSFORMED: {report['batch_id']}")

        for name, details in report["datasets"].items():
            print(
                f"{name}: {details['rows']} rows, "
                f"{details['size_bytes']} bytes"
            )

        print(f"Output: {destination}")

    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        ArithmeticError,
        pa.ArrowException,
    ) as error:
        parser.exit(1, f"Transformation failed: {error}\n")


if __name__ == "__main__":
    main()