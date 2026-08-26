"""Phase 05: PostgreSQL staging to RAW, dimensional warehouse, and data mart."""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import Iterable, Sequence

import pendulum
from psycopg2 import sql

from airflow.sdk import dag, task


LOGGER = logging.getLogger(__name__)

DAG_ID = "ecom_stg_to_raw_dw_dm"
POSTGRES_CONNECTION_ID = "pg_dw"
SQL_ROOT = Path("/opt/airflow/sql/phase05")
DDL_PATH = SQL_ROOT / "001_warehouse_objects.sql"
RAW_PATH = SQL_ROOT / "002_upsert_raw_orders.sql"
DW_PATH = SQL_ROOT / "003_upsert_dimensions_and_fact.sql"
DM_PATH = SQL_ROOT / "004_daily_sales_materialized_view.sql"
VERIFY_PATH = SQL_ROOT / "005_verify_and_audit.sql"

STAGING_SOURCES = (
    ("lazada", "stg_edw", "e01_lazada_orders"),
    ("shopee", "stg_edw", "e01_shopee_orders"),
    ("tiki", "stg_edw", "e01_tiki_orders"),
)
EXPECTED_SOURCES = frozenset(source for source, _, _ in STAGING_SOURCES)


def _collect_dq_metrics(
    cursor,
    source_tables: Sequence[tuple[str, str, str]] = STAGING_SOURCES,
) -> list[dict[str, int | str]]:
    metrics: list[dict[str, int | str]] = []
    query = sql.SQL(
        """
        SELECT
            %s::TEXT AS source,
            COUNT(*)::BIGINT AS row_count,
            COUNT(*) FILTER (
                WHERE order_id IS NULL OR BTRIM(order_id) = ''
            )::BIGINT AS invalid_order_id_count,
            COUNT(*) FILTER (
                WHERE order_date IS NULL
            )::BIGINT AS invalid_order_date_count,
            COUNT(*) FILTER (
                WHERE total_amount IS NULL
            )::BIGINT AS invalid_amount_count,
            COUNT(*) FILTER (
                WHERE platform IS DISTINCT FROM %s
            )::BIGINT AS invalid_platform_count,
            (
                COUNT(*) - COUNT(DISTINCT BTRIM(order_id))
            )::BIGINT AS duplicate_row_count
        FROM {}
        """
    )

    for source, schema_name, table_name in source_tables:
        cursor.execute(
            query.format(sql.Identifier(schema_name, table_name)),
            (source, source),
        )
        row = cursor.fetchone()
        metrics.append(
            {
                "source": row[0],
                "row_count": row[1],
                "invalid_order_id_count": row[2],
                "invalid_order_date_count": row[3],
                "invalid_amount_count": row[4],
                "invalid_platform_count": row[5],
                "duplicate_row_count": row[6],
            }
        )
    return metrics


def _enforce_dq_metrics(metrics: Iterable[dict[str, int | str]]) -> None:
    rows = list(metrics)
    sources = {str(row["source"]) for row in rows}
    if sources != EXPECTED_SOURCES:
        missing = sorted(EXPECTED_SOURCES - sources)
        unexpected = sorted(sources - EXPECTED_SOURCES)
        raise RuntimeError(
            "Phase 05 DQ source coverage failed; "
            f"missing={missing}, unexpected={unexpected}"
        )

    empty_sources = sorted(
        str(row["source"]) for row in rows if int(row["row_count"]) == 0
    )
    critical_fields = (
        "invalid_order_id_count",
        "invalid_order_date_count",
        "invalid_amount_count",
        "invalid_platform_count",
    )
    invalid = {
        str(row["source"]): {
            field: int(row[field])
            for field in critical_fields
            if int(row[field]) > 0
        }
        for row in rows
    }
    invalid = {source: counts for source, counts in invalid.items() if counts}
    if empty_sources or invalid:
        raise RuntimeError(
            "Phase 05 hard DQ gate failed; "
            f"empty_sources={empty_sources}, invalid_critical_counts={invalid}"
        )


def _execute_sql_file(path: Path, parameters: dict[str, str] | None = None) -> None:
    from airflow.providers.postgres.hooks.postgres import PostgresHook

    statement = path.read_text(encoding="utf-8")
    hook = PostgresHook(postgres_conn_id=POSTGRES_CONNECTION_ID)
    connection = hook.get_conn()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(statement, parameters)
    finally:
        connection.close()


