# Phase 04 — SQL Server to PostgreSQL Staging

## Goal

Phase 04 recovers the batch ingestion boundary:

```text
GCP VM: SQL Server 2022 / EDW_Tech.ecom
  -> temporary SSH local-port tunnel
  -> Airflow 3.0.4 LocalExecutor
  -> Spark 3.5.1 local[*]
  -> PostgreSQL 16 / ecom_dw.stg_edw
```

The phase deliberately stops at normalized staging. RAW, DW, DM, GCS, BigQuery,
Kafka, and streaming work remain out of scope.

## Verified topology

- GCP project: `kinetic-genre-473714-d1`
- VM: `instance-20250930-145946` in `asia-southeast1-a`
- SQL Server runs in the existing `mssql` container on VM port `1433`.
- No public ingress rule permits TCP `1433`.
- The temporary tunnel binds only macOS loopback port `11433`.
- Docker Desktop reaches that listener as `host.docker.internal:11433`.
- Airflow and Spark use the same scheduler container and `LocalExecutor`.
- PostgreSQL remains the Phase 02 service at `postgres:5432` inside Compose.

The verified path is:

```text
Airflow/Spark container
  -> host.docker.internal:11433
  -> macOS 127.0.0.1:11433
  -> SSH
  -> GCP VM 127.0.0.1:1433
  -> EDW_Tech
```

Do not add a firewall rule for `1433`. Use a temporary, instance-scoped SSH key
with an expiry and remove it after the verification session.

## Local secret configuration

Create `airflow/.env` from the documented Phase 03 settings and add these keys:

```dotenv
MSSQL_HOST=host.docker.internal
MSSQL_PORT=11433
MSSQL_DATABASE=EDW_Tech
MSSQL_USER=replace_with_reader_login
MSSQL_PASSWORD=replace_with_reader_password
MSSQL_ENCRYPT=true
MSSQL_TRUST_SERVER_CERTIFICATE=false
```

`airflow/.env` must remain ignored by Git and mode `600`. Never put credentials
in DAG arguments, Spark command lines, JDBC URLs, logs, or source files.

The verified local login is `de_phase04_reader`. It has no server role or
database-role membership. Its only explicit database privileges are `CONNECT`
and object-level `SELECT` on the three source tables.

The live SQL Server uses a self-generated certificate and has no configured TLS
certificate. The committed default therefore remains certificate validation on.
For this specific temporary tunnel, the ignored local `.env` used
`MSSQL_TRUST_SERVER_CERTIFICATE=true` after a failed validation probe proved the
self-generated-certificate condition. Encryption remained enabled.

## Source and target contract

| Source table | Source fields | Target table | Platform |
| --- | --- | --- | --- |
| `ecom.E01LazadaOrders` | `orderNumber`, `createTime`, `status`, `customerName`, `paidPrice` | `stg_edw.e01_lazada_orders` | `lazada` |
| `ecom.E01ShopeeOrders` | `MaDonHang`, `NgayDatHang`, `TrangThaiDonHang`, `NguoiMua`, `TongSoTienNguoiMuaThanhToan` | `stg_edw.e01_shopee_orders` | `shopee` |
| `ecom.E01TikiOrders` | `MaDonHang`, `NgayDat`, `TrangThai`, typed-null buyer, `ThanhTien` | `stg_edw.e01_tiki_orders` | `tiki` |

Canonical column order is:

```text
order_id text
order_date timestamp without time zone
order_status text
buyer_name text
total_amount numeric(18,2)
platform text
```

Live source date formats include `dd MMM yyyy HH:mm`, `yyyy-MM-dd HH:mm`,
`dd/MM/yyyy`, and `d/M/yyyy`. The Spark job records any nonblank value that
cannot be converted instead of silently discarding it.

## Image and JDBC dependencies

The custom Airflow image pins and checksum-verifies:

- Microsoft JDBC `13.4.0.jre11`
- PostgreSQL JDBC `42.7.7`
- Java 17
- PySpark `3.5.1`
- Spark provider `5.2.1`

JAR files are downloaded during image build and are never committed.

```bash
docker compose \
  -f airflow/docker-compose.batch.yaml \
  -f airflow/docker-compose.yaml \
  config --quiet

docker compose \
  -f airflow/docker-compose.batch.yaml \
  -f airflow/docker-compose.yaml \
  build airflow-api-server
```

