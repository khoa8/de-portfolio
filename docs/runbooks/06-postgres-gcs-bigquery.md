# Phase 06 — PostgreSQL → GCS → BigQuery

## Goal

Phase 06 publishes the verified local Phase 05 warehouse to Google Cloud:

```text
PostgreSQL ecom_dw
  -> run-specific NDJSON objects in GCS
  -> validated exact object URIs
  -> BigQuery dw/dm canonical tables
```

The pipeline is reproducible and idempotent for repeated runs on the same day.
Every Airflow run uses a unique GCS prefix and each BigQuery load uses one exact
object URI. Canonical tables are replaced only after all three run objects pass
schema, required-field, generation, row-count, per-platform, and total checks.

## Verified architecture

- Airflow: `3.0.4`, `LocalExecutor`, Airflow 3 authoring interfaces from
  `airflow.sdk`.
- Google provider: `apache-airflow-providers-google==17.0.0`, the version pinned
  by the official Airflow 3.0.4 Python 3.12 constraints.
- PostgreSQL connection: `pg_dw` → `postgres:5432/ecom_dw`.
- Google connection: environment-backed `google_cloud_default`, using user ADC.
- Project: `kinetic-genre-473714-d1`.
- Bucket: `edw_bucket_k`, location `ASIA-SOUTHEAST1`.
- BigQuery datasets: `dw` and `dm`, location `asia-southeast1`.
- DAG: `postgres_to_gcs_bigquery`.

The GCP SQL Server VM is not used or started by this phase.

## Credentials and local setup

Create Application Default Credentials through the official interactive flow:

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project kinetic-genre-473714-d1
```

Do not print or copy the credential content. Set only the host path in the
ignored `airflow/.env`:

```dotenv
GOOGLE_APPLICATION_CREDENTIALS_HOST_PATH=/absolute/path/to/application_default_credentials.json
```

Compose mounts that single file at
`/opt/airflow/gcp/application_default_credentials.json:ro`. The verified host
file mode was `600`; inside the scheduler it was readable and not writable.
No service-account key or IAM change is required.

The non-secret project configuration is:

```dotenv
GCP_PROJECT_ID=kinetic-genre-473714-d1
GCS_BUCKET=edw_bucket_k
BQ_LOCATION=asia-southeast1
```

## Export contracts

The DAG publishes:

1. `dw.dim_platform` → `dw.dim_platform`.
2. Enriched `dw.fact_orders` joined to platform, customer, and date dimensions
   → `dw.fact_orders`.
3. `dm.mv_daily_sales` → `dm.daily_sales`.

All BigQuery schemas are explicit; autodetect is disabled.

- `dw.fact_orders` is partitioned by `order_date` and clustered by
  `platform_key`.
- `dm.daily_sales` is partitioned by `order_date` and clustered by
  `platform_name`.
- Fact rows include the stable keys plus `platform_code`, `platform_name`,
  `customer_natural`, and `order_date` for downstream analytics.

Objects use this exact pattern, with no wildcard:

```text
phase06/runs/<safe-Airflow-run-id>/dw/dim_platform.ndjson
phase06/runs/<safe-Airflow-run-id>/dw/fact_orders.ndjson
phase06/runs/<safe-Airflow-run-id>/dm/daily_sales.ndjson
```

The validation task checks the uploaded object generation and downloads that
exact object before any canonical load can start. Each successful load uses
`WRITE_TRUNCATE`; it never appends, so repeated same-day runs do not duplicate
rows.

## Pre-overwrite snapshots

The pre-existing canonical data had unclear legacy provenance and did not
reconcile with Phase 05. With explicit approval, three BigQuery table snapshots
were created before the first overwrite:

- `dw.dim_platform_phase06_snapshot_20260826t203454z`
- `dw.fact_orders_phase06_snapshot_20260826t203454z`
- `dm.daily_sales_phase06_snapshot_20260826t203454z`

They expire at approximately `2026-09-25T20:35:34Z` (30-day TTL). Verification
showed matching source/snapshot schema hashes and the original metrics:

- dimension rows: `12`;
- fact rows: `900452`;
- fact total: `175724694468`;
- daily represented orders: `900452`;
- daily total: `175724694468`.

Do not remove these snapshots before their TTL unless separately approved.

## Build and startup

From the repository root:

```bash
docker compose --env-file airflow/.env \
  -f airflow/docker-compose.batch.yaml \
  -f airflow/docker-compose.yaml \
  config --quiet

docker compose --env-file airflow/.env \
  -f airflow/docker-compose.batch.yaml \
  -f airflow/docker-compose.yaml \
  build airflow-init