def _validate_object_contract(cursor) -> None:
    cursor.execute(
        """
        SELECT table_schema, table_name, column_name, data_type
        FROM information_schema.columns
        WHERE (table_schema, table_name) IN (
            ('raw', 'orders_raw'),
            ('dw', 'dim_platform'),
            ('dw', 'dim_customer'),
            ('dw', 'dim_date'),
            ('dw', 'fact_orders'),
            ('dw', 'phase05_batch_audit')
        )
        """
    )
    actual = {
        (schema_name, table_name, column_name, data_type)
        for schema_name, table_name, column_name, data_type in cursor.fetchall()
    }
    required = {
        ("raw", "orders_raw", "source", "text"),
        ("raw", "orders_raw", "order_code", "text"),
        ("raw", "orders_raw", "payload", "jsonb"),
        (
            "raw",
            "orders_raw",
            "src_event_ts",
            "timestamp with time zone",
        ),
        ("dw", "dim_platform", "platform_key", "smallint"),
        ("dw", "dim_customer", "customer_key", "bigint"),
        ("dw", "dim_date", "date_key", "integer"),
        ("dw", "fact_orders", "order_nk", "text"),
        ("dw", "phase05_batch_audit", "dag_run_id", "text"),
    }
    missing = sorted(required - actual)
    if missing:
        raise RuntimeError(f"Phase 05 object contract is missing fields: {missing}")


@dag(
    dag_id=DAG_ID,
    description="Idempotent STG to RAW to DW to daily-sales data mart",
    schedule=None,
    start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=1)},
    tags=["phase05", "postgres", "raw", "dw", "dm"],
)
def ecom_stg_to_raw_dw_dm():
    @task
    def hard_dq_gate() -> list[dict[str, int | str]]:
        from airflow.providers.postgres.hooks.postgres import PostgresHook

        hook = PostgresHook(postgres_conn_id=POSTGRES_CONNECTION_ID)
        connection = hook.get_conn()
        try:
            with connection.cursor() as cursor:
                metrics = _collect_dq_metrics(cursor)
        finally:
            connection.close()

        _enforce_dq_metrics(metrics)
        for metric in metrics:
            LOGGER.info("Phase 05 staging DQ metric: %s", metric)
        return metrics

    @task
    def prepare_phase05_objects() -> None:
        from airflow.providers.postgres.hooks.postgres import PostgresHook

        _execute_sql_file(DDL_PATH)
        hook = PostgresHook(postgres_conn_id=POSTGRES_CONNECTION_ID)
        connection = hook.get_conn()
        try:
            with connection.cursor() as cursor:
                _validate_object_contract(cursor)
        finally:
            connection.close()
        LOGGER.info("Phase 05 PostgreSQL object contract is ready")

    @task
    def upsert_raw_orders() -> None:
        _execute_sql_file(RAW_PATH)
        LOGGER.info("Phase 05 RAW upsert completed")

    @task
    def upsert_dimensions_and_fact() -> None:
        _execute_sql_file(DW_PATH)
        LOGGER.info("Phase 05 dimensions and fact upserts completed")

    @task
    def refresh_daily_sales() -> None:
        _execute_sql_file(DM_PATH)
        LOGGER.info("Phase 05 daily-sales materialized view refreshed")

    @task
    def verify_and_audit(run_id: str) -> dict[str, int | str]:
        from airflow.providers.postgres.hooks.postgres import PostgresHook

        _execute_sql_file(VERIFY_PATH, {"dag_run_id": run_id})
        hook = PostgresHook(postgres_conn_id=POSTGRES_CONNECTION_ID)
        connection = hook.get_conn()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        dag_run_id,
                        staging_row_count,
                        staging_distinct_order_count,
                        raw_order_count,
                        fact_order_count,
                        dm_group_count,
                        dm_order_count,
                        dw_total_sales,
                        dm_total_sales
                    FROM dw.phase05_batch_audit
                    WHERE dag_run_id = %s
                    """,
                    (run_id,),
                )
                row = cursor.fetchone()
        finally:
            connection.close()

        if row is None:
            raise RuntimeError("Phase 05 verification did not persist an audit row")
        summary = {
            "dag_run_id": row[0],
            "staging_row_count": row[1],
            "staging_distinct_order_count": row[2],
            "raw_order_count": row[3],
            "fact_order_count": row[4],
            "dm_group_count": row[5],
            "dm_order_count": row[6],
            "dw_total_sales": str(row[7]),
            "dm_total_sales": str(row[8]),
        }
        LOGGER.info("Phase 05 verification summary: %s", summary)
        return summary

    dq = hard_dq_gate()
    objects = prepare_phase05_objects()
    raw = upsert_raw_orders()
    warehouse = upsert_dimensions_and_fact()
    mart = refresh_daily_sales()
    verified = verify_and_audit(run_id="{{ run_id }}")

    dq >> objects >> raw >> warehouse >> mart >> verified


ecom_stg_to_raw_dw_dm()
