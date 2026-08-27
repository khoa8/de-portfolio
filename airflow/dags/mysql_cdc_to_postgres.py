"""Phase 07: bounded MySQL CDC consumption from Kafka into PostgreSQL."""

from __future__ import annotations

import logging
import os
from datetime import timedelta
from pathlib import Path

import pendulum

from airflow.providers.apache.spark.operators.spark_submit import SparkSubmitOperator
from airflow.sdk import dag, task


LOGGER = logging.getLogger(__name__)
DAG_ID = "mysql_cdc_to_postgres"
POSTGRES_CONNECTION_ID = "pg_dw"
SPARK_CONNECTION_ID = "spark_local"
SPARK_APPLICATION = "/opt/airflow/spark/mysql_cdc_to_postgres.py"
SINK_DDL_PATH = Path("/opt/airflow/sql/phase07/002_postgres_sink.sql")
SPARK_KAFKA_PACKAGE = "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1"
POSTGRES_JAR = "/opt/airflow/jars/postgresql-42.7.7.jar"


def _runtime_configuration() -> dict[str, str]:
    checkpoint = os.environ.get(
        "PHASE07_CHECKPOINT_LOCATION",
        "/opt/airflow/checkpoints/mysql_orders",
    )
    if not Path(checkpoint).is_absolute() or checkpoint.startswith("/opt/airflow/logs"):
        raise RuntimeError("Phase 07 checkpoint must be an absolute non-log path")
    bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    if bootstrap_servers.startswith("localhost"):
        raise RuntimeError("Kafka must use Compose service DNS from Airflow")
    return {
        "bootstrap_servers": bootstrap_servers,
        "topic": os.environ.get(
            "KAFKA_CDC_TOPIC", "phase07.phase07_shop.orders"
        ),
        "checkpoint": checkpoint,
    }


@dag(
    dag_id=DAG_ID,
    description="Bounded Debezium MySQL CDC to append-only/current PostgreSQL sinks",
    schedule=None,
    start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=1)},
    tags=["phase07", "mysql", "debezium", "kafka", "spark", "postgres"],
)
def mysql_cdc_to_postgres():
    @task
    def preflight() -> dict[str, str]:
        config = _runtime_configuration()
        missing = [
            path
            for path in (SPARK_APPLICATION, str(SINK_DDL_PATH), POSTGRES_JAR)
            if not Path(path).is_file()
        ]
        if missing:
            raise RuntimeError(
                "Phase 07 runtime artifacts are missing: "
                + ", ".join(Path(path).name for path in missing)
            )
        LOGGER.info(
            "Phase 07 preflight succeeded: kafka_host=%s, topic=%s, checkpoint=%s",
            config["bootstrap_servers"].split(":", maxsplit=1)[0],
            config["topic"],
            config["checkpoint"],
        )
        return config

    @task
    def prepare_sink() -> None:
        from airflow.providers.postgres.hooks.postgres import PostgresHook

        hook = PostgresHook(postgres_conn_id=POSTGRES_CONNECTION_ID)
        connection = hook.get_conn()
        try:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(SINK_DDL_PATH.read_text(encoding="utf-8"))
        finally:
            connection.close()
        LOGGER.info("Phase 07 PostgreSQL CDC sink contract is ready")

    consume_available_events = SparkSubmitOperator(
        task_id="consume_available_events",
        application=SPARK_APPLICATION,
        conn_id=SPARK_CONNECTION_ID,
        packages=SPARK_KAFKA_PACKAGE,
        jars=POSTGRES_JAR,
        conf={"spark.jars.ivy": "/home/airflow/.ivy2"},
        application_args=[
            "--trigger",
            "availableNow",
            "--checkpoint-location",
            "{{ task_instance.xcom_pull(task_ids='preflight')['checkpoint'] }}",
        ],
    )

    @task
    def verify_sink() -> dict[str, int]:
        from airflow.providers.postgres.hooks.postgres import PostgresHook

        hook = PostgresHook(postgres_conn_id=POSTGRES_CONNECTION_ID)
        connection = hook.get_conn()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        COUNT(*)::BIGINT,
                        COUNT(*) FILTER (WHERE event_kind = 'malformed')::BIGINT,
                        COUNT(*) FILTER (WHERE event_kind = 'delete')::BIGINT,
                        COUNT(*) FILTER (WHERE event_kind = 'tombstone')::BIGINT
                    FROM cdc.order_events
                    """
                )
                event_count, malformed_count, delete_count, tombstone_count = (
                    cursor.fetchone()
                )
                cursor.execute(
                    """
                    SELECT
                        COUNT(*)::BIGINT,
                        COUNT(*) FILTER (WHERE is_deleted)::BIGINT
                    FROM cdc.orders_current
                    """
                )
                current_count, soft_deleted_count = cursor.fetchone()
        finally:
            connection.close()

        if event_count == 0:
            raise RuntimeError("Phase 07 sink contains no Kafka events")
        metrics = {
            "event_count": event_count,
            "malformed_count": malformed_count,
            "delete_count": delete_count,
            "tombstone_count": tombstone_count,
            "current_count": current_count,
            "soft_deleted_count": soft_deleted_count,
        }
        LOGGER.info("Phase 07 sink metrics: %s", metrics)
        return metrics

    config = preflight()
    sink_ready = prepare_sink()
    config >> sink_ready >> consume_available_events >> verify_sink()


mysql_cdc_to_postgres()
