# Current State

> Concise checkpoint of the currently verified project state.
> Detailed procedures belong in `docs/runbooks/`; recovery history belongs in `docs/history/`.

## Branch

`portfolio-recovery`

## Completed

- Phase 01 — macOS + Docker Desktop setup ✅
- Phase 02 — PostgreSQL data layer ✅

## Verified environment

- Docker Desktop on Apple Silicon (`aarch64`)
- `de_postgres` is healthy
- `de_adminer` is running
- PostgreSQL host port: `5433`
- Adminer host port: `8081`
- Existing unrelated PostgreSQL container on host port `5432` is untouched

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

## Active phase

Phase 03 — Airflow

Goal:

- run Airflow on macOS Docker Desktop
- use database `airflow` for Airflow metadata
- create Airflow connection `pg_dw` to `ecom_dw`
- verify DAG parsing/import
- run a simple smoke-test DAG against `ecom_dw`

Do not start Spark, MSSQL, BigQuery, Kafka, or Debezium in this phase.

## Next

- Phase 04 — SQL Server → Spark → PostgreSQL staging
- Phase 05 — STG → RAW → DW → DM
- Phase 06 — PostgreSQL → GCS → BigQuery
- Phase 07 — MySQL → Debezium → Kafka → Spark Streaming → PostgreSQL

## Rule

Only update this file after a phase has been actually verified.
If this file conflicts with the repository or verified command output, the repository/output is authoritative.
