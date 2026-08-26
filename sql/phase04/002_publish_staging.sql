LOCK TABLE
    stg_edw.e01_lazada_orders,
    stg_edw.e01_shopee_orders,
    stg_edw.e01_tiki_orders,
    stg_edw.phase04_lazada_orders_load,
    stg_edw.phase04_shopee_orders_load,
    stg_edw.phase04_tiki_orders_load,
    stg_edw.phase04_load_metrics
IN ACCESS EXCLUSIVE MODE;

DO $phase04_validate$
BEGIN
    IF (SELECT count(*) FROM stg_edw.phase04_load_metrics) <> 3 THEN
        RAISE EXCEPTION 'Phase 04 requires exactly three load-metric rows';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM stg_edw.phase04_load_metrics
        WHERE dag_run_id <> %(dag_run_id)s
    ) THEN
        RAISE EXCEPTION 'Phase 04 load metrics belong to a different DAG run';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM stg_edw.phase04_load_metrics WHERE source_key = 'lazada')
       OR NOT EXISTS (SELECT 1 FROM stg_edw.phase04_load_metrics WHERE source_key = 'shopee')
       OR NOT EXISTS (SELECT 1 FROM stg_edw.phase04_load_metrics WHERE source_key = 'tiki') THEN
        RAISE EXCEPTION 'Phase 04 load metrics do not cover every source key';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM stg_edw.phase04_load_metrics
        WHERE source_count <> load_count
    ) THEN
        RAISE EXCEPTION 'Phase 04 source/load count reconciliation failed';
    END IF;

    IF (SELECT count(*) FROM stg_edw.phase04_lazada_orders_load)
       <> (SELECT load_count FROM stg_edw.phase04_load_metrics WHERE source_key = 'lazada')
       OR (SELECT count(*) FROM stg_edw.phase04_shopee_orders_load)
       <> (SELECT load_count FROM stg_edw.phase04_load_metrics WHERE source_key = 'shopee')
       OR (SELECT count(*) FROM stg_edw.phase04_tiki_orders_load)
       <> (SELECT load_count FROM stg_edw.phase04_load_metrics WHERE source_key = 'tiki') THEN
        RAISE EXCEPTION 'Phase 04 database load-table counts do not match metrics';
    END IF;

    IF EXISTS (SELECT 1 FROM stg_edw.phase04_lazada_orders_load WHERE platform IS DISTINCT FROM 'lazada')
       OR EXISTS (SELECT 1 FROM stg_edw.phase04_shopee_orders_load WHERE platform IS DISTINCT FROM 'shopee')
       OR EXISTS (SELECT 1 FROM stg_edw.phase04_tiki_orders_load WHERE platform IS DISTINCT FROM 'tiki') THEN
        RAISE EXCEPTION 'Phase 04 load table contains an invalid platform value';
    END IF;
END
$phase04_validate$;

TRUNCATE TABLE
    stg_edw.e01_lazada_orders,
    stg_edw.e01_shopee_orders,
    stg_edw.e01_tiki_orders;

INSERT INTO stg_edw.e01_lazada_orders (
    order_id, order_date, order_status, buyer_name, total_amount, platform
)
SELECT order_id, order_date, order_status, buyer_name, total_amount, platform
FROM stg_edw.phase04_lazada_orders_load;

INSERT INTO stg_edw.e01_shopee_orders (
    order_id, order_date, order_status, buyer_name, total_amount, platform
)
SELECT order_id, order_date, order_status, buyer_name, total_amount, platform
FROM stg_edw.phase04_shopee_orders_load;

INSERT INTO stg_edw.e01_tiki_orders (
    order_id, order_date, order_status, buyer_name, total_amount, platform
)
SELECT order_id, order_date, order_status, buyer_name, total_amount, platform
FROM stg_edw.phase04_tiki_orders_load;

DO $phase04_postcondition$
BEGIN
    IF (SELECT count(*) FROM stg_edw.e01_lazada_orders)
       <> (SELECT load_count FROM stg_edw.phase04_load_metrics WHERE source_key = 'lazada')
       OR (SELECT count(*) FROM stg_edw.e01_shopee_orders)
       <> (SELECT load_count FROM stg_edw.phase04_load_metrics WHERE source_key = 'shopee')
       OR (SELECT count(*) FROM stg_edw.e01_tiki_orders)
       <> (SELECT load_count FROM stg_edw.phase04_load_metrics WHERE source_key = 'tiki') THEN
        RAISE EXCEPTION 'Phase 04 published counts do not match validated load counts';
    END IF;
END
$phase04_postcondition$;

INSERT INTO stg_edw.phase04_batch_audit (
    dag_run_id,
    source_key,
    source_count,
    load_count,
    published_count,
    order_date_conversion_failures,
    total_amount_conversion_failures,
    published_at
)
SELECT
    %(dag_run_id)s,
    metrics.source_key,
    metrics.source_count,
    metrics.load_count,
    metrics.load_count,
    metrics.order_date_conversion_failures,
    metrics.total_amount_conversion_failures,
    CURRENT_TIMESTAMP
FROM stg_edw.phase04_load_metrics AS metrics
ON CONFLICT (dag_run_id, source_key) DO UPDATE SET
    source_count = EXCLUDED.source_count,
    load_count = EXCLUDED.load_count,
    published_count = EXCLUDED.published_count,
    order_date_conversion_failures = EXCLUDED.order_date_conversion_failures,
    total_amount_conversion_failures = EXCLUDED.total_amount_conversion_failures,
    published_at = EXCLUDED.published_at;
