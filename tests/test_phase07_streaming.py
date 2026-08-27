from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DAG_PATH = REPO_ROOT / "airflow/dags/mysql_cdc_to_postgres.py"
SPARK_PATH = REPO_ROOT / "spark/mysql_cdc_to_postgres.py"
COMPOSE_PATH = REPO_ROOT / "airflow/docker-compose.streaming.yaml"
TOPIC_BOOTSTRAP_PATH = REPO_ROOT / "airflow/scripts/phase07_init_topics.sh"
CONNECTOR_BOOTSTRAP_PATH = (
    REPO_ROOT / "airflow/scripts/phase07_bootstrap_connector.py"
)
MYSQL_BOOTSTRAP_PATH = REPO_ROOT / "airflow/scripts/phase07_init_mysql.sh"
SQL_ROOT = REPO_ROOT / "sql/phase07"


def load_spark_module():
    spec = importlib.util.spec_from_file_location("phase07_spark", SPARK_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Phase07DecodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_spark_module()
        cls.kafka_timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def envelope(self, op: str, before=None, after=None) -> str:
        return json.dumps(
            {"before": before, "after": after, "op": op, "ts_ms": 1767225600000}
        )

    def test_read_create_update_delete_are_supported(self) -> None:
        row = {
            "id": 700001,
            "customer_name": "Phase 07",
            "amount": 42.5,
            "status": "new",
            "updated_at": 1767225600000,
        }
        expected = {"r": "read", "c": "create", "u": "update", "d": "delete"}
        for op, event_kind in expected.items():
            before = row if op in {"u", "d"} else None
            after = None if op == "d" else row
            decoded = self.module.decode_record(
                '{"id":700001}',
                self.envelope(op, before=before, after=after),
                self.kafka_timestamp,
            )
            self.assertEqual(decoded["event_kind"], event_kind)
            self.assertEqual(decoded["source_order_id"], 700001)

    def test_tombstone_is_preserved(self) -> None:
        decoded = self.module.decode_record(
            '{"id":700001}', None, self.kafka_timestamp
        )
        self.assertEqual(decoded["event_kind"], "tombstone")
        self.assertEqual(decoded["source_order_id"], 700001)

    def test_malformed_event_is_classified_without_exception(self) -> None:
        decoded = self.module.decode_record(None, "not-json", self.kafka_timestamp)
        self.assertEqual(decoded["event_kind"], "malformed")
        self.assertTrue(decoded["malformed_reason"].startswith("invalid_json:"))

    def test_large_decimal_string_preserves_exact_scale(self) -> None:
        amount = "9999999999999999.99"
        row = {
            "id": 700073,
            "customer_name": "Precision probe",
            "amount": amount,
            "status": "precision_probe",
            "updated_at": 1767225600000,
        }
        decoded = self.module.decode_record(
            '{"id":700073}',
            self.envelope("c", after=row),
            self.kafka_timestamp,
        )
        self.assertEqual(decoded["after_payload"]["amount"], amount)
        self.assertEqual(
            self.module._decimal(decoded["current_payload"]["amount"]),
            Decimal("9999999999999999.99"),
        )


class Phase07ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dag = DAG_PATH.read_text(encoding="utf-8")
        cls.spark = SPARK_PATH.read_text(encoding="utf-8")
        cls.compose = COMPOSE_PATH.read_text(encoding="utf-8")
        cls.topic_bootstrap = TOPIC_BOOTSTRAP_PATH.read_text(encoding="utf-8")
        cls.connector_bootstrap = CONNECTOR_BOOTSTRAP_PATH.read_text(encoding="utf-8")
        cls.mysql_bootstrap = MYSQL_BOOTSTRAP_PATH.read_text(encoding="utf-8")
        cls.source_sql = (SQL_ROOT / "001_mysql_source.sql").read_text(
            encoding="utf-8"
        )
        cls.sink_sql = (SQL_ROOT / "002_postgres_sink.sql").read_text(
            encoding="utf-8"
        )

    def test_airflow_3_authoring_and_bounded_default(self) -> None:
        self.assertIn("from airflow.sdk import dag, task", self.dag)
        self.assertNotIn("from airflow import DAG", self.dag)
        self.assertIn('"availableNow"', self.dag)

    def test_compose_is_phase_scoped_and_pinned_for_arm64_images(self) -> None:
        for image in (
            "mysql:8.4.6",
            "apache/kafka:3.9.1",
            "quay.io/debezium/connect:3.2.4.Final",
            "provectuslabs/kafka-ui:v0.7.2",
        ):
            self.assertIn(image, self.compose)
        self.assertIn("profiles: [phase07]", self.compose)
        self.assertNotIn("redis:", self.compose)
        self.assertNotIn("airflow-worker:", self.compose)

    def test_topics_are_idempotent_and_internal_topics_are_compact(self) -> None:
        self.assertIn("--if-not-exists", self.topic_bootstrap)
        self.assertIn("cleanup.policy=${cleanup_policy}", self.topic_bootstrap)
        self.assertIn("phase07_connect_offsets", self.topic_bootstrap)
        self.assertIn("ensure_topic phase07_schema_history delete", self.topic_bootstrap)
        self.assertNotIn("--delete", self.topic_bootstrap)
        self.assertNotIn("reset", self.topic_bootstrap.lower())

    def test_connector_secret_is_environment_backed(self) -> None:
        self.assertIn('_required("MYSQL_CDC_PASSWORD")', self.connector_bootstrap)
        self.assertIn('"database.password": password', self.connector_bootstrap)
        self.assertNotIn('"database.password": "', self.connector_bootstrap)
        self.assertIn('"tombstones.on.delete": "true"', self.connector_bootstrap)
        self.assertIn('"database.user": "debezium"', self.connector_bootstrap)
        self.assertIn('"decimal.handling.mode": "string"', self.connector_bootstrap)
        self.assertNotIn('"decimal.handling.mode": "double"', self.connector_bootstrap)

    def test_host_tools_are_bound_to_loopback_only(self) -> None:
        for binding in (
            '"127.0.0.1:${MYSQL_CDC_HOST_PORT:-3307}:3306"',
            '"127.0.0.1:8083:8083"',
            '"127.0.0.1:8082:8080"',
        ):
            self.assertIn(binding, self.compose)

    def test_debezium_user_is_created_without_image_auto_grants(self) -> None:
        self.assertNotIn("      MYSQL_USER:", self.compose)
        self.assertNotIn("      MYSQL_PASSWORD:", self.compose)
        self.assertIn("CREATE USER IF NOT EXISTS 'debezium'@'%'", self.mysql_bootstrap)
        self.assertIn("ALTER USER 'debezium'@'%'", self.mysql_bootstrap)
        self.assertIn("REVOKE ALL PRIVILEGES, GRANT OPTION", self.mysql_bootstrap)
        self.assertIn("GRANT SELECT ON \\`phase07_shop\\`.*", self.mysql_bootstrap)
        self.assertNotIn("GRANT SELECT ON *.*", self.mysql_bootstrap)
        self.assertNotIn("GRANT SELECT ON *.*", self.source_sql)

    def test_streaming_contract_avoids_legacy_failure_modes(self) -> None:
        self.assertIn('.option("startingOffsets", "earliest")', self.spark)
        self.assertIn("availableNow=True", self.spark)
        self.assertIn("processingTime=args.processing_time", self.spark)
        self.assertIn("foreachPartition", self.spark)
        self.assertNotIn("toPandas", self.spark)
        self.assertIn(
            '"/opt/airflow/checkpoints/mysql_orders"', self.spark
        )
        self.assertIn('startswith("/opt/airflow/logs")', self.spark)

    def test_sink_is_append_only_and_current_state_is_offset_guarded(self) -> None:
        self.assertIn("CREATE TABLE IF NOT EXISTS cdc.order_events", self.sink_sql)
        self.assertIn(
            "PRIMARY KEY (kafka_topic, kafka_partition, kafka_offset)",
            self.sink_sql,
        )
        self.assertIn("CREATE TABLE IF NOT EXISTS cdc.orders_current", self.sink_sql)
        self.assertIn("is_deleted BOOLEAN NOT NULL", self.sink_sql)
        self.assertIn(
            "cdc.orders_current.kafka_offset < EXCLUDED.kafka_offset", self.spark
        )
        self.assertNotIn("DROP ", self.sink_sql.upper())
        self.assertNotIn("CASCADE", self.sink_sql.upper())


if __name__ == "__main__":
    unittest.main()
