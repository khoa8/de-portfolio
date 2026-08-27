# Architecture Overview

## Design goals

This portfolio favors explicit data contracts, bounded execution, idempotent
loads, and evidence-backed verification. Local orchestration and business data
share one PostgreSQL service but use separate databases. Optional streaming and
cloud paths do not prevent the batch foundation from running independently.

## Batch path

```text
Existing SQL Server database EDW_Tech on GCP VM
  -> temporary macOS SSH tunnel (Phase 04 verification only)
  -> Airflow 3 LocalExecutor
  -> Spark 3.5.1 JDBC normalization
  -> PostgreSQL ecom_dw.stg_edw
  -> hard DQ gate
  -> PostgreSQL raw.orders_raw
  -> PostgreSQL dw dimensions + fact_orders
  -> PostgreSQL dm.mv_daily_sales
  -> run-unique GCS NDJSON objects
  -> BigQuery dw.dim_platform / dw.fact_orders / dm.daily_sales
```

Phase 04 uses disposable load tables and an atomic publish into explicit
staging contracts. Phase 05 performs idempotent RAW and DW upserts, creates the
materialized view reproducibly, and fails before writes when critical DQ is
bad. Phase 06 validates exact run objects before the three canonical BigQuery
loads.

The SQL Server VM, SSH tunnel, GCS, and BigQuery are not required for the local
PostgreSQL/Airflow foundation or the Phase 07 streaming demo.

## Streaming path

```text
MySQL 8.4.6 phase07_shop.orders
  -> Debezium 3.2.4 connector
  -> Kafka 3.9.1 KRaft, one data partition
  -> Spark Structured Streaming 3.5.1
  -> PostgreSQL ecom_dw.cdc.order_events (append-only)
  -> PostgreSQL ecom_dw.cdc.orders_current (offset-guarded current state)
```

The Airflow DAG uses `availableNow`, so LocalExecutor receives a bounded task.
An optional Compose service provides a processing-time mode for a continuous
demo. Both modes use the same named checkpoint volume. Debezium emits decimals
as strings so Spark never introduces a floating-point conversion before the
PostgreSQL numeric sink.

## Compose layers

| File | Responsibility | Starts independently |
| --- | --- | --- |
| `airflow/docker-compose.batch.yaml` | PostgreSQL 16 and Adminer | Yes |
| `airflow/docker-compose.yaml` | Airflow API server, scheduler, DAG processor, init/CLI | With batch layer |
| `airflow/docker-compose.streaming.yaml` | MySQL, Kafka, Connect, Kafka UI, init jobs, optional Spark demo | Only with `phase07`/`phase07-demo` profile |

All project services use `de_network`. Containers reach PostgreSQL at
`postgres:5432`; macOS reaches it at port `5433`. MySQL, Connect REST, and Kafka
UI are exposed only on `127.0.0.1`.

## Database boundaries

| Database | Purpose | Schemas |
| --- | --- | --- |
| `airflow` | Airflow metadata only | Airflow-managed |
| `ecom_dw` | Portfolio business data | `stg_edw`, `raw`, `dw`, `dm`, `cdc` |

The Airflow connection `pg_dw` targets `postgres:5432/ecom_dw`. Business DAGs
must never use the metadata database.

## Active DAGs

| DAG | Purpose |
| --- | --- |
| `phase03_postgres_smoke` | Read-only business database smoke test |
| `mssql_ecom_to_stg` | SQL Server marketplace ingestion |
| `ecom_stg_to_raw_dw_dm` | DQ, RAW, star schema, and daily mart |
| `postgres_to_gcs_bigquery` | Validated GCS/BigQuery export |
| `mysql_cdc_to_postgres` | Bounded CDC processing |

Seven legacy DAGs remain source-controlled and are quarantined by
`airflow/dags/.airflowignore`.

## Data contracts and idempotency

- Staging tables have explicit typed columns and source allowlists.
- RAW uses the stable `(source, order_code)` business key and retains JSONB
  source evidence.
- Dimensions and facts use stable keys and conflict-aware upserts.
- The daily mart is recreated from DW SQL and refreshed only after its object
  and unique index exist.
- GCS paths contain the Airflow run identity; BigQuery loads the exact validated
  object rather than a date wildcard.
- CDC event identity is Kafka `(topic, partition, offset)`; current-state writes
  apply only newer offsets and represent deletes explicitly.

## Security and persistence

- Runtime secrets live in ignored `airflow/.env`, generated Airflow auth files,
  or existing user ADC mounted read-only.
- No service-account key, connector password, token, or resolved URI belongs in
  Git.
- The fixed Debezium user has source-database `SELECT` and only the global
  privileges required for snapshot/binlog operation.
- Docker volumes preserve PostgreSQL, MySQL, Kafka, Airflow auth, and Spark
  checkpoint state. Destructive volume deletion is never a normal lifecycle
  command.

## Repository map

```text
airflow/             Compose layers, image, DAGs, safe bootstrap scripts
spark/               Batch and streaming Spark applications
sql/init/            PostgreSQL database/bootstrap contracts
sql/phase04/         Staging contracts
sql/phase05/         RAW/DW/DM contracts and verification SQL
sql/phase07/         MySQL source and PostgreSQL CDC sink contracts
tests/               Focused offline unit/contract tests
docs/runbooks/       Canonical phase procedures and runtime evidence
scripts/ci/          Secret-free repository validation
.github/workflows/   Pull-request and branch CI
```
