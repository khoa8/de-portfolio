# Data Engineering Portfolio

A reproducible, verification-first data engineering project built on macOS and
Docker Desktop. It demonstrates both a batch warehouse path and a local CDC
streaming path while keeping orchestration metadata, business data, secrets,
and cloud resources deliberately separated.

## The problem

E-commerce order data arrives from heterogeneous operational systems and must
be made trustworthy for analytics. This portfolio shows how to:

- ingest three SQL Server marketplace sources into PostgreSQL staging;
- enforce hard data-quality gates before publishing RAW and dimensional data;
- build an idempotent star schema and daily-sales mart;
- export validated warehouse data through run-specific GCS objects to
  partitioned and clustered BigQuery tables;
- process MySQL change events through Debezium, Kafka, and bounded Spark
  Structured Streaming without duplicating sink records.

## Architecture

```text
Batch
SQL Server (GCP VM, private SSH tunnel)
  -> Airflow 3 / Spark JDBC
  -> PostgreSQL stg_edw -> raw -> dw -> dm
  -> run-specific GCS NDJSON -> BigQuery dw / dm

Streaming
MySQL -> Debezium Connect -> Kafka KRaft
  -> Spark Structured Streaming -> PostgreSQL cdc
```

Airflow metadata lives in PostgreSQL database `airflow`; all local business
schemas live in the separate `ecom_dw` database. The streaming services are an
optional Compose profile, so the batch stack remains independently runnable.

See the [architecture overview](docs/ARCHITECTURE.md) for service boundaries,
data contracts, and repository layout.

## Technology stack

| Layer | Technology |
| --- | --- |
| Orchestration | Apache Airflow 3.0.4, LocalExecutor, SimpleAuthManager |
| Processing | Apache Spark / PySpark 3.5.1, Java 17 |
| Local data | PostgreSQL 16, MySQL 8.4.6 |
| Streaming | Apache Kafka 3.9.1 KRaft, Debezium 3.2.4, Kafka UI 0.7.2 |
| Cloud analytics | Google Cloud Storage, BigQuery |
| Packaging | Docker Compose, pinned providers/JDBC dependencies |
| Quality | Python unit tests, SQL contracts, Compose validation, GitHub Actions |

## Verified results

| Capability | Verified result |
| --- | --- |
| Airflow runtime | Airflow 3.0.4, `LocalExecutor`, clean DAG imports |
| SQL Server staging | 428,361 physical rows across Lazada, Shopee, and Tiki |
| RAW/DW/DM | 245,675 distinct orders, 0 orphan keys, 1,336 daily groups |
| Warehouse totals | DW and DM both reconcile to `50,228,062,824.00` |
| BigQuery export | 245,675 unique fact orders and 1,336 daily groups after two same-day runs |
| MySQL CDC | 8 Kafka records -> 8 unique sink offsets, including update/delete/tombstone/malformed cases |
| Decimal precision | `9999999999999999.99` preserved exactly end to end |

The concise evidence index is in
[Verification Summary](docs/VERIFICATION.md). Detailed commands and runtime
evidence remain in the phase runbooks.

## Quick start

Prerequisites: Docker Desktop with Compose v2, Git, and Python 3.11+.

```bash
git clone https://github.com/khoa8/de-portfolio.git
cd de-portfolio
cp airflow/.env.example airflow/.env
chmod 600 airflow/.env
```

Replace every `change_me`/`replace_me` value needed for the phase you intend to
run. Never commit `airflow/.env` or print its resolved Compose configuration.

Validate and start only the local PostgreSQL/Adminer foundation:

```bash
docker compose --env-file airflow/.env \
  -f airflow/docker-compose.batch.yaml \
  config --quiet

docker compose --env-file airflow/.env \
  -f airflow/docker-compose.batch.yaml \
  up -d postgres adminer
```

Continue with the [Airflow setup runbook](docs/runbooks/03-airflow-setup.md) or
the phase-specific runbook below. Never use `docker compose down -v`; project
volumes hold verified PostgreSQL, MySQL, Kafka, auth, and checkpoint state.

## Reproduce the portfolio checks without secrets or cloud access

```bash
python3 scripts/ci/validate_repository.py

PYTHONPYCACHEPREFIX=/tmp/de_portfolio_ci_pycache \
python3 -m compileall -q airflow/dags airflow/scripts spark tests scripts/ci

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

These checks do not start containers, use ADC, contact cloud services, or read
the ignored `.env` file.

## Documentation

- [Architecture overview](docs/ARCHITECTURE.md)
- [Verification summary](docs/VERIFICATION.md)
- [Short demo guide](docs/DEMO.md)
- [Current verified state](docs/CURRENT_STATE.md)
- [Phase 01 — macOS and Docker](docs/runbooks/01-macos-docker-setup.md)
- [Phase 02 — PostgreSQL](docs/runbooks/02-postgres-data-layer.md)
- [Phase 03 — Airflow](docs/runbooks/03-airflow-setup.md)
- [Phase 04 — SQL Server to staging](docs/runbooks/04-mssql-spark-to-postgres-staging.md)
- [Phase 05 — RAW, DW, and DM](docs/runbooks/05-stg-raw-dw-dm.md)
- [Phase 06 — GCS and BigQuery](docs/runbooks/06-postgres-gcs-bigquery.md)
- [Phase 07 — MySQL CDC streaming](docs/runbooks/07-mysql-kafka-spark-streaming.md)

## Safety boundaries

- Credentials live only in ignored runtime files or existing user ADC.
- Phase 04 never exposes SQL Server port 1433 publicly.
- Phase 06 loads exact run objects and validates before canonical writes.
- Phase 07 binds MySQL, Connect REST, and Kafka UI host ports to `127.0.0.1`.
- Legacy DAGs remain source-controlled but quarantined by `.airflowignore`.
- No normal workflow deletes topics, checkpoints, or Docker volumes.
