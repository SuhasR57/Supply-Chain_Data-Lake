import io
import unittest
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from src.data_transformer import (
    SHIPMENT_SCHEMA,
    TransformationError,
    build_tables,
)


ROOT = Path(__file__).resolve().parents[1]


class TestDataTransformer(unittest.TestCase):
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

    def test_table_counts_and_types(self):
        tables = build_tables(self.orders, self.items)

        self.assertEqual(tables["orders"].num_rows, 2)
        self.assertEqual(tables["order_items"].num_rows, 3)
        self.assertEqual(tables["shipments"].num_rows, 1)

        self.assertEqual(
            tables["order_items"].schema.field(
                "order_item_id"
            ).type,
            pa.int64(),
        )

        self.assertEqual(
            tables["orders"].schema.field(
                "order_purchase_timestamp"
            ).type,
            pa.timestamp("us"),
        )

    def test_money_is_stored_as_decimal(self):
        tables = build_tables(self.orders, self.items)
        items = tables["order_items"]

        self.assertEqual(
            items.schema.field("price").type,
            pa.decimal128(18, 2),
        )

        self.assertEqual(
            items["price"][0].as_py(),
            Decimal("50.00"),
        )

    def test_parquet_round_trip_preserves_tables(self):
        tables = build_tables(self.orders, self.items)

        for name, original in tables.items():
            with self.subTest(dataset=name):
                buffer = io.BytesIO()

                pq.write_table(
                    original,
                    buffer,
                    compression="snappy",
                    version="1.0",
                    coerce_timestamps="us",
                )

                buffer.seek(0)
                restored = pq.ParquetFile(buffer).read()

                self.assertTrue(original.equals(restored))

    def test_empty_shipments_keep_the_schema(self):
        canceled = self.orders.loc[
            self.orders["order_status"].eq("canceled")
        ].copy()

        canceled_items = self.items.loc[
            self.items["order_id"].isin(canceled["order_id"])
        ].copy()

        tables = build_tables(canceled, canceled_items)

        self.assertEqual(tables["shipments"].num_rows, 0)
        self.assertEqual(
            tables["shipments"].schema,
            SHIPMENT_SCHEMA,
        )

    def test_invalid_records_are_not_silently_dropped(self):
        self.orders.loc[0, "order_delivered_customer_date"] = ""

        with self.assertRaises(TransformationError):
            build_tables(self.orders, self.items)

    def test_extra_currency_precision_is_not_rounded(self):
        self.items.loc[0, "price"] = "50.001"

        with self.assertRaises(TransformationError):
            build_tables(self.orders, self.items)


if __name__ == "__main__":
    unittest.main()