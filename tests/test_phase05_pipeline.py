from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DAG_PATH = REPO_ROOT / "airflow/dags/ecom_stg_to_raw_dw_dm.py"
SQL_ROOT = REPO_ROOT / "sql/phase05"


def load_phase05_dag_module():
    spec = importlib.util.spec_from_file_location("phase05_dag", DAG_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Phase05DqTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_phase05_dag_module()

    def valid_metrics(self):
        return [
            {
                "source": source,
                "row_count": 1,
                "invalid_order_id_count": 0,
                "invalid_order_date_count": 0,
                "invalid_amount_count": 0,
                "invalid_platform_count": 0,
                "duplicate_row_count": 0,
            }
            for source in ("lazada", "shopee", "tiki")
        ]

    def test_hard_dq_accepts_valid_critical_data(self):
        self.module._enforce_dq_metrics(self.valid_metrics())

    def test_hard_dq_rejects_bad_critical_data(self):
        metrics = self.valid_metrics()
        metrics[0]["invalid_order_id_count"] = 1
        with self.assertRaisesRegex(RuntimeError, "hard DQ gate failed"):
            self.module._enforce_dq_metrics(metrics)

    def test_hard_dq_rejects_missing_platform(self):
        with self.assertRaisesRegex(RuntimeError, "source coverage failed"):
            self.module._enforce_dq_metrics(self.valid_metrics()[:2])


class Phase05SqlContractTests(unittest.TestCase):
    def read_sql(self, name: str) -> str:
        return (SQL_ROOT / name).read_text(encoding="utf-8")

    def test_no_drop_or_cascade_statements(self):
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(SQL_ROOT.glob("*.sql"))
        ).upper()
        self.assertNotIn("DROP ", combined)
        self.assertNotIn("CASCADE", combined)

    def test_raw_insert_uses_explicit_contract_and_upsert(self):
        sql_text = self.read_sql("002_upsert_raw_orders.sql")
        self.assertIn("INSERT INTO raw.orders_raw (", sql_text)
        for column in ("source", "order_code", "payload", "src_event_ts"):
            self.assertIn(column, sql_text)
        self.assertIn("ON CONFLICT (source, order_code) DO UPDATE", sql_text)

    def test_raw_dedup_is_explicit_and_preserves_variants(self):
        sql_text = self.read_sql("002_upsert_raw_orders.sql")
        self.assertIn("candidate_hash", sql_text)
        self.assertIn("distinct_variant_count", sql_text)
        self.assertIn("'_variants'", sql_text)
        self.assertIn("'selection_rule'", sql_text)

    def test_dw_reads_raw_not_staging(self):
        sql_text = self.read_sql("003_upsert_dimensions_and_fact.sql")
        self.assertIn("raw.orders_raw", sql_text)
        self.assertNotIn("stg_edw", sql_text)
        self.assertIn("ON CONFLICT (platform_key, order_nk) DO UPDATE", sql_text)

    def test_materialized_view_exists_and_is_indexed_before_refresh(self):
        sql_text = self.read_sql("004_daily_sales_materialized_view.sql")
        create_pos = sql_text.index("CREATE MATERIALIZED VIEW IF NOT EXISTS")
        index_pos = sql_text.index("CREATE UNIQUE INDEX IF NOT EXISTS")
        refresh_pos = sql_text.index("REFRESH MATERIALIZED VIEW")
        self.assertLess(create_pos, index_pos)
        self.assertLess(index_pos, refresh_pos)

    def test_dag_uses_airflow_3_sdk(self):
        dag_text = DAG_PATH.read_text(encoding="utf-8")
        self.assertIn("from airflow.sdk import dag, task", dag_text)
        self.assertNotIn("from airflow import DAG", dag_text)


if __name__ == "__main__":
    unittest.main()
