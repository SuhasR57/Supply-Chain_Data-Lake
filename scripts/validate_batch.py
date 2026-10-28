"""Validate one local batch and save accepted and rejected records."""

import argparse
import csv
import io
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from scripts.upload_batch import load_and_verify
from src.data_validator import (
    BatchValidationError,
    validate_items,
    validate_orders,
)


ROOT = Path(__file__).resolve().parents[1]


def read_frame(contents, filename):
    """Read verified bytes without hiding malformed CSV structure."""
    reader = csv.reader(
        io.StringIO(
            contents.decode("utf-8-sig"),
            newline="",
        ),
        strict=True,
    )

    header = next(reader, None)

    if not header or any(not name.strip() for name in header):
        raise BatchValidationError(
            f"{filename}: missing or empty column names"
        )

    if len(header) != len(set(header)):
        raise BatchValidationError(
            f"{filename}: duplicate column names"
        )

    rows = []

    for record_number, row in enumerate(reader, start=1):
        if len(row) != len(header):
            raise BatchValidationError(
                f"{filename}: record {record_number} has "
                f"{len(row)} fields; expected {len(header)}"
            )

        rows.append(row)

    return pd.DataFrame(rows, columns=header)


def summarize(input_frame, accepted, rejected):
    input_rows = len(input_frame)
    accepted_rows = len(accepted)
    rejected_rows = len(rejected)

    if input_rows != accepted_rows + rejected_rows:
        raise RuntimeError("Row reconciliation failed")

    reasons = Counter()

    for value in rejected["rejection_reasons"]:
        reasons.update(value.split("|"))

    return {
        "input_rows": input_rows,
        "accepted_rows": accepted_rows,
        "rejected_rows": rejected_rows,
        "reconciled": True,
        "rejection_reason_counts": dict(sorted(reasons.items())),
    }


def validate_batch(batch_dir, output_root):
    manifest, prepared = load_and_verify(batch_dir)

    destination = output_root / manifest["batch_id"]

    if destination.exists():
        raise FileExistsError(
            f"Validation output already exists: {destination}"
        )

    frames = {}

    for entry, contents, _digest in prepared:
        frames[entry["dataset"]] = read_frame(
            contents,
            entry["file_name"],
        )

    orders = frames["orders"]
    items = frames["order_items"]

    accepted_orders, rejected_orders = validate_orders(orders)

    accepted_items, rejected_items = validate_items(
        items,
        known_order_ids=orders["order_id"],
        accepted_order_ids=accepted_orders["order_id"],
    )

    results = {
        "orders": (orders, accepted_orders, rejected_orders),
        "order_items": (items, accepted_items, rejected_items),
    }

    table_reports = {
        name: summarize(original, accepted, rejected)
        for name, (original, accepted, rejected) in results.items()
    }

    has_rejections = any(
        table["rejected_rows"] > 0
        for table in table_reports.values()
    )

    report = {
        "schema_version": 1,
        "validation_rules_version": "1",
        "batch_id": manifest["batch_id"],
        "source_date": manifest["source_date"],
        "validated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "status": (
            "validated_with_rejections"
            if has_rejections
            else "validated"
        ),
        "tables": table_reports,
    }

    # No output directory is created until both tables have
    # passed structural validation and row reconciliation.
    output_root.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(dir=output_root) as temporary:
        staging = Path(temporary) / manifest["batch_id"]

        (staging / "accepted").mkdir(parents=True)
        (staging / "quarantine").mkdir()

        for name, (_original, accepted, rejected) in results.items():
            accepted.to_csv(
                staging / "accepted" / f"{name}.csv",
                index=False,
                encoding="utf-8",
                lineterminator="\n",
            )

            rejected.to_csv(
                staging / "quarantine" / f"{name}.csv",
                index=False,
                encoding="utf-8",
                lineterminator="\n",
            )

        (staging / "report.json").write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
        )

        staging.rename(destination)

    return destination, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--batch-dir",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "data" / "local" / "validated",
    )

    args = parser.parse_args()

    try:
        destination, report = validate_batch(
            args.batch_dir.resolve(),
            args.output_root.resolve(),
        )

        print(f"\nVALIDATION COMPLETE: {report['batch_id']}")

        for name, counts in report["tables"].items():
            print(
                f"{name}: "
                f"{counts['input_rows']} input = "
                f"{counts['accepted_rows']} accepted + "
                f"{counts['rejected_rows']} rejected"
            )

        print(f"Status: {report['status']}")
        print(f"Output: {destination}")

    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        csv.Error,
        RuntimeError,
    ) as error:
        parser.exit(1, f"Validation failed: {error}\n")


if __name__ == "__main__":
    main()