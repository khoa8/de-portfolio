# Spark notes for this repository

The current verified Spark procedure is
`docs/runbooks/04-mssql-spark-to-postgres-staging.md`.

## Current architecture

- Airflow `3.0.4` with `LocalExecutor`
- Spark `3.5.1` using Airflow connection `spark_local` → `local[*]`
- Java 17 inside the custom Airflow image
- Microsoft JDBC `13.4.0.jre11`
- PostgreSQL JDBC `42.7.7`
- business target: `postgres:5432/ecom_dw`, never the Airflow metadata database

The Docker image downloads pinned JDBC JARs during build and verifies their
SHA-256 values. Binary JARs are not committed and DAG runs do not download
floating dependencies.

## Separation of responsibilities

- `spark/spark_mssql_to_postgres.py` reads, normalizes, measures conversions,
  and writes disposable Phase 04 load tables.
- `airflow/dags/mssql_ecom_to_stg.py` owns orchestration, retries, dependency
  order, PostgreSQL DDL, count reconciliation, atomic publish, and cleanup.
- Credentials are inherited from ignored runtime environment variables. They
  must never be application arguments, JDBC URL fields, source literals, or
  log output.

## Safe JDBC publishing

Do not use Spark JDBC `mode("overwrite")` on canonical PostgreSQL tables. Spark
can drop and recreate a target when truncate optimization is unavailable,
breaking schema contracts and dependent objects.

The verified Phase 04 pattern is:

```text
create explicit canonical/load tables from versioned SQL
  -> clear disposable load tables
  -> Spark append to load tables
  -> reconcile all source/load counts
  -> transactionally truncate and refill canonical tables
  -> validate published counts
  -> clear disposable load state
```

Use explicit source-key and target-table allowlists. Tiki's missing buyer field
must be a typed Spark string null. Treat conversion failures as measured data
quality evidence rather than silently dropping rows.

## Useful checks

```bash
docker compose \
  -f airflow/docker-compose.batch.yaml \
  -f airflow/docker-compose.yaml \
  config --quiet

docker compose \
  -f airflow/docker-compose.batch.yaml \
  -f airflow/docker-compose.yaml \
  exec -T airflow-scheduler \
  python -c 'import pyspark; print(pyspark.__version__)'

docker compose \
  -f airflow/docker-compose.batch.yaml \
  -f airflow/docker-compose.yaml \
  exec -T airflow-scheduler \
  airflow dags list-import-errors --output json
```

Never print resolved Compose configuration when it contains `.env` values, run
`docker compose down -v`, point business data at database `airflow`, or add
Phase 05–07 logic to the Phase 04 job.
