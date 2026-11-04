SELECT
    o.order_id,
    o.order_purchase_timestamp,
    i.order_item_id,
    i.price,
    i.freight_value
FROM orders AS o
JOIN order_items AS i
    ON o.order_id = i.order_id
    AND o.source_date = i.source_date
WHERE o.source_date = '2018-01-01'
  AND i.source_date = '2018-01-01'
ORDER BY o.order_id, i.order_item_id
LIMIT 5;