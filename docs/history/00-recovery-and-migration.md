# Recovery and Migration History

> Internal project history. This document explains how the current repository was recovered and why several architectural decisions changed during the migration. It is **not** the step-by-step runbook for rebuilding the project from scratch.

## Purpose

The original Data Engineering portfolio was developed primarily inside an Ubuntu ARM64 virtual machine running under UTM on macOS. GitHub stopped being updated before the actual local project work stopped, so the public repository did not represent the final local state.

In August 2026, the project was recovered before migrating development to Docker Desktop directly on macOS.

The recovery process had two goals:

1. Preserve work that existed only inside the old VM or Google Drive.
2. Rebuild the project into a reproducible, documented portfolio instead of continuing from an undocumented legacy environment.

## Legacy Environment

```text
macOS
  ↓
UTM Ubuntu ARM64 VM
  ↓
Docker Engine
  ├── Airflow
  ├── PostgreSQL
  ├── Redis
  ├── MySQL
  ├── Kafka
  ├── Debezium
  └── Spark
```

External/cloud systems included SQL Server on GCP, GCS, BigQuery, Looker Studio, and experimental Microsoft Fabric work.

The migration target is:

```text
macOS
  ├── Git / VS Code / Terminal
  └── Docker Desktop
       ├── Airflow (LocalExecutor)
       ├── PostgreSQL
       └── Later phase-scoped services
            ├── Spark
            ├── MySQL
            ├── Kafka
            └── Debezium
```

## GitHub State at Recovery Time

The public repository was clean through the Kafka phase, with the latest main-branch work ending in September 2025.

The legacy VM repository still matched `origin/main`, but it contained local work that had never been committed.

Important local changes included:

```text
Modified:
- airflow/Dockerfile
- airflow/docker-compose.yaml

Untracked:
- airflow/dags/ecom_stg_to_bq_dw.py
- airflow/dags/ecom_stg_to_dw.py
- airflow/dags/mssql_ecom_to_stg.py
- airflow/jars/mssql-jdbc-12.6.1.jre11.jar
- airflow/jars/postgresql-42.7.3.jar
- spark/spark_mssql_to_postgres.py
```

This explains why GitHub appeared to stop at Kafka even though later batch/cloud pipeline work had actually been implemented.

## Recovered Pipeline Stages

### Source and staging

```text
SQL Server / EDW_Tech
        ↓
      Spark
        ↓
PostgreSQL stg_edw
```

### Data warehouse evolution

The initial design was:

```text
STAGING
   ↓
STAR-SCHEMA DW
```

Later VM code evolved into:

```text
STAGING
   ↓
Data Quality
   ↓
RAW JSONB
   ↓
STAR-SCHEMA DW
   ↓
DATA MART
```

The warehouse included:

```text
dw.dim_platform
dw.dim_customer
dw.dim_date
dw.fact_orders
```

The data mart included:

```text
dm.mv_daily_sales
```

### Cloud export

A previously missing DAG was recovered from the VM:

```text
airflow/dags/ecom_stg_to_bq_dw.py
```

Its flow was:

```text
PostgreSQL DW / DM
        ↓
PostgresToGCSOperator
        ↓
GCS NDJSON
        ↓
GCSToBigQueryOperator
        ↓
BigQuery
```

Airflow logs confirmed that this cloud pipeline had actually been executed.

## Important Legacy Issues Found During Recovery

### Platform code case mismatch

One VM version produced display values such as `Shopee`, `Lazada`, and `Tiki`, while downstream joins expected canonical codes `shopee`, `lazada`, and `tiki`.

The clean implementation standardizes machine-readable platform codes as lowercase and stores display names separately.

### Data-quality task only warned

The legacy task was described as a DQ gate but only emitted a PostgreSQL notice. Critical-null checks should fail the task when the data is unusable.

### Missing database bootstrap SQL

Some required objects had been created manually and were not source controlled, including the RAW table and data-mart materialized view.

The rebuild moves database structure into versioned SQL files.

### BigQuery same-day wildcard risk

The legacy GCS export generated timestamped full snapshots inside a date-level directory, while the load step used a wildcard matching all files for that date. Multiple runs in one day could therefore load multiple full snapshots together.

The rebuilt pipeline will isolate every DAG run.

### Secrets and binary drivers

Legacy configuration contained local credentials and JDBC JAR files. The clean repository should never commit real `.env` files or credentials and should avoid committing binary JDBC drivers when they can be resolved during build/setup.

## Recovery Asset Policy

### Keep and clean

```text
mssql_ecom_to_stg.py
spark_mssql_to_postgres.py
ecom_stg_to_dw.py
ecom_stg_to_bq_dw.py
Dockerfile
docker-compose.yaml
```

### Keep as forensic/history material only

```text
uncommitted_git_diff.patch
legacy .env
selected Airflow execution logs
old Drive snapshots
ecom_cols.csv
```

### Do not commit to the clean portfolio

```text
real .env files
credentials
generated Airflow logs
Spark checkpoints
__pycache__
JDBC JAR binaries
runtime artifacts
```

## Documentation Strategy

Recovery history and operational runbooks are intentionally separate:

```text
docs/
├── history/
│   └── 00-recovery-and-migration.md
└── runbooks/
    ├── 01-macos-docker-setup.md
    ├── 02-postgres-data-layer.md
    ├── 03-airflow-setup.md
    ├── 04-spark-mssql-ingestion.md
    ├── 05-staging-to-dw.md
    ├── 06-gcs-bigquery.md
    └── 07-kafka-cdc-streaming.md
```

The rule is:

```text
BUILD
  ↓
RUN
  ↓
VERIFY
  ↓
DOCUMENT
  ↓
COMMIT
```

A runbook must describe how to reproduce the phase from a clean checkout. Historical recovery details belong here instead.

## Migration Status

```text
Legacy project forensic audit       COMPLETE
Critical uncommitted code recovery  COMPLETE
Migration to macOS                  STARTED
Docker Desktop verification         COMPLETE
Local PostgreSQL bootstrap          COMPLETE
Airflow migration                   COMPLETE
Spark / MSSQL migration             COMPLETE
GCS / BigQuery migration            NEXT
Kafka / Debezium migration          PENDING
Fabric audit                        PENDING
```

Phase 04 was reverified on macOS against the original live SQL Server source on
the existing GCP VM. The clean implementation uses an instance-scoped temporary
SSH tunnel, a dedicated object-level read-only SQL login, pinned checksum-verified
JDBC drivers, disposable load tables, and an atomic PostgreSQL publish step. Two
consecutive Airflow runs produced stable counts with zero conversion failures.
Live evidence also revealed the source-specific date formats that were missing
from the recovered Spark parser; those formats are now covered by regression
tests. No legacy credential or binary JAR was recovered into Git.

The UTM VM should remain archived until the important pipelines have been reproduced successfully on macOS.
