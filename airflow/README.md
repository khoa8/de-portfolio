# Airflow local runtime

Phase 03 runs Apache Airflow 3.0.4 with `LocalExecutor` on Docker Desktop. Airflow shares the Phase 02 PostgreSQL 16 service; it does not start Redis, Celery, Kafka, Debezium, MySQL, or a second PostgreSQL instance.

Use both Compose files as one project:

```bash
cd airflow
docker compose --env-file .env \
  -f docker-compose.batch.yaml \
  -f docker-compose.yaml \
  config --quiet
```

The canonical build, startup, login, verification, restart, and troubleshooting procedure is [Phase 03 — Airflow setup](../docs/runbooks/03-airflow-setup.md).

Key invariants:

- `airflow` is the Airflow metadata database.
- `ecom_dw` is the business database.
- `pg_dw` targets `postgres:5432/ecom_dw` inside Docker.
- The seven legacy DAGs remain source-controlled but are quarantined by `dags/.airflowignore`.
- `phase03_postgres_smoke` is the only active repository DAG in this phase.
- `.env`, logs, generated auth material, and generated `airflow.cfg` must not be committed.

Never use `docker compose down -v` for this project: it deletes persistent database and Airflow auth volumes.
