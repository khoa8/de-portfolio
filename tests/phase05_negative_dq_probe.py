"""Isolated PostgreSQL proof that Phase 05 rejects bad critical staging data."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from airflow.providers.postgres.hooks.postgres import PostgresHook


DAG_PATH = Path("/opt/airflow/dags/ecom_stg_to_raw_dw_dm.py")


def load_phase05_module():
    spec = importlib.util.spec_from_file_location("phase05_negative_probe", DAG_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> None:
    phase05 = load_phase05_module()
    hook = PostgresHook(postgres_conn_id="pg_dw")
    connection = hook.get_conn()
    connection.autocommit = False
    try:
        with connection.cursor() as cursor:
            for source in ("lazada", "shopee", "tiki"):
                cursor.execute(
                    f"""
                    CREATE TEMP TABLE phase05_bad_{source} (
                        LIKE stg_edw.e01_{source}_orders INCLUDING ALL
                    ) ON COMMIT DROP
                    """
                )

            cursor.execute(
                """
                INSERT INTO phase05_bad_lazada (
                    order_id, order_date, order_status,
                    buyer_name, total_amount, platform
                ) VALUES (
                    NULL, TIMESTAMP '2026-01-01 00:00:00',
                    'probe', NULL, 1.00, 'lazada'
                )
                """
            )
            for source in ("shopee", "tiki"):
                cursor.execute(
                    f"""
                    INSERT INTO phase05_bad_{source} (
                        order_id, order_date, order_status,
                        buyer_name, total_amount, platform
                    ) VALUES (
                        'probe-order', TIMESTAMP '2026-01-01 00:00:00',
                        'probe', NULL, 1.00, %s
                    )
                    """,
                    (source,),
                )

            specs = tuple(
                (source, "pg_temp", f"phase05_bad_{source}")
                for source in ("lazada", "shopee", "tiki")
            )
            metrics = phase05._collect_dq_metrics(cursor, specs)
            try:
                phase05._enforce_dq_metrics(metrics)
            except RuntimeError:
                print("negative_dq_result=expected_failure")
            else:
                raise AssertionError("Phase 05 hard DQ gate accepted bad critical data")
    finally:
        connection.rollback()
        connection.close()

    print("negative_dq_persistent_writes=0")


if __name__ == "__main__":
    main()
