# Data notes

## Source and scope

Source: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce

The real data is a historical snapshot. Grouping completed records by purchase date does not reconstruct what was known on each historical day. We will explicitly describe this as batch replay.

## Orders

- File: `olist_orders_dataset.csv`
- Grain: one row per order.
- Expected key: `order_id`.
- Important fields: `customer_id`, `order_status`, `order_purchase_timestamp`, `order_approved_at`, `order_delivered_carrier_date`, `order_delivered_customer_date`, `order_estimated_delivery_date`.
- Empty delivery timestamps may be legitimate for undelivered or canceled orders.
- Parse timestamps without assuming a timezone that the source does not specify.

## Order items

- File: `olist_order_items_dataset.csv`
- Grain: one item line within an order.
- Expected key: (`order_id`, `order_item_id`).
- `order_id` alone is not unique here.
- Other fields include `product_id`, `seller_id`, `shipping_limit_date`, `price`, and `freight_value`.

## Shipment limitation

There is no independent shipment event stream in these two files. Later we will derive an order-level delivery record using the order timestamps. Do not invent carrier IDs or claim that these are package-level tracking events.

## Record your Day 1 findings

- Download date: 10/24/2026
- Order row count: 99441
- Order-item row count: 112650
- Duplicate order keys: 0
- Duplicate item keys: 0
- Purchase timestamp range:  "2016-09-04 21:15:19" - "2018-10-17 17:30:18",
- Columns containing empty values:  "order_approved_at": 160,
        "order_delivered_carrier_date": 1783,
        "order_delivered_customer_date": 2965,
- Order items referencing absent orders: 0
- Questions to investigate before validation rules are finalized:
- Are missing delivery timestamps explained by order status?
- Do any delivered orders lack a customer-delivery timestamp?
- Are any approval, carrier-handoff, or delivery dates earlier than purchase?
- Which orders have no item records, and what are their statuses?
