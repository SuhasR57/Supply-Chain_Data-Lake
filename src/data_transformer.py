"""Convert accepted Olist records into explicitly typed Arrow tables."""

from datetime import datetime
from decimal import Decimal, InvalidOperation

import pyarrow as pa

from src.data_validator import (
    DATE_FORMAT,
    ORDER_DATES,
    validate_items,
    validate_orders,
)


TIMESTAMP_TYPE = pa.timestamp("us")
MONEY_TYPE = pa.decimal128(18, 2)

ORDER_SCHEMA = pa.schema([
    ("order_id", pa.string()),
    ("customer_id", pa.string()),
    ("order_status", pa.string()),
    *[
        (column, TIMESTAMP_TYPE)
        for column in ORDER_DATES
    ],
])

ITEM_SCHEMA = pa.schema([
    ("order_id", pa.string()),
    ("order_item_id", pa.int64()),
    ("product_id", pa.string()),
    ("seller_id", pa.string()),
    ("shipping_limit_date", TIMESTAMP_TYPE),
    ("price", MONEY_TYPE),
    ("freight_value", MONEY_TYPE),
])

SHIPMENT_SCHEMA = pa.schema([
    ("order_id", pa.string()),
    ("order_status", pa.string()),
    ("carrier_handoff_at", TIMESTAMP_TYPE),
    ("customer_delivered_at", TIMESTAMP_TYPE),
    ("estimated_delivery_at", TIMESTAMP_TYPE),
])


class TransformationError(ValueError):
    """Input cannot be transformed using the defined output types."""


def parse_timestamp(value):
    text = value.strip()

    if not text:
        return None

    return datetime.strptime(text, DATE_FORMAT)


def parse_money(value):
    try:
        amount = Decimal(value.strip())

        if not amount.is_finite() or amount < 0:
            raise TransformationError(
                f"Invalid nonnegative currency amount: {value!r}"
            )

        # decimal128(18, 2) has room for 16 integer digits.
        if amount >= Decimal("10000000000000000"):
            raise TransformationError(
                "Currency amount exceeds decimal128(18, 2)"
            )

        quantized = amount.quantize(Decimal("0.01"))

        if amount != quantized:
            raise TransformationError(
                "Currency amount has more than two decimal places"
            )

        return quantized

    except InvalidOperation as error:
        raise TransformationError(
            f"Invalid currency amount: {value!r}"
        ) from error


def to_arrow(frame, schema):
    columns = {}

    for field in schema:
        values = frame[field.name].tolist()

        if pa.types.is_timestamp(field.type):
            converted = [
                parse_timestamp(value)
                for value in values
            ]

        elif pa.types.is_decimal(field.type):
            converted = [
                parse_money(value)
                for value in values
            ]

        elif pa.types.is_integer(field.type):
            converted = [int(value) for value in values]

        else:
            converted = values

        columns[field.name] = converted

    table = pa.Table.from_pydict(
        columns,
        schema=schema,
    )
    table.validate(full=True)

    return table


def build_tables(orders, items):
    """Return typed tables; refuse records that fail validation."""

    accepted_orders, rejected_orders = validate_orders(orders)

    accepted_items, rejected_items = validate_items(
        items,
        known_order_ids=orders["order_id"],
        accepted_order_ids=accepted_orders["order_id"],
    )

    if not rejected_orders.empty or not rejected_items.empty:
        raise TransformationError(
            "Transformation requires accepted records only: "
            f"{len(rejected_orders)} orders and "
            f"{len(rejected_items)} items failed validation"
        )

    handed_to_carrier = (
        accepted_orders["order_delivered_carrier_date"]
        .str.strip()
        .ne("")
    )

    shipments = (
        accepted_orders.loc[handed_to_carrier]
        .rename(columns={
            "order_delivered_carrier_date": "carrier_handoff_at",
            "order_delivered_customer_date": "customer_delivered_at",
            "order_estimated_delivery_date": "estimated_delivery_at",
        })
    )

    return {
        "orders": to_arrow(accepted_orders, ORDER_SCHEMA),
        "order_items": to_arrow(accepted_items, ITEM_SCHEMA),
        "shipments": to_arrow(shipments, SHIPMENT_SCHEMA),
    }