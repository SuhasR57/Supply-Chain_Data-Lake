SELECT
    'orders' AS dataset,
    COUNT(*) AS row_count
FROM orders
WHERE source_date = '2018-01-01'

UNION ALL

SELECT
    'order_items' AS dataset,
    COUNT(*) AS row_count
FROM order_items
WHERE source_date = '2018-01-01'

UNION ALL

SELECT
    'shipments' AS dataset,
    COUNT(*) AS row_count
FROM shipments
WHERE source_date = '2018-01-01'

ORDER BY dataset;