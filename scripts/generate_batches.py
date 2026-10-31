"""will Generate daily historical Olist batches and manifests."""

import argparse
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
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

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def read_source(path, required_columns):
    # Preserve identifiers and original empty fields.
    frame = pd.read_csv(
        path,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
    )

    missing = set(required_columns) - set(frame.columns)
    if missing:
        raise ValueError(
            f"{path.name}: missing columns {sorted(missing)}"
        )

    if frame["order_id"].str.strip().eq("").any():
        raise ValueError(f"{path.name}: empty order_id found")

    return frame


def write_csv(frame, path, dataset):
    frame.to_csv(
        path,
        index=False,
        encoding="utf-8",
        lineterminator="\n",
    )

    contents = path.read_bytes()

    return {
        "dataset": dataset,
        "file_name": path.name,
        "row_count": len(frame),
        "size_bytes": len(contents),
        "sha256": hashlib.sha256(contents).hexdigest(),
    }


def generate_batches(data_dir, output_dir, start_date, days):
    orders = read_source(
        data_dir / "olist_orders_dataset.csv",
        ["order_id", "order_purchase_timestamp"],
    )

    items = read_source(
        data_dir / "olist_order_items_dataset.csv",
        ["order_id", "order_item_id"],
    )

    purchase_dates = pd.to_datetime(
        orders["order_purchase_timestamp"],
        format="%Y-%m-%d %H:%M:%S",
        errors="raise",
    ).dt.date

    if purchase_dates.isna().any():
        raise ValueError("Orders contain missing purchase timestamps")

    orphan_mask = ~items["order_id"].isin(orders["order_id"])
    if orphan_mask.any():
        raise ValueError(
            "Some order items reference orders absent from the source"
        )

    dates = [
        start_date + timedelta(days=offset)
        for offset in range(days)
    ]

    # Check all destinations before creating any batches.
    for source_date in dates:
        destination = output_dir / f"olist-{source_date.isoformat()}"
        if destination.exists():
            raise FileExistsError(
                f"Batch already exists: {destination}"
            )

    output_dir.mkdir(parents=True, exist_ok=True)

    for source_date in dates:
        batch_id = f"olist-{source_date.isoformat()}"
        destination = output_dir / batch_id

        daily_orders = orders.loc[
            purchase_dates == source_date
        ].copy()

        daily_items = items.loc[
            items["order_id"].isin(daily_orders["order_id"])
        ].copy()

        # Assemble a complete batch before exposing its final folder.
        with TemporaryDirectory(dir=output_dir) as temporary:
            staging = Path(temporary) / batch_id
            staging.mkdir()

            files = [
                write_csv(
                    daily_orders,
                    staging / "orders.csv",
                    "orders",
                ),
                write_csv(
                    daily_items,
                    staging / "order_items.csv",
                    "order_items",
                ),
            ]

            manifest = {
                "schema_version": 1,
                "batch_id": batch_id,
                "source": "olist",
                "replay_mode": "historical_purchase_date",
                "source_date": source_date.isoformat(),
                "created_at_utc": datetime.now(
                    timezone.utc
                ).isoformat(),
                "files": files,
            }

            (staging / "manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n",
                encoding="utf-8",
            )

            staging.rename(destination)

        print(
            f"{batch_id}: "
            f"{len(daily_orders)} orders, "
            f"{len(daily_items)} items"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--data-dir",
        type=Path,
        default=ROOT / "data" / "raw",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "data" / "local" / "batches",
    )
    parser.add_argument(
        "--start-date",
        type=date.fromisoformat,
        required=True,
        help="First historical purchase date, YYYY-MM-DD",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
    )

    args = parser.parse_args()

    if not 1 <= args.days <= 31:
        parser.error("--days must be between 1 and 31")

    try:
        generate_batches(
            args.data_dir,
            args.output_dir,
            args.start_date,
            args.days,
        )
    except (OSError, ValueError, pd.errors.ParserError) as error:
        parser.exit(1, f"Batch generation failed: {error}\n")


if __name__ == "__main__":
    main()