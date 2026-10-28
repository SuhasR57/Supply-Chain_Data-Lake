import csv
import hashlib
import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from scripts.generate_batches import generate_batches
from scripts.validate_batch import validate_batch
from src.data_validator import BatchValidationError


ROOT = Path(__file__).resolve().parents[1]


class TestValidateBatch(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

        self.workspace = Path(self.temporary.name)
        self.batch_root = self.workspace / "batches"
        self.output_root = self.workspace / "validated"

        with redirect_stdout(io.StringIO()):
            generate_batches(
                ROOT / "data" / "sample",
                self.batch_root,
                date(2018, 1, 1),
                1,
            )

        self.batch_dir = self.batch_root / "olist-2018-01-01"

    def run_validation(self):
        with redirect_stdout(io.StringIO()):
            return validate_batch(
                self.batch_dir,
                self.output_root,
            )

    def replace_orders(self, frame):
        path = self.batch_dir / "orders.csv"

        frame.to_csv(
            path,
            index=False,
            encoding="utf-8",
            lineterminator="\n",
        )

        # Rebuild transport metadata so the test reaches
        # business/schema validation rather than failing
        # the earlier file-integrity check.
        contents = path.read_bytes()

        reader = csv.DictReader(
            io.StringIO(contents.decode("utf-8"), newline="")
        )
        row_count = sum(1 for _ in reader)

        manifest_path = self.batch_dir / "manifest.json"
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )

        for entry in manifest["files"]:
            if entry["dataset"] == "orders":
                entry["row_count"] = row_count
                entry["size_bytes"] = len(contents)
                entry["sha256"] = hashlib.sha256(
                    contents
                ).hexdigest()

        manifest_path.write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
        )

    def test_clean_batch_writes_reconciled_outputs(self):
        destination, report = self.run_validation()

        self.assertEqual(report["status"], "validated")
        self.assertEqual(
            report["tables"]["orders"]["accepted_rows"],
            1,
        )
        self.assertEqual(
            report["tables"]["order_items"]["accepted_rows"],
            2,
        )

        self.assertTrue(
            (destination / "accepted" / "orders.csv").is_file()
        )
        self.assertTrue(
            (destination / "quarantine" / "orders.csv").is_file()
        )

        for counts in report["tables"].values():
            self.assertEqual(
                counts["input_rows"],
                counts["accepted_rows"] + counts["rejected_rows"],
            )

    def test_rejected_order_quarantines_its_items(self):
        orders = pd.read_csv(
            self.batch_dir / "orders.csv",
            dtype=str,
            keep_default_na=False,
        )

        orders.loc[0, "order_delivered_customer_date"] = ""
        self.replace_orders(orders)

        destination, report = self.run_validation()

        self.assertEqual(
            report["status"],
            "validated_with_rejections",
        )
        self.assertEqual(
            report["tables"]["orders"]["rejected_rows"],
            1,
        )
        self.assertEqual(
            report["tables"]["order_items"]["rejected_rows"],
            2,
        )

        rejected_items = pd.read_csv(
            destination / "quarantine" / "order_items.csv"
        )

        self.assertTrue(
            rejected_items["rejection_reasons"]
            .str.contains("PARENT_ORDER_REJECTED")
            .all()
        )

    def test_missing_file_produces_no_output(self):
        # Only removes a generated file in this test's
        # disposable temporary directory.
        (self.batch_dir / "order_items.csv").unlink()

        with self.assertRaises(FileNotFoundError):
            self.run_validation()

        self.assertFalse(self.output_root.exists())

    def test_missing_column_produces_no_output(self):
        orders = pd.read_csv(
            self.batch_dir / "orders.csv",
            dtype=str,
            keep_default_na=False,
        )

        self.replace_orders(
            orders.drop(columns=["order_status"])
        )

        with self.assertRaises(BatchValidationError):
            self.run_validation()

        self.assertFalse(self.output_root.exists())

    def test_changed_file_fails_integrity_check(self):
        path = self.batch_dir / "orders.csv"
        path.write_bytes(path.read_bytes() + b"\n")

        with self.assertRaises(ValueError):
            self.run_validation()

        self.assertFalse(self.output_root.exists())

    def test_existing_output_is_not_overwritten(self):
        destination, _report = self.run_validation()
        original = (destination / "report.json").read_bytes()

        with self.assertRaises(FileExistsError):
            self.run_validation()

        self.assertEqual(
            original,
            (destination / "report.json").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()