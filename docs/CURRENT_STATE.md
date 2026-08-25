# Current State

> Concise checkpoint of the currently verified project state.
> Detailed procedures belong in `docs/runbooks/`; recovery history belongs in `docs/history/`.

## Branch

`portfolio-recovery`

## Completed

- Phase 01 — macOS + Docker Desktop setup ✅
- Phase 02 — PostgreSQL data layer ✅
- Phase 03 — Airflow 3.0.4 + LocalExecutor ✅

## Verified environment

- Docker Desktop on Apple Silicon (`aarch64`)
- `de_postgres` is healthy
- `de_adminer` is running
- PostgreSQL host port: `5433`
- Adminer host port: `8081`
- Existing unrelated PostgreSQL container on host port `5432` is untouched
- Airflow API server, scheduler, and DAG processor are healthy
- Airflow executor: `LocalExecutor`
- Airflow auth manager: `SimpleAuthManager`
- Airflow UI/API host port: `8080`

## Verified databases

PostgreSQL contains:

- `airflow` — reserved for Airflow metadata
- `ecom_dw` — business data

`ecom_dw` contains:

- `stg_edw`
- `raw`
- `dw`
- `dm`

Verified table:

- `raw.orders_raw`
  - primary key: `raw_id`
  - unique constraint: `(source, order_code)`

## Verified Airflow

- Airflow metadata is stored in database `airflow`
- `pg_dw` resolves to `postgres:5432/ecom_dw`
- bundled examples are disabled
- seven legacy DAGs remain tracked and quarantined
- only `phase03_postgres_smoke` is active
- DAG import errors: none
- verified smoke run: `phase03_verify_20260825T195300Z` — `success`
- canonical procedure: `docs/runbooks/03-airflow-setup.md`

## Active phase

Phase 04 — SQL Server → Spark → PostgreSQL staging

Phase 04 has not started.

## Next

- Phase 05 — STG → RAW → DW → DM
- Phase 06 — PostgreSQL → GCS → BigQuery
- Phase 07 — MySQL → Debezium → Kafka → Spark Streaming → PostgreSQL

## Rule

Only update this file after a phase has been actually verified.
If this file conflicts with the repository or verified command output, the repository/output is authoritative.
