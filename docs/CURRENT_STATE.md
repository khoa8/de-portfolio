# Current State

> Concise checkpoint of the currently verified project state.
> Detailed procedures belong in `docs/runbooks/`; recovery history belongs in `docs/history/`.

## Branch

`portfolio-recovery`

## Completed

- Phase 01 — macOS + Docker Desktop setup ✅
- Phase 02 — PostgreSQL data layer ✅
- Phase 03 — Airflow 3.0.4 + LocalExecutor ✅
- Phase 04 — SQL Server → Spark → PostgreSQL staging ✅
- Phase 05 — STG → RAW → DW → DM ✅

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
- Spark `3.5.1` runs in local mode through Airflow `LocalExecutor`
- SQL Server access uses a temporary loopback SSH tunnel; public port `1433` remains closed
- Phase 05 runs entirely against local PostgreSQL and does not require the GCP VM or tunnel

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
- active repository DAGs: `phase03_postgres_smoke`, `mssql_ecom_to_stg`, and
  `ecom_stg_to_raw_dw_dm`
- DAG import errors: none
- verified smoke run: `phase03_verify_20260825T195300Z` — `success`
- post-Phase-04 regression run: `phase03_regression_20260826T165100Z` — `success`
- canonical procedure: `docs/runbooks/03-airflow-setup.md`

## Verified Phase 04

- source: `EDW_Tech.ecom` on the existing GCP SQL Server VM
- targets: three canonical tables in `ecom_dw.stg_edw`
- final verification runs:
  - `phase04_verify_20260826T164900Z_run3` — `success`
  - `phase04_verify_20260826T165000Z_run4` — `success`
- stable counts on both runs:
  - Lazada: `149139`
  - Shopee: `244799`
  - Tiki: `34423`
- source/load/published counts reconciled for every platform
- date and amount conversion failures: `0`
- canonical runbook: `docs/runbooks/04-mssql-spark-to-postgres-staging.md`

## Verified Phase 05

- hard DQ rejects bad critical staging data before writes
- RAW explicit key: `(source, order_code)` with JSONB dedup/variant evidence
- DW reads only RAW and maintains stable platform/customer/date/fact keys
- data mart: `dm.mv_daily_sales`
- final consecutive runs:
  - `phase05_verify_20260826T194500Z_run1` — `success`
  - `phase05_verify_20260826T194700Z_run2` — `success`
- reconciled counts on both runs:
  - staging physical rows: `428361`
  - distinct staging orders / RAW / fact / DM orders: `245675`
  - DM daily-platform groups: `1336`
- DW and DM total sales: `50228062824.00`
- orphan dimension keys: `0`
- post-Phase-05 regression run:
  `phase03_regression_after_phase05_20260826T194800Z` — `success`
- canonical runbook: `docs/runbooks/05-stg-raw-dw-dm.md`

## Next phase

- Phase 06 — PostgreSQL → GCS → BigQuery — not started
- Phase 07 — MySQL → Debezium → Kafka → Spark Streaming → PostgreSQL

## Rule

Only update this file after a phase has been actually verified.
If this file conflicts with the repository or verified command output, the repository/output is authoritative.
