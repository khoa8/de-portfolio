from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


class Phase08PortfolioContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root_readme = read("README.md")
        cls.architecture = read("docs/ARCHITECTURE.md")
        cls.verification = read("docs/VERIFICATION.md")
        cls.demo = read("docs/DEMO.md")
        cls.kafka_readme = read("kafka/README.md")
        cls.compose = read("airflow/docker-compose.yaml")
        cls.streaming_compose = read("airflow/docker-compose.streaming.yaml")
        cls.workflow = read(".github/workflows/portfolio-ci.yml")

    def test_landing_page_contains_portfolio_contract(self) -> None:
        for heading in (
            "## The problem",
            "## Architecture",
            "## Technology stack",
            "## Verified results",
            "## Quick start",
            "## Documentation",
        ):
            self.assertIn(heading, self.root_readme)
        for link in (
            "docs/ARCHITECTURE.md",
            "docs/VERIFICATION.md",
            "docs/DEMO.md",
            "docs/CURRENT_STATE.md",
        ):
            self.assertIn(link, self.root_readme)
        self.assertIn(
            "git clone https://github.com/khoa8/de-portfolio.git",
            self.root_readme,
        )

    def test_architecture_matches_compose_and_active_dags(self) -> None:
        self.assertIn("AIRFLOW__CORE__EXECUTOR: LocalExecutor", self.compose)
        self.assertIn("postgres:5432/ecom_dw", self.architecture)
        for binding in (
            '"127.0.0.1:${MYSQL_CDC_HOST_PORT:-3307}:3306"',
            '"127.0.0.1:8083:8083"',
            '"127.0.0.1:8082:8080"',
        ):
            self.assertIn(binding, self.streaming_compose)
        for dag_id in (
            "phase03_postgres_smoke",
            "mssql_ecom_to_stg",
            "ecom_stg_to_raw_dw_dm",
            "postgres_to_gcs_bigquery",
            "mysql_cdc_to_postgres",
        ):
            self.assertIn(dag_id, self.architecture)

    def test_verification_summary_matches_verified_state(self) -> None:
        current_state = read("docs/CURRENT_STATE.md")
        for evidence in (
            "245,675",
            "1,336",
            "50,228,062,824",
            "9999999999999999.99",
        ):
            self.assertIn(evidence, self.verification)
        for raw_value in ("245675", "1336", "50228062824", "9999999999999999.99"):
            self.assertIn(raw_value, current_state)

    def test_demo_is_safe_and_uses_canonical_commands(self) -> None:
        self.assertIn("scripts/ci/validate_repository.py", self.demo)
        self.assertIn("--profile phase07 config --quiet", self.demo)
        self.assertIn("phase03_postgres_smoke", self.demo)
        self.assertNotIn("down -v", self.demo)
        self.assertNotIn("gcloud ", self.demo)
        self.assertNotIn("bq ", self.demo)

    def test_kafka_readme_describes_only_verified_active_stack(self) -> None:
        self.assertIn("apache/kafka:3.9.1", self.kafka_readme)
        self.assertIn("de_network", self.kafka_readme)
        self.assertIn("phase07-mysql-orders-cdc", self.kafka_readme)
        self.assertIn("availableNow", self.kafka_readme)
        self.assertIn("Legacy artifacts", self.kafka_readme)
        self.assertNotIn("Bitnami", self.kafka_readme)
        self.assertNotIn("`de-net`", self.kafka_readme)
        self.assertNotIn("startingOffsets=latest", self.kafka_readme)

    def test_legacy_connector_config_contains_only_placeholder_password(self) -> None:
        config = json.loads(read("airflow/config/mysql_source.json"))
        connector = config.get("config", config)
        self.assertEqual(connector["database.password"], "change_me")

    def test_legacy_dag_quarantine_is_exact(self) -> None:
        ignored = {
            line.strip()
            for line in read("airflow/dags/.airflowignore").splitlines()
            if line.strip()
        }
        self.assertEqual(
            ignored,
            {
                "csv_to_postgres.py",
                "ggsheet-to-postgres-upsert.py",
                "ggsheet-to-postgres.py",
                "mysql_to_postgres.py",
                "quick_hello_pipeline.py",
                "realtime_orders.py",
                "spark_csv_to_postgres.py",
            },
        )

    def test_ci_is_offline_and_secret_free(self) -> None:
        for required in (
            "validate_repository.py",
            "compileall",
            "test_phase08_repository",
            "config --quiet",
            "git diff --check",
        ):
            self.assertIn(required, self.workflow)
        for forbidden in (
            "secrets.",
            "gcloud ",
            "bq ",
            "docker compose up",
            "docker build",
        ):
            self.assertNotIn(forbidden, self.workflow)


if __name__ == "__main__":
    unittest.main()
