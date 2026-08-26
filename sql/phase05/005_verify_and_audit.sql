DO $phase05_verify$
BEGIN
    IF EXISTS (
        WITH staging_counts AS (
            SELECT 'lazada'::TEXT AS source, COUNT(DISTINCT BTRIM(order_id)) AS row_count
            FROM stg_edw.e01_lazada_orders
            UNION ALL
            SELECT 'shopee', COUNT(DISTINCT BTRIM(order_id))
            FROM stg_edw.e01_shopee_orders
            UNION ALL
            SELECT 'tiki', COUNT(DISTINCT BTRIM(order_id))
            FROM stg_edw.e01_tiki_orders
        ),
        raw_counts AS (
            SELECT source, COUNT(*) AS row_count
            FROM raw.orders_raw
            GROUP BY source
        )
        SELECT 1
        FROM staging_counts
        FULL OUTER JOIN raw_counts USING (source)
        WHERE staging_counts.row_count IS DISTINCT FROM raw_counts.row_count
    ) THEN
        RAISE EXCEPTION 'Phase 05 STG distinct-order counts do not match RAW';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM raw.orders_raw
        WHERE source NOT IN ('lazada', 'shopee', 'tiki')
           OR source <> LOWER(source)
           OR order_code IS NULL
           OR BTRIM(order_code) = ''
           OR src_event_ts IS NULL
           OR NOT payload ?& ARRAY[
                'platform',
                'order_id',
                'order_date',
                'order_status',
                'buyer_name',
                'total_amount',
                '_dedup',
                '_variants'
           ]
           OR payload ->> 'platform' IS DISTINCT FROM source
           OR payload ->> 'order_id' IS DISTINCT FROM order_code
    ) THEN
        RAISE EXCEPTION 'Phase 05 RAW contract verification failed';
    END IF;

    IF EXISTS (
        WITH raw_counts AS (
            SELECT source, COUNT(*) AS row_count
            FROM raw.orders_raw
            GROUP BY source
        ),
        fact_counts AS (
            SELECT platform.platform_code AS source, COUNT(*) AS row_count
            FROM dw.fact_orders AS fact
            JOIN dw.dim_platform AS platform
              ON platform.platform_key = fact.platform_key
            GROUP BY platform.platform_code
        )
        SELECT 1
        FROM raw_counts
        FULL OUTER JOIN fact_counts USING (source)
        WHERE raw_counts.row_count IS DISTINCT FROM fact_counts.row_count
    ) THEN
        RAISE EXCEPTION 'Phase 05 RAW counts do not match DW fact counts';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM dw.fact_orders AS fact
        LEFT JOIN dw.dim_platform AS platform
          ON platform.platform_key = fact.platform_key
        LEFT JOIN dw.dim_customer AS customer
          ON customer.customer_key = fact.customer_key
        LEFT JOIN dw.dim_date AS date_dim
          ON date_dim.date_key = fact.date_key
        WHERE platform.platform_key IS NULL
           OR customer.customer_key IS NULL
           OR date_dim.date_key IS NULL
    ) THEN
        RAISE EXCEPTION 'Phase 05 DW contains orphan dimension keys';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM dw.dim_platform
        WHERE platform_code NOT IN ('lazada', 'shopee', 'tiki')
           OR platform_code <> LOWER(platform_code)
    ) THEN
        RAISE EXCEPTION 'Phase 05 DW platform codes are not canonical lowercase values';
    END IF;

    IF EXISTS (
        WITH fact_daily AS (
            SELECT
                date_dim.full_date AS order_date,
                platform.platform_code,
                SUM(fact.amount)::NUMERIC(24, 2) AS total_sales,
                COUNT(*)::BIGINT AS order_count
            FROM dw.fact_orders AS fact
            JOIN dw.dim_date AS date_dim
              ON date_dim.date_key = fact.date_key
            JOIN dw.dim_platform AS platform
              ON platform.platform_key = fact.platform_key
            GROUP BY date_dim.full_date, platform.platform_code
        )
        SELECT 1
        FROM fact_daily
        FULL OUTER JOIN dm.mv_daily_sales AS mart
          ON mart.order_date = fact_daily.order_date
         AND mart.platform_code = fact_daily.platform_code
        WHERE fact_daily.order_count IS DISTINCT FROM mart.order_count
           OR fact_daily.total_sales IS DISTINCT FROM mart.total_sales
    ) THEN
        RAISE EXCEPTION 'Phase 05 DM totals or order counts do not match DW';
    END IF;
END
$phase05_verify$;

INSERT INTO dw.phase05_batch_audit (
    dag_run_id,
    staging_row_count,
    staging_distinct_order_count,
    raw_order_count,
    fact_order_count,
    dm_group_count,
    dm_order_count,
    dw_total_sales,
    dm_total_sales,
    verified_at
)
SELECT
    %(dag_run_id)s,
    (
        (SELECT COUNT(*) FROM stg_edw.e01_lazada_orders)
        + (SELECT COUNT(*) FROM stg_edw.e01_shopee_orders)
        + (SELECT COUNT(*) FROM stg_edw.e01_tiki_orders)
    ),
    (
        (SELECT COUNT(DISTINCT BTRIM(order_id)) FROM stg_edw.e01_lazada_orders)
        + (SELECT COUNT(DISTINCT BTRIM(order_id)) FROM stg_edw.e01_shopee_orders)
        + (SELECT COUNT(DISTINCT BTRIM(order_id)) FROM stg_edw.e01_tiki_orders)
    ),
    (SELECT COUNT(*) FROM raw.orders_raw),
    (SELECT COUNT(*) FROM dw.fact_orders),
    (SELECT COUNT(*) FROM dm.mv_daily_sales),
    (SELECT COALESCE(SUM(order_count), 0) FROM dm.mv_daily_sales),
    (SELECT COALESCE(SUM(amount), 0)::NUMERIC(24, 2) FROM dw.fact_orders),
    (SELECT COALESCE(SUM(total_sales), 0)::NUMERIC(24, 2) FROM dm.mv_daily_sales),
    CURRENT_TIMESTAMP
ON CONFLICT (dag_run_id) DO UPDATE
SET staging_row_count = EXCLUDED.staging_row_count,
    staging_distinct_order_count = EXCLUDED.staging_distinct_order_count,
    raw_order_count = EXCLUDED.raw_order_count,
    fact_order_count = EXCLUDED.fact_order_count,
    dm_group_count = EXCLUDED.dm_group_count,
    dm_order_count = EXCLUDED.dm_order_count,
    dw_total_sales = EXCLUDED.dw_total_sales,
    dm_total_sales = EXCLUDED.dm_total_sales,
    verified_at = EXCLUDED.verified_at;
