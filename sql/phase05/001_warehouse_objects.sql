CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS dw;
CREATE SCHEMA IF NOT EXISTS dm;

CREATE TABLE IF NOT EXISTS raw.orders_raw (
    raw_id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    order_code TEXT NOT NULL,
    payload JSONB NOT NULL,
    src_event_ts TIMESTAMP WITH TIME ZONE,
    ingested_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_raw_orders UNIQUE (source, order_code)
);

CREATE INDEX IF NOT EXISTS idx_orders_raw_src_event_ts
    ON raw.orders_raw (src_event_ts);

CREATE TABLE IF NOT EXISTS dw.dim_platform (
    platform_key SMALLSERIAL PRIMARY KEY,
    platform_code TEXT NOT NULL UNIQUE,
    platform_name TEXT NOT NULL,
    CONSTRAINT ck_dim_platform_code
        CHECK (platform_code IN ('lazada', 'shopee', 'tiki'))
);

CREATE TABLE IF NOT EXISTS dw.dim_customer (
    customer_key BIGSERIAL PRIMARY KEY,
    platform_key SMALLINT NOT NULL
        REFERENCES dw.dim_platform (platform_key),
    customer_natural TEXT NOT NULL,
    first_seen_date DATE NOT NULL,
    last_seen_date DATE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_dim_customer
        UNIQUE (platform_key, customer_natural),
    CONSTRAINT ck_dim_customer_seen_dates
        CHECK (first_seen_date <= last_seen_date)
);

CREATE TABLE IF NOT EXISTS dw.dim_date (
    date_key INTEGER PRIMARY KEY,
    full_date DATE NOT NULL UNIQUE,
    year SMALLINT NOT NULL,
    quarter SMALLINT NOT NULL,
    month SMALLINT NOT NULL,
    day SMALLINT NOT NULL,
    dow SMALLINT NOT NULL,
    is_weekend BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS dw.fact_orders (
    platform_key SMALLINT NOT NULL
        REFERENCES dw.dim_platform (platform_key),
    order_nk TEXT NOT NULL,
    customer_key BIGINT NOT NULL
        REFERENCES dw.dim_customer (customer_key),
    date_key INTEGER NOT NULL
        REFERENCES dw.dim_date (date_key),
    order_status TEXT,
    amount NUMERIC(18, 2) NOT NULL,
    load_dts TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_fact_orders PRIMARY KEY (platform_key, order_nk)
);

CREATE INDEX IF NOT EXISTS idx_fact_orders_date_key
    ON dw.fact_orders (date_key);

CREATE INDEX IF NOT EXISTS idx_fact_orders_customer_key
    ON dw.fact_orders (customer_key);

CREATE TABLE IF NOT EXISTS dw.phase05_batch_audit (
    dag_run_id TEXT PRIMARY KEY,
    staging_row_count BIGINT NOT NULL,
    staging_distinct_order_count BIGINT NOT NULL,
    raw_order_count BIGINT NOT NULL,
    fact_order_count BIGINT NOT NULL,
    dm_group_count BIGINT NOT NULL,
    dm_order_count BIGINT NOT NULL,
    dw_total_sales NUMERIC(24, 2) NOT NULL,
    dm_total_sales NUMERIC(24, 2) NOT NULL,
    verified_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
