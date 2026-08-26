INSERT INTO dw.dim_platform (platform_code, platform_name)
VALUES
    ('lazada', 'Lazada'),
    ('shopee', 'Shopee'),
    ('tiki', 'Tiki')
ON CONFLICT (platform_code) DO UPDATE
SET platform_name = EXCLUDED.platform_name
WHERE dw.dim_platform.platform_name IS DISTINCT FROM EXCLUDED.platform_name;

WITH raw_dates AS (
    SELECT (payload ->> 'order_date')::TIMESTAMP::DATE AS order_date
    FROM raw.orders_raw
),
bounds AS (
    SELECT MIN(order_date) AS min_date, MAX(order_date) AS max_date
    FROM raw_dates
),
date_series AS (
    SELECT GENERATE_SERIES(min_date, max_date, INTERVAL '1 day')::DATE AS full_date
    FROM bounds
)
INSERT INTO dw.dim_date (
    date_key,
    full_date,
    year,
    quarter,
    month,
    day,
    dow,
    is_weekend
)
SELECT
    TO_CHAR(full_date, 'YYYYMMDD')::INTEGER,
    full_date,
    EXTRACT(YEAR FROM full_date)::SMALLINT,
    EXTRACT(QUARTER FROM full_date)::SMALLINT,
    EXTRACT(MONTH FROM full_date)::SMALLINT,
    EXTRACT(DAY FROM full_date)::SMALLINT,
    EXTRACT(DOW FROM full_date)::SMALLINT,
    EXTRACT(DOW FROM full_date)::SMALLINT IN (0, 6)
FROM date_series
ON CONFLICT (date_key) DO NOTHING;

WITH raw_customers AS (
    SELECT
        platform.platform_key,
        COALESCE(NULLIF(BTRIM(raw.payload ->> 'buyer_name'), ''), 'unknown')
            AS customer_natural,
        (raw.payload ->> 'order_date')::TIMESTAMP::DATE AS seen_date
    FROM raw.orders_raw AS raw
    JOIN dw.dim_platform AS platform
      ON platform.platform_code = raw.source
),
customer_bounds AS (
    SELECT
        platform_key,
        customer_natural,
        MIN(seen_date) AS first_seen_date,
        MAX(seen_date) AS last_seen_date
    FROM raw_customers
    GROUP BY platform_key, customer_natural
)
INSERT INTO dw.dim_customer (
    platform_key,
    customer_natural,
    first_seen_date,
    last_seen_date,
    updated_at
)
SELECT
    platform_key,
    customer_natural,
    first_seen_date,
    last_seen_date,
    CURRENT_TIMESTAMP
FROM customer_bounds
ON CONFLICT (platform_key, customer_natural) DO UPDATE
SET first_seen_date = LEAST(
        dw.dim_customer.first_seen_date,
        EXCLUDED.first_seen_date
    ),
    last_seen_date = GREATEST(
        dw.dim_customer.last_seen_date,
        EXCLUDED.last_seen_date
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE ROW(
        dw.dim_customer.first_seen_date,
        dw.dim_customer.last_seen_date
    ) IS DISTINCT FROM ROW(
        LEAST(dw.dim_customer.first_seen_date, EXCLUDED.first_seen_date),
        GREATEST(dw.dim_customer.last_seen_date, EXCLUDED.last_seen_date)
    );

WITH raw_orders AS (
    SELECT
        source,
        order_code,
        (payload ->> 'order_date')::TIMESTAMP::DATE AS order_date,
        NULLIF(payload ->> 'order_status', '') AS order_status,
        COALESCE(NULLIF(BTRIM(payload ->> 'buyer_name'), ''), 'unknown')
            AS customer_natural,
        (payload ->> 'total_amount')::NUMERIC(18, 2) AS amount
    FROM raw.orders_raw
),
resolved_keys AS (
    SELECT
        platform.platform_key,
        raw_orders.order_code AS order_nk,
        customer.customer_key,
        date_dim.date_key,
        raw_orders.order_status,
        raw_orders.amount
    FROM raw_orders
    JOIN dw.dim_platform AS platform
      ON platform.platform_code = raw_orders.source
    JOIN dw.dim_customer AS customer
      ON customer.platform_key = platform.platform_key
     AND customer.customer_natural = raw_orders.customer_natural
    JOIN dw.dim_date AS date_dim
      ON date_dim.full_date = raw_orders.order_date
)
INSERT INTO dw.fact_orders (
    platform_key,
    order_nk,
    customer_key,
    date_key,
    order_status,
    amount,
    load_dts
)
SELECT
    platform_key,
    order_nk,
    customer_key,
    date_key,
    order_status,
    amount,
    CURRENT_TIMESTAMP
FROM resolved_keys
ON CONFLICT (platform_key, order_nk) DO UPDATE
SET customer_key = EXCLUDED.customer_key,
    date_key = EXCLUDED.date_key,
    order_status = EXCLUDED.order_status,
    amount = EXCLUDED.amount,
    load_dts = CURRENT_TIMESTAMP
WHERE ROW(
        dw.fact_orders.customer_key,
        dw.fact_orders.date_key,
        dw.fact_orders.order_status,
        dw.fact_orders.amount
    ) IS DISTINCT FROM ROW(
        EXCLUDED.customer_key,
        EXCLUDED.date_key,
        EXCLUDED.order_status,
        EXCLUDED.amount
    );
