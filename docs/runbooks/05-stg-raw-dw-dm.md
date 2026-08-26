# Phase 05 — STG to RAW to DW to DM

## Goal

Phase 05 turns the verified Phase 04 PostgreSQL staging snapshot into a local,
idempotent analytics pipeline:

```text
ecom_dw.stg_edw
  -> hard data-quality gate
  -> raw.orders_raw
  -> dw dimensions and fact
  -> dm.mv_daily_sales
```

The phase is PostgreSQL-only. It does not require the GCP VM, SQL Server, the
Phase 04 SSH tunnel, Spark, or any cloud service.

## Architecture and responsibilities

The Airflow DAG is `ecom_stg_to_raw_dw_dm`. It uses Airflow 3 TaskFlow authoring
interfaces from `airflow.sdk`, connection `pg_dw`, `LocalExecutor`, no schedule,
no catchup, and at most one active run.

```text
hard_dq_gate
  -> prepare_phase05_objects
    -> upsert_raw_orders
      -> upsert_dimensions_and_fact
        -> refresh_daily_sales
          -> verify_and_audit
```

Versioned SQL lives under `sql/phase05/`:

| File | Responsibility |
| --- | --- |
| `001_warehouse_objects.sql` | Create RAW/DW contracts, stable keys, constraints, indexes, and audit table |
| `002_upsert_raw_orders.sql` | Deterministically reconcile staging duplicates and idempotently upsert RAW |
| `003_upsert_dimensions_and_fact.sql` | Upsert platform/date/customer dimensions and order fact strictly from RAW |
| `004_daily_sales_materialized_view.sql` | Create/index the daily-sales MV before refreshing it |
| `005_verify_and_audit.sql` | Enforce STG/RAW/DW/DM reconciliation and persist per-run evidence |

No file uses `DROP`, `DROP ... CASCADE`, or Spark JDBC overwrite.

## Hard data-quality gate

The first task fails before any Phase 05 write when:

- a required source table is missing or empty;
- `order_id` is null/blank;
- `order_date` is null;
- `total_amount` is null;
- the stored platform is not exactly its lowercase canonical code.

The only accepted machine codes are:

```text
lazada
shopee
tiki
```

Duplicates are measured but are not silently discarded. An isolated PostgreSQL
probe creates temporary look-alike staging tables, inserts a bad critical row,
proves that the production DQ evaluator raises an error, and rolls back without
persistent writes.

## RAW contract and deterministic reconciliation

RAW is written with the explicit column contract:

```text
(source, order_code, payload, src_event_ts)
```

`raw.orders_raw` remains unique on `(source, order_code)`. A repeat run uses
`ON CONFLICT` and writes only when payload or source timestamp changed, so an
unchanged snapshot does not change `ingested_at`.

Phase 04 staging contains multiple rows for many order IDs. Source modification
timestamps and line identifiers are not available in the normalized staging
contract, so choosing an implicit “latest” row would be ambiguous. Phase 05
makes the resolution observable:

- exact and conflicting candidates are grouped by a stable payload hash;
- every distinct candidate and its source-row multiplicity is retained in
  `payload._variants`;
- `payload._dedup` records source-row count, distinct-variant count, selected
  hash, and the canonical selection rule;
- the canonical candidate is ordered by event time, amount, status, buyer, and
  payload hash, all with explicit direction/null handling.

This preserves replay/audit evidence while producing one stable order-grain RAW
record. The rule is deterministic; it is not presented as a source-system
update timestamp.

## Dimensional model

Phase 05 creates and maintains:

```text
dw.dim_platform
dw.dim_customer
dw.dim_date
dw.fact_orders
dw.phase05_batch_audit
```

- Platform codes remain lowercase and have stable surrogate keys.
- Customer natural key is platform-scoped. Missing/blank buyer values map to
  the explicit `unknown` member for that platform.
- Date key is the stable integer `YYYYMMDD`.
- Fact grain is `(platform_key, order_nk)`.
- Dimensions/fact use upserts and update timestamps only when business values
  actually change.
- DW reads only `raw.orders_raw`; it never reads staging directly.

The current Phase 04 staging snapshot has blank buyer names for every row, so
the verified customer dimension contains one `unknown` member per platform.
This is source evidence, not synthetic customer recovery.

## Daily-sales data mart

`dm.mv_daily_sales` is derived only from `dw.fact_orders` joined to platform and
date dimensions. It exposes:

