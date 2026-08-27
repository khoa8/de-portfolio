from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DAG_PATH = REPO_ROOT / "airflow/dags/postgres_to_gcs_bigquery.py"
DOCKERFILE_PATH = REPO_ROOT / "airflow/Dockerfile"
COMPOSE_PATH = REPO_ROOT / "airflow/docker-compose.yaml"


def load_phase06_module():
    spec = importlib.util.spec_from_file_location("phase06_dag", DAG_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Phase06ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_phase06_module()
        cls.dag_text = DAG_PATH.read_text(encoding="utf-8")

    def test_airflow_3_public_authoring_interface(self) -> None:
        self.assertIn("from airflow.sdk import dag, get_current_context, task", self.dag_text)
        self.assertNotIn("from airflow import DAG", self.dag_text)

    def test_run_objects_are_unique_and_exact(self) -> None:
        first = self.module._object_name(
            "phase06_verify_20260827T010000Z_run1",
            self.module.TABLE_SPECS["fact_orders"],
        )
        second = self.module._object_name(
            "phase06_verify_20260827T010500Z_run2",
            self.module.TABLE_SPECS["fact_orders"],
        )
        self.assertNotEqual(first, second)
        self.assertNotIn("*", first)
        self.assertNotIn("?", first)

    def test_explicit_schemas_partitioning_and_clustering(self) -> None:
        specs = self.module.TABLE_SPECS
        self.assertEqual(set(specs), {"dim_platform", "fact_orders", "daily_sales"})
        self.assertIsNone(specs["dim_platform"].partition_field)
        self.assertEqual(specs["fact_orders"].partition_field, "order_date")
        self.assertEqual(specs["daily_sales"].partition_field, "order_date")
        self.assertEqual(specs["fact_orders"].cluster_fields, ("platform_key",))
        self.assertEqual(specs["daily_sales"].cluster_fields, ("platform_name",))
        for spec in specs.values():
            self.assertTrue(spec.schema)
            self.assertTrue(all(mode in {"REQUIRED", "NULLABLE"} for _, _, mode in spec.schema))

    def test_ndjson_validation_rejects_metric_mismatch(self) -> None:
        spec = self.module.TABLE_SPECS["dim_platform"]
        row = {"platform_key": 1, "platform_code": "lazada", "platform_name": "Lazada"}
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
            handle.flush()
            bad_metrics = {
                "row_count": 2,
                "order_count": 2,
                "total": "0",
                "platforms": {
                    "lazada": {"row_count": 2, "order_count": 2, "total": "0"}
                },
            }
            with self.assertRaisesRegex(RuntimeError, "metrics differ"):
                self.module._validate_ndjson(Path(handle.name), spec, bad_metrics)

    def test_numeric_reconciliation_is_scale_independent(self) -> None:
        self.assertEqual(Decimal("16147639680.00"), Decimal("16147639680"))

    def test_fact_export_is_enriched_from_dimensions(self) -> None:
        sql = self.module.TABLE_SPECS["fact_orders"].sql
        self.assertIn("dw.dim_platform", sql)
        self.assertIn("dw.dim_customer", sql)
        self.assertIn("dw.dim_date", sql)
        fields = {name for name, _, _ in self.module.TABLE_SPECS["fact_orders"].schema}
        self.assertTrue(
            {"platform_code", "platform_name", "customer_natural", "order_date"} <= fields
        )

    def test_provider_is_pinned_and_adc_mount_is_read_only(self) -> None:
        dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")
        compose = COMPOSE_PATH.read_text(encoding="utf-8")
        self.assertIn("apache-airflow-providers-google==17.0.0", dockerfile)
        self.assertIn("application_default_credentials.json:ro", compose)
        self.assertIn("GOOGLE_APPLICATION_CREDENTIALS", compose)
        self.assertNotIn("service_account", compose.lower())

    def test_bigquery_schema_adapter_uses_client_constructor_contract(self) -> None:
        self.assertIn(
            'bigquery.SchemaField(field["name"], field["type"], mode=field["mode"])',
            self.dag_text,
        )
        self.assertNotIn("AS groups", self.dag_text)

    def test_only_three_canonical_write_truncate_calls(self) -> None:
        self.assertEqual(self.dag_text.count("WriteDisposition.WRITE_TRUNCATE"), 1)
        self.assertIn("All three canonical load jobs", self.dag_text)


if __name__ == "__main__":
    unittest.main()
