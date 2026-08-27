"""Consume Debezium MySQL order events and publish idempotently to PostgreSQL."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


EVENT_KIND_BY_OP = {
    "r": "read",
    "c": "create",
    "u": "update",
    "d": "delete",
}


def _json_object(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("JSON value is not an object")
    payload = parsed.get("payload", parsed)
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("JSON payload is not an object")
    return payload


def _timestamp(value: Any, fallback: datetime | None = None) -> datetime | None:
    if value is None:
        return fallback
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return fallback


def _key_order_id(raw_key: str | None) -> int | None:
    try:
        key = _json_object(raw_key)
        value = None if key is None else key.get("id")
        return None if value is None else int(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def decode_record(
    raw_key: str | None,
    raw_value: str | None,
    kafka_timestamp: datetime | None,
) -> dict[str, Any]:
    """Decode one Kafka record without throwing on malformed source data."""

    base = {
        "event_kind": "malformed",
        "source_order_id": _key_order_id(raw_key),
        "source_event_ts": kafka_timestamp,
        "before_payload": None,
        "after_payload": None,
        "current_payload": None,
        "malformed_reason": None,
    }

    if raw_value is None:
        base["event_kind"] = "tombstone"
        return base

    try:
        envelope = _json_object(raw_value)
    except (ValueError, json.JSONDecodeError) as exc:
        base["malformed_reason"] = f"invalid_json:{type(exc).__name__}"
        return base

    if envelope is None:
        base["malformed_reason"] = "null_envelope"
        return base

    op = envelope.get("op")
    if op not in EVENT_KIND_BY_OP:
        base["malformed_reason"] = "unsupported_or_missing_op"
        return base

    before = envelope.get("before")
    after = envelope.get("after")
    if before is not None and not isinstance(before, dict):
        base["malformed_reason"] = "before_is_not_an_object"
        return base
    if after is not None and not isinstance(after, dict):
        base["malformed_reason"] = "after_is_not_an_object"
        return base

    current = before if op == "d" else after
    if not isinstance(current, dict):
        base["malformed_reason"] = "missing_row_image"
        return base

    order_id = current.get("id", base["source_order_id"])
    try:
        order_id = int(order_id)
    except (TypeError, ValueError):
        base["malformed_reason"] = "missing_or_invalid_order_id"
        return base

    base.update(
        {
            "event_kind": EVENT_KIND_BY_OP[op],
            "source_order_id": order_id,
            "source_event_ts": _timestamp(envelope.get("ts_ms"), kafka_timestamp),
            "before_payload": before,
            "after_payload": after,
            "current_payload": current,
        }
    )
    return base


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid amount in Debezium row image") from exc


def _required_environment() -> dict[str, str]:
    required = ("POSTGRES_USER", "POSTGRES_PASSWORD")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError("Missing Phase 07 environment key names: " + ", ".join(missing))
    return {
        "host": os.environ.get("POSTGRES_HOST", "postgres"),
        "port": os.environ.get("POSTGRES_PORT", "5432"),
        "dbname": os.environ.get("POSTGRES_DATABASE", "ecom_dw"),
        "user": os.environ["POSTGRES_USER"],
        "password": os.environ["POSTGRES_PASSWORD"],
    }


def _write_partition(rows: Iterable[Any], batch_id: int) -> None:
    import psycopg2
    from psycopg2.extras import Json

    connection = psycopg2.connect(**_required_environment())
    try:
        with connection:
            with connection.cursor() as cursor:
                for row in rows:
                    event = decode_record(row.raw_key, row.raw_value, row.kafka_timestamp)
                    cursor.execute(
                        """
                        INSERT INTO cdc.order_events (
                            kafka_topic, kafka_partition, kafka_offset,
                            kafka_timestamp, event_kind, source_order_id,
                            source_event_ts, before_payload, after_payload,
                            raw_key, raw_value, malformed_reason, spark_batch_id
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s
                        )
                        ON CONFLICT (kafka_topic, kafka_partition, kafka_offset)
                        DO NOTHING
                        """,
                        (
                            row.kafka_topic,
                            row.kafka_partition,
                            row.kafka_offset,
                            row.kafka_timestamp,
                            event["event_kind"],
                            event["source_order_id"],
                            event["source_event_ts"],
                            Json(event["before_payload"])
                            if event["before_payload"] is not None
                            else None,
                            Json(event["after_payload"])
                            if event["after_payload"] is not None
                            else None,
                            row.raw_key,
                            row.raw_value,
                            event["malformed_reason"],
                            batch_id,
                        ),
                    )

                    if event["event_kind"] not in {"read", "create", "update", "delete"}:
                        continue

                    payload = event["current_payload"]
                    assert isinstance(payload, dict)
                    source_updated_at = _timestamp(
                        payload.get("updated_at"), event["source_event_ts"]
                    )
                    is_deleted = event["event_kind"] == "delete"
                    cursor.execute(
                        """
                        INSERT INTO cdc.orders_current (
                            source_order_id, customer_name, amount, status,
                            source_updated_at, is_deleted, deleted_at,
                            kafka_topic, kafka_partition, kafka_offset,
                            source_event_ts, applied_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, CURRENT_TIMESTAMP
                        )
                        ON CONFLICT (source_order_id) DO UPDATE SET
                            customer_name = COALESCE(
                                EXCLUDED.customer_name, cdc.orders_current.customer_name
                            ),
                            amount = COALESCE(
                                EXCLUDED.amount, cdc.orders_current.amount
                            ),
                            status = COALESCE(
                                EXCLUDED.status, cdc.orders_current.status
                            ),
                            source_updated_at = COALESCE(
                                EXCLUDED.source_updated_at,
                                cdc.orders_current.source_updated_at
                            ),
                            is_deleted = EXCLUDED.is_deleted,
                            deleted_at = EXCLUDED.deleted_at,
                            kafka_topic = EXCLUDED.kafka_topic,
                            kafka_partition = EXCLUDED.kafka_partition,
                            kafka_offset = EXCLUDED.kafka_offset,
                            source_event_ts = EXCLUDED.source_event_ts,
                            applied_at = CURRENT_TIMESTAMP
                        WHERE cdc.orders_current.kafka_topic = EXCLUDED.kafka_topic
                          AND cdc.orders_current.kafka_partition = EXCLUDED.kafka_partition
                          AND cdc.orders_current.kafka_offset < EXCLUDED.kafka_offset
                        """,
                        (
                            event["source_order_id"],
                            payload.get("customer_name"),
                            _decimal(payload.get("amount")),
                            payload.get("status"),
                            source_updated_at,
                            is_deleted,
                            event["source_event_ts"] if is_deleted else None,
                            row.kafka_topic,
                            row.kafka_partition,
                            row.kafka_offset,
                            event["source_event_ts"],
                        ),
                    )
    finally:
        connection.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--trigger", choices=("availableNow", "processingTime"), default="availableNow"
    )
    parser.add_argument("--processing-time", default="5 seconds")
    parser.add_argument(
        "--checkpoint-location",
        default=os.environ.get(
            "PHASE07_CHECKPOINT_LOCATION",
            "/opt/airflow/checkpoints/mysql_orders",
        ),
    )
    return parser.parse_args()


def main() -> None:
    from pyspark.sql import SparkSession
    from pyspark.sql.functions import col

    args = _parse_args()
    checkpoint = Path(args.checkpoint_location)
    if not checkpoint.is_absolute() or str(checkpoint).startswith("/opt/airflow/logs"):
        raise RuntimeError("Checkpoint must be an absolute non-log path")

    spark = (
        SparkSession.builder.appName("phase07_mysql_cdc_to_postgres")
        .config("spark.sql.shuffle.partitions", "1")
        .config("spark.streaming.stopGracefullyOnShutdown", "true")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    source = (
        spark.readStream.format("kafka")
        .option(
            "kafka.bootstrap.servers",
            os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
        )
        .option(
            "subscribe",
            os.environ.get("KAFKA_CDC_TOPIC", "phase07.phase07_shop.orders"),
        )
        .option("startingOffsets", "earliest")
        .option("failOnDataLoss", "true")
        .load()
        .select(
            col("topic").alias("kafka_topic"),
            col("partition").alias("kafka_partition"),
            col("offset").alias("kafka_offset"),
            col("timestamp").alias("kafka_timestamp"),
            col("key").cast("string").alias("raw_key"),
            col("value").cast("string").alias("raw_value"),
        )
    )

    def write_batch(batch_df, batch_id: int) -> None:
        ordered = batch_df.repartition("kafka_partition").sortWithinPartitions(
            "kafka_partition", "kafka_offset"
        )
        ordered.foreachPartition(lambda rows: _write_partition(rows, batch_id))

    writer = (
        source.writeStream.outputMode("append")
        .option("checkpointLocation", str(checkpoint))
        .foreachBatch(write_batch)
    )
    if args.trigger == "availableNow":
        query = writer.trigger(availableNow=True).start()
    else:
        query = writer.trigger(processingTime=args.processing_time).start()
    query.awaitTermination()


if __name__ == "__main__":
    main()