```text
order_date
platform_code
platform_name
total_sales
order_count
```

The MV is created with `IF NOT EXISTS`, then its unique/query indexes are
created, and only then is it refreshed. Verification compares every daily
platform group, order count, and total against an independent DW aggregation.

## Build and static checks

```bash
docker compose \
  -f airflow/docker-compose.batch.yaml \
  -f airflow/docker-compose.yaml \
  config --quiet

python3 -m py_compile \
  airflow/dags/ecom_stg_to_raw_dw_dm.py \
  tests/test_phase05_pipeline.py \
  tests/phase05_negative_dq_probe.py

docker run --rm --entrypoint python \
  -v /absolute/path/to/de-portfolio:/workspace:ro \
  -w /workspace de-airflow:3.0.4 \
  -m unittest tests.test_phase05_pipeline -v
```

The isolated negative DQ probe must run inside the scheduler runtime so it can
reuse `pg_dw`. Copy it temporarily to the container, run it, and remove the
temporary copy afterward. It creates only temp tables and always rolls back.

## Run and verify

```bash
docker compose \
  -f airflow/docker-compose.batch.yaml \
  -f airflow/docker-compose.yaml \
  exec -T airflow-scheduler \
  airflow dags unpause ecom_stg_to_raw_dw_dm

docker compose \
  -f airflow/docker-compose.batch.yaml \
  -f airflow/docker-compose.yaml \
  exec -T airflow-scheduler \
  airflow dags trigger --run-id <unique-run-id> ecom_stg_to_raw_dw_dm
```

For idempotency, trigger two consecutive runs against the unchanged staging
snapshot. Verify both DAG/task states, both audit rows, RAW/DW counts, stable
technical-key/content fingerprints, orphan counts, and DW/DM reconciliation.

## Verified evidence — 2026-08-27

Final runs:

- `phase05_verify_20260826T194500Z_run1` — `success`, six tasks successful;
- `phase05_verify_20260826T194700Z_run2` — `success`, six tasks successful.

Both audit rows are identical:

| Metric | Value |
| --- | ---: |
| Staging physical rows | 428,361 |
| Staging distinct order keys | 245,675 |
| RAW orders | 245,675 |
| DW facts | 245,675 |
| DM daily/platform groups | 1,336 |
| DM order count | 245,675 |
| DW total sales | 50,228,062,824.00 |
| DM total sales | 50,228,062,824.00 |

Per-platform reconciliation:

| Platform | STG rows | Distinct orders | RAW | Fact | DM orders | DM sales |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Lazada | 149,139 | 84,669 | 84,669 | 84,669 | 84,669 | 16,147,639,680.00 |
| Shopee | 244,799 | 140,444 | 140,444 | 140,444 | 140,444 | 29,892,213,979.00 |
| Tiki | 34,423 | 20,562 | 20,562 | 20,562 | 20,562 | 4,188,209,165.00 |

The second run preserved RAW/fact content fingerprints, platform/customer key
mappings, maximum RAW `ingested_at`, and maximum fact `load_dts`. Counts did
not grow. Platform, customer, and date orphan counts were all zero. Every DM
group matched DW independently.

The isolated negative probe returned:

```text
negative_dq_result=expected_failure
negative_dq_persistent_writes=0
```

DAG import errors were empty. Phase 03 regression run
`phase03_regression_after_phase05_20260826T194800Z` succeeded.

## Stop and restart

Phase 05 has no additional long-running service. Normal Airflow/PostgreSQL
Compose stop/restart preserves all database volumes and can rerun the DAG after
services are healthy.

Never run `docker compose down -v`, delete the PostgreSQL volume, reset either
database, or use `DROP ... CASCADE` as a Phase 05 troubleshooting step.

## Troubleshooting

- DQ failure: use the reported source/count category; do not weaken the gate.
- RAW mismatch: compare staging distinct order keys with RAW `(source,
  order_code)` and inspect `_dedup` metadata without deleting audit evidence.
- Fact mismatch: verify that dimensions resolve all RAW rows; DW SQL must not
  bypass RAW.
- MV refresh failure: verify that the MV and both indexes exist before refresh.
- Duplicate-count surprises: remember that STG physical rows are not the order
  grain; use the documented variants and deterministic selection rule.

## Out of scope

Phase 04 source ingestion changes, GCP/SQL Server access, incremental loading,
production customer identity resolution, GCS, BigQuery, Kafka, Debezium,
MySQL, and Phase 06 work remain out of scope.
