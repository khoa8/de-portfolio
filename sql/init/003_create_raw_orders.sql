\connect ecom_dw

CREATE TABLE IF NOT EXISTS raw.orders_raw (
    raw_id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    order_code TEXT NOT NULL,
    payload JSONB NOT NULL,
    src_event_ts TIMESTAMPTZ,
    ingested_at TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT uq_raw_orders
        UNIQUE (source, order_code)
);
