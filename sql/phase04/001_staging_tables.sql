CREATE SCHEMA IF NOT EXISTS stg_edw;

CREATE TABLE IF NOT EXISTS stg_edw.e01_lazada_orders (
    order_id TEXT,
    order_date TIMESTAMP WITHOUT TIME ZONE,
    order_status TEXT,
    buyer_name TEXT,
    total_amount NUMERIC(18, 2),
    platform TEXT NOT NULL CHECK (platform = 'lazada')
);

CREATE TABLE IF NOT EXISTS stg_edw.e01_shopee_orders (
    order_id TEXT,
    order_date TIMESTAMP WITHOUT TIME ZONE,
    order_status TEXT,
    buyer_name TEXT,
    total_amount NUMERIC(18, 2),
    platform TEXT NOT NULL CHECK (platform = 'shopee')
);

CREATE TABLE IF NOT EXISTS stg_edw.e01_tiki_orders (
    order_id TEXT,
    order_date TIMESTAMP WITHOUT TIME ZONE,
    order_status TEXT,
    buyer_name TEXT,
    total_amount NUMERIC(18, 2),
    platform TEXT NOT NULL CHECK (platform = 'tiki')
);

CREATE TABLE IF NOT EXISTS stg_edw.phase04_lazada_orders_load (
    order_id TEXT,
    order_date TIMESTAMP WITHOUT TIME ZONE,
    order_status TEXT,
    buyer_name TEXT,
    total_amount NUMERIC(18, 2),
    platform TEXT
);

CREATE TABLE IF NOT EXISTS stg_edw.phase04_shopee_orders_load (
    order_id TEXT,
    order_date TIMESTAMP WITHOUT TIME ZONE,
    order_status TEXT,
    buyer_name TEXT,
    total_amount NUMERIC(18, 2),
    platform TEXT
);

CREATE TABLE IF NOT EXISTS stg_edw.phase04_tiki_orders_load (
    order_id TEXT,
    order_date TIMESTAMP WITHOUT TIME ZONE,
    order_status TEXT,
    buyer_name TEXT,
    total_amount NUMERIC(18, 2),
    platform TEXT
);

CREATE TABLE IF NOT EXISTS stg_edw.phase04_load_metrics (
    source_key TEXT PRIMARY KEY CHECK (source_key IN ('lazada', 'shopee', 'tiki')),
    dag_run_id TEXT NOT NULL,
    source_count BIGINT NOT NULL CHECK (source_count >= 0),
    load_count BIGINT NOT NULL CHECK (load_count >= 0),
    order_date_conversion_failures BIGINT NOT NULL CHECK (order_date_conversion_failures >= 0),
    total_amount_conversion_failures BIGINT NOT NULL CHECK (total_amount_conversion_failures >= 0)
);

CREATE TABLE IF NOT EXISTS stg_edw.phase04_batch_audit (
    dag_run_id TEXT NOT NULL,
    source_key TEXT NOT NULL CHECK (source_key IN ('lazada', 'shopee', 'tiki')),
    source_count BIGINT NOT NULL CHECK (source_count >= 0),
    load_count BIGINT NOT NULL CHECK (load_count >= 0),
    published_count BIGINT NOT NULL CHECK (published_count >= 0),
    order_date_conversion_failures BIGINT NOT NULL CHECK (order_date_conversion_failures >= 0),
    total_amount_conversion_failures BIGINT NOT NULL CHECK (total_amount_conversion_failures >= 0),
    published_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (dag_run_id, source_key)
);
