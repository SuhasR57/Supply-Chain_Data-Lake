import unittest
from pathlib import Path

import pandas as pd

from src.data_validator import (
    BatchValidationError,
    validate_items,
    validate_orders,
)


ROOT = Path(__file__).resolve().parents[1]


class TestDataValidator(unittest.TestCase):
    def setUp(self):
        sample_dir = ROOT / "data" / "sample"

        self.orders = pd.read_csv(
            sample_dir / "olist_orders_dataset.csv",
            dtype=str,
            keep_default_na=False,
        )

        self.items = pd.read_csv(
            sample_dir / "olist_order_items_dataset.csv",
            dtype=str,
            keep_default_na=False,
        )

    def test_original_sample_orders_are_accepted(self):
        accepted, rejected = validate_orders(self.orders)

        self.assertEqual(len(accepted), 2)
        self.assertEqual(len(rejected), 0)

    def test_delivered_order_requires_delivery_date(self):
        self.orders.loc[0, "order_delivered_customer_date"] = ""

        accepted, rejected = validate_orders(self.orders)

        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 1)
        self.assertIn(
            "DELIVERED_ORDER_MISSING_DELIVERY_DATE",
            rejected.iloc[0]["rejection_reasons"],
        )

    def test_all_duplicate_order_keys_are_rejected(self):
        duplicate_orders = pd.concat(
            [self.orders.iloc[[0]], self.orders.iloc[[0]]],
            ignore_index=True,
        )

        accepted, rejected = validate_orders(duplicate_orders)

        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 2)

    def test_missing_column_fails_validation(self):
        broken = self.orders.drop(columns=["order_status"])

        with self.assertRaises(BatchValidationError):
            validate_orders(broken)

    def test_infinite_price_is_rejected(self):
        self.items.loc[0, "price"] = "inf"

        accepted, rejected = validate_items(
            self.items,
            self.orders["order_id"],
            self.orders["order_id"],
        )

        self.assertEqual(len(rejected), 1)
        self.assertIn(
            "INVALID_PRICE",
            rejected.iloc[0]["rejection_reasons"],
        )

    def test_absent_parent_order_is_rejected(self):
        self.items.loc[0, "order_id"] = "missing_order"

        accepted, rejected = validate_items(
            self.items,
            self.orders["order_id"],
            self.orders["order_id"],
        )

        self.assertEqual(len(rejected), 1)
        self.assertIn(
            "ORDER_NOT_FOUND",
            rejected.iloc[0]["rejection_reasons"],
        )

    def test_items_of_rejected_order_are_rejected(self):
        accepted_order_ids = ["sample_order_002"]

        accepted, rejected = validate_items(
            self.items,
            self.orders["order_id"],
            accepted_order_ids,
        )

        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 2)
        self.assertTrue(
            rejected["rejection_reasons"]
            .str.contains("PARENT_ORDER_REJECTED")
            .all()
        )


if __name__ == "__main__":
    unittest.main()