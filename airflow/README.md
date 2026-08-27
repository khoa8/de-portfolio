# Airflow local runtime

The verified orchestration runtime uses Apache Airflow 3.0.4 with
`LocalExecutor` and SimpleAuthManager on Docker Desktop. Airflow shares the
Phase 02 PostgreSQL 16 service; the base stack does not start Redis, Celery,
Kafka, Debezium, MySQL, or a second PostgreSQL instance.

Use both Compose files as one project:

```bash
cd airflow
docker compose --env-file .env \
  -f docker-compose.batch.yaml \
  -f docker-compose.yaml \
  config --quiet
```

The canonical build, startup, login, verification, restart, and troubleshooting
procedure is [Phase 03 — Airflow setup](../docs/runbooks/03-airflow-setup.md).
Later phases add DAGs to this same runtime; each phase's external services and
data contracts are documented in its own runbook.

Key invariants:

- `airflow` is the Airflow metadata database.
- `ecom_dw` is the business database.
- `pg_dw` targets `postgres:5432/ecom_dw` inside Docker.
- The seven legacy DAGs remain source-controlled but are quarantined by `dags/.airflowignore`.
- Active verified repository DAGs are `phase03_postgres_smoke`,
  `mssql_ecom_to_stg`, `ecom_stg_to_raw_dw_dm`,
  `postgres_to_gcs_bigquery`, and `mysql_cdc_to_postgres`.
- `.env`, logs, generated auth material, and generated `airflow.cfg` must not be committed.

The streaming overlay is optional:

```bash
docker compose --env-file .env \
  -f docker-compose.batch.yaml \
  -f docker-compose.yaml \
  -f docker-compose.streaming.yaml \
  --profile phase07 config --quiet
```

See the repository [landing page](../README.md),
[architecture overview](../docs/ARCHITECTURE.md), and
[verification summary](../docs/VERIFICATION.md) for the complete portfolio.

Never use `docker compose down -v` for this project: it deletes persistent database and Airflow auth volumes.
