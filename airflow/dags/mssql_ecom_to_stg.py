"""Phase 04: SQL Server e-commerce sources to PostgreSQL staging."""

from __future__ import annotations

import logging
import os
import re
import socket
from datetime import timedelta
from pathlib import Path

import pendulum

from airflow.providers.apache.spark.operators.spark_submit import SparkSubmitOperator
from airflow.sdk import dag, task


LOGGER = logging.getLogger(__name__)

DAG_ID = "mssql_ecom_to_stg"
SPARK_CONNECTION_ID = "spark_local"
SPARK_APPLICATION = "/opt/airflow/spark/spark_mssql_to_postgres.py"
JDBC_JARS = (
    "/opt/airflow/jars/mssql-jdbc-13.4.0.jre11.jar,"
    "/opt/airflow/jars/postgresql-42.7.7.jar"
)
DDL_PATH = Path("/opt/airflow/sql/phase04/001_staging_tables.sql")
PUBLISH_PATH = Path("/opt/airflow/sql/phase04/002_publish_staging.sql")

SOURCE_KEYS = ("lazada", "shopee", "tiki")
LOAD_TABLES = (
    "stg_edw.phase04_lazada_orders_load",
    "stg_edw.phase04_shopee_orders_load",
    "stg_edw.phase04_tiki_orders_load",
)
EXPECTED_ORDER_COLUMNS = (
    ("order_id", "text", None, None),
    ("order_date", "timestamp without time zone", None, None),
    ("order_status", "text", None, None),
    ("buyer_name", "text", None, None),
    ("total_amount", "numeric", 18, 2),
    ("platform", "text", None, None),
)
ORDER_TABLE_NAMES = (
    "e01_lazada_orders",
    "e01_shopee_orders",
    "e01_tiki_orders",
    "phase04_lazada_orders_load",
    "phase04_shopee_orders_load",
    "phase04_tiki_orders_load",
)


