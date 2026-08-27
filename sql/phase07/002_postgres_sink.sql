CREATE SCHEMA IF NOT EXISTS cdc;

CREATE TABLE IF NOT EXISTS cdc.order_events (
    kafka_topic TEXT NOT NULL,
    kafka_partition INTEGER NOT NULL CHECK (kafka_partition >= 0),
    kafka_offset BIGINT NOT NULL CHECK (kafka_offset >= 0),
    kafka_timestamp TIMESTAMPTZ,
    event_kind TEXT NOT NULL CHECK (
        event_kind IN ('read', 'create', 'update', 'delete', 'tombstone', 'malformed')
    ),
    source_order_id BIGINT,
    source_event_ts TIMESTAMPTZ,
    before_payload JSONB,
    after_payload JSONB,
    raw_key TEXT,
    raw_value TEXT,
    malformed_reason TEXT,
    spark_batch_id BIGINT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (kafka_topic, kafka_partition, kafka_offset)
);

CREATE INDEX IF NOT EXISTS ix_order_events_source_order
    ON cdc.order_events (source_order_id, kafka_offset);

CREATE INDEX IF NOT EXISTS ix_order_events_kind
    ON cdc.order_events (event_kind, ingested_at);

CREATE TABLE IF NOT EXISTS cdc.orders_current (
    source_order_id BIGINT PRIMARY KEY,
    customer_name TEXT,
    amount NUMERIC(18, 2),
    status TEXT,
    source_updated_at TIMESTAMPTZ,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at TIMESTAMPTZ,
    kafka_topic TEXT NOT NULL,
    kafka_partition INTEGER NOT NULL CHECK (kafka_partition >= 0),
    kafka_offset BIGINT NOT NULL CHECK (kafka_offset >= 0),
    source_event_ts TIMESTAMPTZ,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (kafka_topic, kafka_partition, kafka_offset)
);

COMMENT ON TABLE cdc.order_events IS
    'Append-only Phase 07 Debezium event ledger keyed by Kafka topic-partition-offset.';
COMMENT ON TABLE cdc.orders_current IS
    'Idempotent current order state; deletes are represented by is_deleted=true.';
