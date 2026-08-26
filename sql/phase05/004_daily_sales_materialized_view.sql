CREATE MATERIALIZED VIEW IF NOT EXISTS dm.mv_daily_sales AS
SELECT
    date_dim.full_date AS order_date,
    platform.platform_code,
    platform.platform_name,
    SUM(fact.amount)::NUMERIC(24, 2) AS total_sales,
    COUNT(*)::BIGINT AS order_count
FROM dw.fact_orders AS fact
JOIN dw.dim_date AS date_dim
  ON date_dim.date_key = fact.date_key
JOIN dw.dim_platform AS platform
  ON platform.platform_key = fact.platform_key
GROUP BY
    date_dim.full_date,
    platform.platform_code,
    platform.platform_name
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_daily_sales_date_platform
    ON dm.mv_daily_sales (order_date, platform_code);

CREATE INDEX IF NOT EXISTS idx_mv_daily_sales_order_date
    ON dm.mv_daily_sales (order_date);

REFRESH MATERIALIZED VIEW dm.mv_daily_sales;
