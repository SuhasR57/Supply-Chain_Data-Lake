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
from scripts.transform_batch import transform_batch
from scripts.validate_batch import validate_batch
from src.data_transformer import TransformationError


ROOT = Path(__file__).resolve().parents[1]


class TestTransformBatch(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

        self.workspace = Path(self.temporary.name)
        self.batch_root = self.workspace / "batches"
        self.validated_root = self.workspace / "validated"
        self.output_root = self.workspace / "parquet"

        with redirect_stdout(io.StringIO()):
            generate_batches(
                ROOT / "data" / "sample",
                self.batch_root,
                date(2018, 1, 1),
                2,
            )

            for batch_id in [
                "olist-2018-01-01",
                "olist-2018-01-02",
            ]:
                validate_batch(
                    self.batch_root / batch_id,
                    self.validated_root,
                )

        self.validated_dir = (
            self.validated_root / "olist-2018-01-01"
        )

    def test_writes_files_with_matching_checksums(self):
        destination, report = transform_batch(
            self.validated_dir,
            self.output_root,
        )

        self.assertEqual(
            report["datasets"]["orders"]["rows"],
            1,
        )
        self.assertEqual(
            report["datasets"]["order_items"]["rows"],
            2,
        )
        self.assertEqual(
            report["datasets"]["shipments"]["rows"],
            1,
        )

        for details in report["datasets"].values():
            path = destination / details["relative_path"]
            contents = path.read_bytes()

            self.assertEqual(
                len(contents),
                details["size_bytes"],
            )
            self.assertEqual(
                hashlib.sha256(contents).hexdigest(),
                details["sha256"],
            )

        saved_report = json.loads(
            (destination / "transform_report.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(saved_report, report)

    def test_empty_shipment_dataset_is_written(self):
        destination, report = transform_batch(
            self.validated_root / "olist-2018-01-02",
            self.output_root,
        )

        details = report["datasets"]["shipments"]

        self.assertEqual(details["rows"], 0)
        self.assertTrue(
            (destination / details["relative_path"]).is_file()
        )

    def test_invalid_currency_precision_produces_no_output(self):
        path = (
            self.validated_dir / "accepted" / "order_items.csv"
        )

        items = pd.read_csv(
            path,
            dtype=str,
            keep_default_na=False,
        )
        items.loc[0, "price"] = "50.001"
        items.to_csv(path, index=False)

        with self.assertRaises(TransformationError):
            transform_batch(
                self.validated_dir,
                self.output_root,
            )

        self.assertFalse(self.output_root.exists())

    def test_missing_accepted_file_produces_no_output(self):
        # This file exists only in the disposable test directory.
        (
            self.validated_dir / "accepted" / "orders.csv"
        ).unlink()

        with self.assertRaises(FileNotFoundError):
            transform_batch(
                self.validated_dir,
                self.output_root,
            )

        self.assertFalse(self.output_root.exists())

    def test_existing_output_is_not_overwritten(self):
        destination, _report = transform_batch(
            self.validated_dir,
            self.output_root,
        )

        original = (
            destination / "transform_report.json"
        ).read_bytes()

        with self.assertRaises(FileExistsError):
            transform_batch(
                self.validated_dir,
                self.output_root,
            )

        self.assertEqual(
            original,
            (
                destination / "transform_report.json"
            ).read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()