## Tunnel and startup lifecycle

Start the existing VM only when needed. Use existing approved SSH access and a
temporary key; placeholders below must be resolved locally without committing
them:

```bash
ssh -N \
  -i ~/.ssh/de_portfolio_phase04_ed25519 \
  -o IdentitiesOnly=yes \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=15 \
  -o ServerAliveCountMax=3 \
  -L 127.0.0.1:11433:127.0.0.1:1433 \
  <linux-user>@<vm-external-ip>
```

Validate connectivity from the actual scheduler container before running the
DAG. A successful macOS connection alone is insufficient.

```bash
docker compose \
  -f airflow/docker-compose.batch.yaml \
  -f airflow/docker-compose.yaml \
  up -d --no-build airflow-api-server airflow-scheduler airflow-dag-processor
```

## DAG and atomic publish design

`mssql_ecom_to_stg` has no schedule, no catchup, and at most one active run. Its
flow is:

```text
verify_runtime_configuration
  -> prepare_phase04_tables
  -> extract_lazada_to_load
     extract_shopee_to_load
     extract_tiki_to_load
  -> validate_and_publish
  -> cleanup_phase04_load_tables
```

Spark appends only to disposable load tables. PostgreSQL then validates all
three counts and publishes all canonical targets in one transaction. The
canonical tables are truncated without `CASCADE` and refilled with explicit
columns; they are never dropped or recreated by Spark. This avoids Spark JDBC
`overwrite`, which can drop PostgreSQL targets and break dependent objects.

## Trigger and verification

```bash
docker compose \
  -f airflow/docker-compose.batch.yaml \
  -f airflow/docker-compose.yaml \
  exec -T airflow-scheduler \
  airflow dags trigger --run-id <unique-run-id> mssql_ecom_to_stg
```

Verify the DAG state, every task state, `stg_edw.phase04_batch_audit`, canonical
row counts, and empty disposable load tables. Run the DAG twice against the same
source snapshot; counts must remain stable rather than accumulate.

## Verified evidence — 2026-08-26

Final successful runs:

- `phase04_verify_20260826T164900Z_run3`
- `phase04_verify_20260826T165000Z_run4`

Both runs produced identical metrics:

| Platform | Source | Load | Published | Date failures | Amount failures |
| --- | ---: | ---: | ---: | ---: | ---: |
| Lazada | 149,139 | 149,139 | 149,139 | 0 | 0 |
| Shopee | 244,799 | 244,799 | 244,799 | 0 | 0 |
| Tiki | 34,423 | 34,423 | 34,423 | 0 | 0 |

All seven Phase 04 tasks were `success` on both runs. Load tables and
`phase04_load_metrics` were empty after cleanup. The second run did not inflate
canonical counts. DAG import errors were empty. Phase 03 regression run
`phase03_regression_20260826T165100Z` also succeeded.

Airflow metadata remained in `postgres:5432/airflow`; Phase 04 tables existed
only in `postgres:5432/ecom_dw`. The internal Task Execution API remained
`http://airflow-api-server:8080/execution/`.

## Stop, restart, and cleanup

- Stop the tunnel with `Ctrl-C` in its owning terminal.
- Remove the exact temporary public key entry from instance metadata.
- Verify all prior metadata entries remain unchanged, then delete the temporary
  local key pair.
- Stop the GCP VM when the source is no longer needed.
- Normal Compose stop/restart must preserve PostgreSQL volumes.

Never run `docker compose down -v`, delete the PostgreSQL volume, drop either
database, use `TRUNCATE ... CASCADE`, or expose SQL Server port `1433` publicly.

## Troubleshooting

- `connection refused`: confirm the VM, `mssql` container, listener, tunnel, and
  scheduler-container TCP path in that order.
- certificate validation failure: inspect the actual server certificate first;
  never set `encrypt=false`. Use the documented ignored local exception only for
  the verified self-generated certificate.
- Spark defaults to YARN: verify Airflow connection `spark_local` resolves to
  `local[*]`.
- conversion failures: inspect the source format and add a regression test;
  never hide failures by dropping rows.
- count mismatch: do not publish; retain the previous canonical transaction and
  inspect the load/audit evidence.

## Out of scope

Phase 05 transformations, incremental loading, scheduling, production TLS,
GCS/BigQuery, Kafka/Debezium/MySQL, and production credential management remain
out of scope.
