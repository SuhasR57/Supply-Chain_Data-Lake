"""Inspect small Olist CSV inputs without dependencies or AWS access."""

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPECS = {
    "orders": (
        "olist_orders_dataset.csv",
        ("order_id",),
        ("order_purchase_timestamp", "order_approved_at",
         "order_delivered_carrier_date", "order_delivered_customer_date",
         "order_estimated_delivery_date"),
    ),
    "order_items": (
        "olist_order_items_dataset.csv",
        ("order_id", "order_item_id"),
        ("shipping_limit_date",),
    ),
}


def inspect_file(path, keys, timestamps):
    """Return summary and referenced order IDs; hold keys in memory for inspection."""
    missing = Counter()
    seen = set()
    order_ids = set()
    duplicates = 0
    incomplete = 0
    count = 0
    ranges = {name: {"min": None, "max": None, "invalid": 0}
              for name in timestamps}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []
        if not columns or len(columns) != len(set(columns)):
            raise ValueError(f"{path.name}: absent or duplicate column headers")
        required = set(keys) | set(timestamps)
        absent = required - set(columns)
        if absent:
            raise ValueError(f"{path.name}: missing columns: {', '.join(sorted(absent))}")
        for row in reader:
            count += 1
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{path.name}: malformed CSV near line {reader.line_num}")
            for column in columns:
                if not row[column].strip():
                    missing[column] += 1
            key = tuple(row[column].strip() for column in keys)
            if not all(key):
                incomplete += 1
            elif key in seen:
                duplicates += 1
            else:
                seen.add(key)
            if row["order_id"].strip():
                order_ids.add(row["order_id"].strip())
            for column in timestamps:
                value = row[column].strip()
                if not value:
                    continue
                try:
                    parsed = datetime.fromisoformat(value)
                    if parsed.tzinfo is not None:
                        raise ValueError("Expected source timestamps without timezone")
                except ValueError:
                    ranges[column]["invalid"] += 1
                    continue
                normalized = parsed.isoformat(sep=" ")
                stat = ranges[column]
                stat["min"] = min(stat["min"], normalized) if stat["min"] else normalized
                stat["max"] = max(stat["max"], normalized) if stat["max"] else normalized
    return {
        "file": path.name,
        "rows": count,
        "columns": columns,
        "key_columns": list(keys),
        "duplicate_key_rows": duplicates,
        "incomplete_key_rows": incomplete,
        "empty_values_by_column": {c: missing[c] for c in columns},
        "timestamp_ranges": ranges,
    }, order_ids


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--report", type=Path, help="Optional JSON report destination")
    args = parser.parse_args()
    try:
        report = {"source_directory": str(args.data_dir.resolve()), "tables": {}}
        ids = {}
        for name, (filename, keys, timestamps) in SPECS.items():
            report["tables"][name], ids[name] = inspect_file(
                args.data_dir / filename, keys, timestamps
            )
        report["distinct_item_order_ids_absent_from_orders"] = len(
            ids["order_items"] - ids["orders"]
        )
        rendered = json.dumps(report, indent=2)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
    except (OSError, ValueError, csv.Error) as error:
        print(f"Inspection failed: {error}", file=sys.stderr)
        print("Download the two source CSVs into data/raw, or use --data-dir data/sample.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
