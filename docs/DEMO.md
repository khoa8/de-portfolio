# Short Demo Guide

This walkthrough presents the verified portfolio without requiring SQL Server,
GCP, or any new cloud operation. It does not reset databases, topics, volumes,
or checkpoints.

## 1. Explain the architecture (2 minutes)

Open the [architecture overview](ARCHITECTURE.md) and describe the two paths:

- batch: SQL Server -> Spark -> PostgreSQL STG/RAW/DW/DM -> GCS -> BigQuery;
- streaming: MySQL -> Debezium -> Kafka -> Spark -> PostgreSQL CDC.

Emphasize the `airflow`/`ecom_dw` database boundary, hard DQ gate, stable keys,
run-specific GCS objects, and Kafka topic-partition-offset identity.

## 2. Run offline release checks (2 minutes)

From the repository root:

```bash
python3 scripts/ci/validate_repository.py

PYTHONPYCACHEPREFIX=/tmp/de_portfolio_ci_pycache \
python3 -m unittest \
  tests.test_phase04_spark_job.Phase04ConfigurationTests \
  tests.test_phase07_streaming \
  tests.test_phase08_repository

docker compose --env-file airflow/.env.example \
  -f airflow/docker-compose.batch.yaml \
  -f airflow/docker-compose.yaml \
  config --quiet

docker compose --env-file airflow/.env.example \
  -f airflow/docker-compose.batch.yaml \
  -f airflow/docker-compose.yaml \
  -f airflow/docker-compose.streaming.yaml \
  --profile phase07 config --quiet
```

These commands do not read `airflow/.env`, start services, or access cloud
resources.

## 3. Show verified results (2 minutes)

Use [Verification Summary](VERIFICATION.md) to show:

- 245,675 warehouse orders and zero orphan dimension keys;
- equal DW/DM totals;
- two idempotent same-day BigQuery export runs;
- 8 unique CDC offsets with update, delete, tombstone, and malformed handling;
- exact preservation of the large `DECIMAL(18,2)` probe.

## 4. Optional local runtime proof (3 minutes)

Only if the already-configured local stack is running:

```bash
docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'

curl --fail --silent --output /dev/null \
  http://127.0.0.1:8080/api/v2/version

curl --fail --silent \
  http://127.0.0.1:8083/connectors/phase07-mysql-orders-cdc/status
```

The connector status endpoint is safe; do not request or display its resolved
configuration. For a new environment, follow the Phase 03 or Phase 07 runbook
instead of improvising startup commands.

The read-only database smoke can be triggered through the running scheduler:

```bash
docker compose --env-file airflow/.env \
  -f airflow/docker-compose.batch.yaml \
  -f airflow/docker-compose.yaml \
  exec -T airflow-scheduler \
  airflow dags trigger phase03_postgres_smoke \
  --run-id phase08_demo_smoke
```

Do not show `.env`, Airflow auth files, connector configuration, tokens, or
credential-bearing URIs during a demo.

## 5. Close with reproducibility and safety (1 minute)

Point to the phase runbooks and explain that runtime evidence is kept separate
from CI's offline contract checks. Stop services with the phase-specific
`docker compose stop` command if needed, but never delete volumes as part of a
demo.
