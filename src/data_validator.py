"""Record validation for historical Olist order batches."""

import math

import pandas as pd


DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_PATTERN = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"

ORDER_DATES = [
    "order_purchase_timestamp",
    "order_approved_at",
    "order_delivered_carrier_date",
    "order_delivered_customer_date",
    "order_estimated_delivery_date",
]

ORDER_COLUMNS = [
    "order_id",
    "customer_id",
    "order_status",
    *ORDER_DATES,
]

ITEM_COLUMNS = [
    "order_id",
    "order_item_id",
    "product_id",
    "seller_id",
    "shipping_limit_date",
    "price",
    "freight_value",
]

ORDER_STATUSES = {
    "created",
    "approved",
    "invoiced",
    "processing",
    "shipped",
    "delivered",
    "unavailable",
    "canceled",
}


class BatchValidationError(ValueError):
    """The batch cannot be interpreted using its expected schema."""


def prepare(frame, required_columns):
    if frame.columns.duplicated().any():
        raise BatchValidationError("Duplicate column names")

    missing = set(required_columns) - set(frame.columns)
    if missing:
        raise BatchValidationError(
            f"Missing required columns: {sorted(missing)}"
        )

    reserved = {"source_record_number", "rejection_reasons"}
    if reserved.intersection(frame.columns):
        raise BatchValidationError(
            "Input contains reserved validation columns"
        )

    # Work on a separate copy with a predictable row index.
    data = frame.reset_index(drop=True).fillna("").astype(str)
    reasons = pd.Series("", index=data.index, dtype=object)

    return data, reasons


def reject(reasons, mask, reason):
    mask = mask.fillna(False)

    reasons.loc[mask] = reasons.loc[mask].map(
        lambda existing: (
            f"{existing}|{reason}" if existing else reason
        )
    )


def check_identifiers(data, reasons, columns):
    for column in columns:
        values = data[column]
        stripped = values.str.strip()

        reject(
            reasons,
            stripped.eq(""),
            f"MISSING_{column.upper()}",
        )

        reject(
            reasons,
            values.ne(stripped),
            f"WHITESPACE_IN_{column.upper()}",
        )


def parse_timestamp(data, reasons, column, required=False):
    values = data[column].str.strip()

    parsed = pd.to_datetime(
        values,
        format=DATE_FORMAT,
        errors="coerce",
    )

    has_value = values.ne("")
    correct_shape = values.str.fullmatch(
        DATE_PATTERN,
        na=False,
    )

    reject(
        reasons,
        has_value & (~correct_shape | parsed.isna()),
        f"INVALID_{column.upper()}",
    )

    if required:
        reject(
            reasons,
            ~has_value,
            f"MISSING_{column.upper()}",
        )

    return parsed


def split_results(data, reasons):
    rejected_mask = reasons.ne("")

    accepted = data.loc[~rejected_mask].copy()
    rejected = data.loc[rejected_mask].copy()

    # One-based data-record number, not physical CSV line number.
    rejected.insert(
        0,
        "source_record_number",
        rejected.index + 1,
    )

    rejected["rejection_reasons"] = reasons.loc[rejected_mask]

    return (
        accepted.reset_index(drop=True),
        rejected.reset_index(drop=True),
    )


def validate_orders(frame):
    data, reasons = prepare(frame, ORDER_COLUMNS)

    check_identifiers(
        data,
        reasons,
        ["order_id", "customer_id"],
    )

    reject(
        reasons,
        data.duplicated(["order_id"], keep=False),
        "DUPLICATE_ORDER_ID",
    )

    reject(
        reasons,
        ~data["order_status"].isin(ORDER_STATUSES),
        "INVALID_ORDER_STATUS",
    )

    parsed = {}

    for column in ORDER_DATES:
        parsed[column] = parse_timestamp(
            data,
            reasons,
            column,
            required=column in {
                "order_purchase_timestamp",
                "order_estimated_delivery_date",
            },
        )

    reject(
        reasons,
        data["order_status"].eq("delivered")
        & data["order_delivered_customer_date"].str.strip().eq(""),
        "DELIVERED_ORDER_MISSING_DELIVERY_DATE",
    )

    purchase = parsed["order_purchase_timestamp"]

    for column in ORDER_DATES[1:]:
        reject(
            reasons,
            parsed[column] < purchase,
            f"{column.upper()}_BEFORE_PURCHASE",
        )

    reject(
        reasons,
        parsed["order_delivered_customer_date"]
        < parsed["order_delivered_carrier_date"],
        "CUSTOMER_DELIVERY_BEFORE_CARRIER_HANDOFF",
    )

    return split_results(data, reasons)


def validate_items(frame, known_order_ids, accepted_order_ids):
    data, reasons = prepare(frame, ITEM_COLUMNS)

    check_identifiers(
        data,
        reasons,
        ["order_id", "order_item_id", "product_id", "seller_id"],
    )

    reject(
        reasons,
        data.duplicated(
            ["order_id", "order_item_id"],
            keep=False,
        ),
        "DUPLICATE_ORDER_ITEM_KEY",
    )

    reject(
        reasons,
        ~data["order_item_id"].str.fullmatch(
            r"[1-9][0-9]*",
            na=False,
        ),
        "INVALID_ORDER_ITEM_ID",
    )

    parse_timestamp(
        data,
        reasons,
        "shipping_limit_date",
        required=True,
    )

    for column in ["price", "freight_value"]:
        numbers = pd.to_numeric(data[column], errors="coerce")

        valid_numbers = numbers.map(
            lambda value: (
                pd.notna(value)
                and math.isfinite(value)
                and value >= 0
            )
        )

        reject(
            reasons,
            ~valid_numbers,
            f"INVALID_{column.upper()}",
        )

    known = data["order_id"].isin(set(known_order_ids))
    accepted_parent = data["order_id"].isin(
        set(accepted_order_ids)
    )

    reject(reasons, ~known, "ORDER_NOT_FOUND")

    reject(
        reasons,
        known & ~accepted_parent,
        "PARENT_ORDER_REJECTED",
    )

    return split_results(data, reasons)