docker compose --env-file airflow/.env \
  -f airflow/docker-compose.batch.yaml \
  -f airflow/docker-compose.yaml \
  up --force-recreate airflow-init

docker compose --env-file airflow/.env \
  -f airflow/docker-compose.batch.yaml \
  -f airflow/docker-compose.yaml \
  up -d --force-recreate \
  airflow-api-server airflow-scheduler airflow-dag-processor
```

Never use `docker compose down -v`; that deletes persistent PostgreSQL and
Airflow auth data.

## Run and verify

Use a unique, reviewable run ID:

```bash
docker exec airflow-airflow-scheduler-1 \
  airflow dags trigger postgres_to_gcs_bigquery \
  --run-id phase06_manual_YYYYMMDDTHHMMSSZ
```

Check the DAG and task states:

```bash
docker exec airflow-airflow-scheduler-1 \
  airflow dags list-runs postgres_to_gcs_bigquery --output json

docker exec airflow-airflow-scheduler-1 \
  airflow tasks states-for-dag-run \
  postgres_to_gcs_bigquery <run-id>
```

For every successful run, verify that:

- `cloud_preflight`, `export_run`, and `validate_run_objects` succeed before
  load tasks;
- all three load tasks and `verify_destinations` succeed;
- the run prefix contains exactly three NDJSON objects;
- BigQuery load jobs have exactly one `sourceUri`, matching that run prefix;
- output counts remain `3`, `245675`, and `1336` for dimension, fact, and daily
  tables respectively.

## Final verification evidence

Two consecutive same-day runs completed successfully:

- `phase06_verify_20260827T045600Z_run1` — `success`;
- `phase06_verify_20260827T045700Z_run2` — `success`.

Each run produced exactly three objects totaling `66567984` bytes
(`63.48 MiB`). The two prefixes were distinct. Six final load jobs were `DONE`,
had no error, used one exact run object each, and reported output rows:

- dimension: `3`;
- fact: `245675`;
- daily sales groups: `1336`.

After both runs:

- fact rows / distinct `(platform_code, order_nk)`: `245675 / 245675`;
- daily groups / distinct date-platform groups: `1336 / 1336`;
- daily represented orders: `245675`;
- fact and daily total sales: `50228062824`;
- per-platform order counts:
  - `lazada`: `84669`;
  - `shopee`: `140444`;
  - `tiki`: `20562`.

The counts, per-platform counts, and totals matched PostgreSQL. DAG import
errors were `[]`. Regression run
`phase03_regression_after_phase06_20260827T045900Z` succeeded.

Two earlier failed Phase 06 runs remain in Airflow history. They exposed and
helped fix a server-side cursor metadata assumption, a BigQuery schema adapter
argument, existing-table clustering compatibility, NUMERIC scale comparison,
and a reserved query alias. Their GCS objects remain for audit; no legacy or
failed-run objects were deleted.

## Stop and restart

Stop only the Airflow runtime services while preserving volumes:

```bash
docker compose --env-file airflow/.env \
  -f airflow/docker-compose.batch.yaml \
  -f airflow/docker-compose.yaml \
  stop airflow-api-server airflow-scheduler airflow-dag-processor
```

Start them again with `docker compose ... up -d` and the same two Compose files.

## Cost and cleanup considerations

- NDJSON objects and snapshots consume GCS/BigQuery storage until lifecycle or
  snapshot expiry removes them.
- BigQuery validation queries process a small amount of project data but are
  still subject to normal project billing and quota.
- This phase created no service account, key, IAM binding, firewall rule, VM,
  dataset, or bucket.
- GCS legacy objects were preserved. Cleanup of Phase 06 run objects is a
  separate lifecycle decision and is not part of this phase.

## Troubleshooting

- `DefaultCredentialsError`: confirm ADC exists, the host path is set in the
  ignored `.env`, and the Compose mount is read-only but readable.
- Dataset/bucket location mismatch: do not move or recreate resources; confirm
  all destinations use `asia-southeast1`.
- Partition/clustering incompatibility: `WRITE_TRUNCATE` cannot change an
  existing table's partition/clustering definition. Keep the verified contract
  or stop for an approved migration.
- GCS validation failure: inspect the run-specific exact object and PostgreSQL
  source; do not bypass the gate or load a wildcard.
- BigQuery count mismatch: stop before treating the run as verified; compare
  PostgreSQL and BigQuery per-platform counts and totals.

## Out of scope

- GCP SQL Server VM startup or Phase 04 re-ingestion;
- Kafka, Debezium, MySQL, GCS legacy cleanup, and Looker Studio;
- IAM/service-account changes or credential key creation;
- Phase 07 implementation.