def _required_environment() -> dict[str, str]:
    required_keys = ("MSSQL_HOST", "MSSQL_USER", "MSSQL_PASSWORD")
    missing = [key for key in required_keys if not os.environ.get(key)]
    if missing:
        raise RuntimeError(
            "Phase 04 SQL Server configuration is incomplete; missing key names: "
            + ", ".join(missing)
        )

    database = os.environ.get("MSSQL_DATABASE", "EDW_Tech")
    if database != "EDW_Tech":
        raise RuntimeError("MSSQL_DATABASE must be EDW_Tech for Phase 04")

    host = os.environ["MSSQL_HOST"].strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", host):
        raise RuntimeError("MSSQL_HOST contains unsupported characters")

    try:
        port = int(os.environ.get("MSSQL_PORT", "1433"))
    except ValueError as exc:
        raise RuntimeError("MSSQL_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("MSSQL_PORT must be between 1 and 65535")

    for key in ("MSSQL_ENCRYPT", "MSSQL_TRUST_SERVER_CERTIFICATE"):
        value = os.environ.get(key, "true" if key == "MSSQL_ENCRYPT" else "false")
        if value.lower() not in {"true", "false"}:
            raise RuntimeError(f"{key} must be true or false")

    return {"host": host, "port": str(port), "database": database}


def _endpoint_class(host: str) -> str:
    if host == "host.docker.internal":
        return "host_service"
    if "." not in host:
        return "compose_or_container_service"
    return "remote_host"


def _validate_order_table_contract(cursor) -> None:
    cursor.execute(
        """
        SELECT
            table_name,
            column_name,
            data_type,
            numeric_precision,
            numeric_scale
        FROM information_schema.columns
        WHERE table_schema = 'stg_edw'
          AND table_name = ANY(%s)
        ORDER BY table_name, ordinal_position
        """,
        (list(ORDER_TABLE_NAMES),),
    )
    actual: dict[str, list[tuple[str, str, int | None, int | None]]] = {}
    for table_name, column_name, data_type, precision, scale in cursor.fetchall():
        actual.setdefault(table_name, []).append(
            (column_name, data_type, precision, scale)
        )

    expected = list(EXPECTED_ORDER_COLUMNS)
    mismatches = [
        table_name
        for table_name in ORDER_TABLE_NAMES
        if actual.get(table_name) != expected
    ]
    if mismatches:
        raise RuntimeError(
            "Phase 04 table contract mismatch for: " + ", ".join(mismatches)
        )


@dag(
    dag_id=DAG_ID,
    description="Full-refresh EDW_Tech.ecom orders into ecom_dw.stg_edw",
    schedule=None,
    start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=2)},
    tags=["phase04", "mssql", "spark", "postgres", "staging"],
)
def mssql_ecom_to_stg():
    @task
    def verify_runtime_configuration() -> None:
        config = _required_environment()

        missing_jars = [path for path in JDBC_JARS.split(",") if not Path(path).is_file()]
        if missing_jars:
            raise RuntimeError(
                "Phase 04 JDBC driver files are missing: "
                + ", ".join(Path(path).name for path in missing_jars)
            )

        try:
            with socket.create_connection(
                (config["host"], int(config["port"])), timeout=5
            ):
                pass
        except OSError as exc:
            raise RuntimeError(
                "SQL Server preflight failed for the configured redacted endpoint"
            ) from exc

        LOGGER.info(
            "Phase 04 preflight succeeded: endpoint_class=%s, database=%s, "
            "credentials_present=true, jdbc_drivers_present=true",
            _endpoint_class(config["host"]),
            config["database"],
        )

    @task
    def prepare_phase04_tables() -> None:
        from airflow.providers.postgres.hooks.postgres import PostgresHook

        ddl = DDL_PATH.read_text(encoding="utf-8")
        hook = PostgresHook(postgres_conn_id="pg_dw")
        connection = hook.get_conn()
        try:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(ddl)
                    _validate_order_table_contract(cursor)
                    cursor.execute(
                        """
                        TRUNCATE TABLE
                            stg_edw.phase04_lazada_orders_load,
                            stg_edw.phase04_shopee_orders_load,
                            stg_edw.phase04_tiki_orders_load,
                            stg_edw.phase04_load_metrics
                        """
                    )
        finally:
            connection.close()
        LOGGER.info("Phase 04 PostgreSQL table contract validated and load state reset")

    @task
    def validate_and_publish(run_id: str) -> list[dict[str, int | str]]:
        from airflow.providers.postgres.hooks.postgres import PostgresHook

        publish_sql = PUBLISH_PATH.read_text(encoding="utf-8")
        hook = PostgresHook(postgres_conn_id="pg_dw")
        connection = hook.get_conn()
        try:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(publish_sql, {"dag_run_id": run_id})
                    cursor.execute(
                        """
                        SELECT
                            source_key,
                            source_count,
                            load_count,
                            published_count,
                            order_date_conversion_failures,
                            total_amount_conversion_failures
                        FROM stg_edw.phase04_batch_audit
                        WHERE dag_run_id = %s
                        ORDER BY source_key
                        """,
                        (run_id,),
                    )
                    rows = cursor.fetchall()
        finally:
            connection.close()

        if len(rows) != 3:
            raise RuntimeError("Phase 04 publish did not produce three audit rows")

        summaries = [
            {
                "source_key": row[0],
                "source_count": row[1],
                "load_count": row[2],
                "published_count": row[3],
                "order_date_conversion_failures": row[4],
                "total_amount_conversion_failures": row[5],
            }
            for row in rows
        ]
        for summary in summaries:
            LOGGER.info("Phase 04 publish metric: %s", summary)
        return summaries

    @task
    def cleanup_phase04_load_tables() -> None:
        from airflow.providers.postgres.hooks.postgres import PostgresHook

        hook = PostgresHook(postgres_conn_id="pg_dw")
        connection = hook.get_conn()
        try:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        TRUNCATE TABLE
                            stg_edw.phase04_lazada_orders_load,
                            stg_edw.phase04_shopee_orders_load,
                            stg_edw.phase04_tiki_orders_load,
                            stg_edw.phase04_load_metrics
                        """
                    )
        finally:
            connection.close()
        LOGGER.info("Phase 04 disposable load tables are clean")

    preflight = verify_runtime_configuration()
    prepared = prepare_phase04_tables()

    extract_tasks = [
        SparkSubmitOperator(
            task_id=f"extract_{source_key}_to_load",
            application=SPARK_APPLICATION,
            conn_id=SPARK_CONNECTION_ID,
            jars=JDBC_JARS,
            application_args=[
                "--source-key",
                source_key,
                "--run-id",
                "{{ run_id }}",
            ],
            name=f"phase04_{source_key}_to_postgres_load",
            verbose=False,
        )
        for source_key in SOURCE_KEYS
    ]

    published = validate_and_publish(run_id="{{ run_id }}")
    cleaned = cleanup_phase04_load_tables()

    preflight >> prepared >> extract_tasks >> published >> cleaned


mssql_ecom_to_stg()
