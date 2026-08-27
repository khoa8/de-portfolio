# Verification Summary

This page is an index of observed evidence, not a substitute for the canonical
runbooks. Counts and run IDs below were recorded from completed local/cloud
verification on 2026-08-26 and 2026-08-27.

## Phase evidence

| Phase | Mandatory proof | Verified result |
| --- | --- | --- |
| 01 | Apple Silicon Docker environment | Docker Desktop on `aarch64` |
| 02 | PostgreSQL data layer | PostgreSQL 16 healthy; `airflow` and `ecom_dw` separated |
| 03 | Airflow runtime and smoke DAG | Airflow 3.0.4, LocalExecutor, SimpleAuthManager, smoke `success` |
| 04 | SQL Server staging ingestion | 149,139 Lazada + 244,799 Shopee + 34,423 Tiki rows; two runs `success` |
| 05 | Hard DQ and idempotent warehouse | 245,675 distinct orders, 0 orphan keys, two runs with stable counts |
| 06 | Exact-object cloud export | 3 dimension rows, 245,675 unique facts, 1,336 daily groups; two same-day runs without duplicates |
| 07 | CDC behavior and checkpoint resume | 8 topic records, 8 unique sink TPOs, exact large decimal, two bounded runs `success` |

## Warehouse reconciliation

| Metric | PostgreSQL result | BigQuery result |
| --- | ---: | ---: |
| Distinct/fact orders | 245,675 | 245,675 |
| Daily platform groups | 1,336 | 1,336 |
| Total sales | 50,228,062,824.00 | 50,228,062,824 |
| Orphan dimension keys | 0 | Not applicable after enriched export validation |

Phase 05 reconciled staging distinct orders, RAW, fact, and daily-mart order
counts. Phase 06 separately reconciled row counts, per-platform counts, order
counts, and totals after each canonical BigQuery load.

## Streaming reconciliation

| Metric | Result |
| --- | ---: |
| Kafka end offset | 8 |
| Append-only event rows | 8 |
| Distinct topic-partition-offset keys | 8 |
| Active current rows | 2 |
| Soft-deleted current rows | 1 |
| Malformed events retained | 1 |
| Active amount total | 10,000,000,000,000,025.74 |
| Precision probe | `9999999999999999.99` exact in MySQL, Kafka JSON, event JSON, and PostgreSQL |

The connector and its task were `RUNNING`; the second bounded run reused the
existing checkpoint and did not increase event/current counts. MySQL, Kafka,
and checkpoint volumes remained intact.

## Regression evidence

- Phase 03 read-only PostgreSQL smoke passed after Phases 04, 05, 06, and 07.
- Airflow reported no DAG import errors after each active DAG was introduced.
- Phase 05's isolated negative probe proved bad critical data fails the hard DQ
  gate before warehouse writes.
- Focused unit tests cover source allowlists, conversion behavior, DQ contracts,
  exact-object export rules, BigQuery schema settings, CDC operation decoding,
  tombstones, malformed records, offset guards, loopback bindings, least
  privilege, and decimal precision.

## CI verification boundary

The repository CI is intentionally secret-free and cloud-free. It verifies:

- Python compilation;
- focused offline unit/contract tests;
- base and Phase 07 Compose configuration;
- local Markdown links and cross-document contracts;
- whitespace, generated-artifact, and credential-pattern hygiene.

CI does not claim to reproduce the live SQL Server, Airflow task execution,
GCS, BigQuery, or CDC runtime evidence. Those integrations require approved
credentials or persistent services and are documented in the corresponding
runbooks.

## Canonical evidence

- [Phase 03 Airflow](runbooks/03-airflow-setup.md)
- [Phase 04 staging ingestion](runbooks/04-mssql-spark-to-postgres-staging.md)
- [Phase 05 warehouse](runbooks/05-stg-raw-dw-dm.md)
- [Phase 06 cloud export](runbooks/06-postgres-gcs-bigquery.md)
- [Phase 07 streaming](runbooks/07-mysql-kafka-spark-streaming.md)
- [Current state](CURRENT_STATE.md)
