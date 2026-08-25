"""Read-only Phase 03 verification of the ecom_dw business database."""

from __future__ import annotations

import pendulum

from airflow.sdk import dag, task


@dag(
    dag_id="phase03_postgres_smoke",
    description="Verify pg_dw reaches the expected ecom_dw database and RAW table",
    schedule=None,
    start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
    catchup=False,
    tags=["phase03", "smoke"],
)
def phase03_postgres_smoke():
    @task
    def verify_business_database() -> None:
        from airflow.providers.postgres.hooks.postgres import PostgresHook

        database_name, raw_schema_exists, orders_table_exists = PostgresHook(
            postgres_conn_id="pg_dw"
        ).get_first(
            """
            SELECT
                current_database(),
                EXISTS (
                    SELECT 1
                    FROM information_schema.schemata
                    WHERE schema_name = 'raw'
                ),
                to_regclass('raw.orders_raw') IS NOT NULL
            """
        )

        if (database_name, raw_schema_exists, orders_table_exists) != ("ecom_dw", True, True):
            raise RuntimeError(
                "pg_dw did not reach the expected ecom_dw database objects: "
                f"database={database_name!r}, raw_schema={raw_schema_exists!r}, "
                f"orders_table={orders_table_exists!r}"
            )

        print(
            "Phase 03 smoke verification succeeded: "
            "database=ecom_dw, raw_schema=true, orders_table=true"
        )

    verify_business_database()


phase03_postgres_smoke()
