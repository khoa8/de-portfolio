# Phase 07 — MySQL CDC → Kafka → Spark Streaming → PostgreSQL

## Goal

Phase 07 adds an isolated local streaming path without changing the verified
batch warehouse:

```text
MySQL 8.4 orders
  -> Debezium 3.2 Kafka Connect
  -> Kafka 3.9 KRaft
  -> Spark Structured Streaming 3.5.1
  -> PostgreSQL ecom_dw.cdc
```

The bounded Airflow path uses Spark `availableNow`. It consumes all currently
available records and exits, so a LocalExecutor task never waits forever. A
separate Compose one-off supports a processing-time continuous demonstration.

## Verified architecture

The Phase 02/03 files remain the batch foundation. Phase 07 is an additive
overlay:

```text
docker-compose.batch.yaml       PostgreSQL 16 + Adminer
docker-compose.yaml             Airflow 3.0.4 + LocalExecutor
docker-compose.streaming.yaml   profile-scoped Phase 07 services
```

The `phase07` profile adds:

- `mysql`: `mysql:8.4.6`, source port `127.0.0.1:3307` on macOS;
- `kafka`: `apache/kafka:3.9.1`, single-node KRaft broker/controller;
- `connect`: `quay.io/debezium/connect:3.2.4.Final`, host endpoint
  `127.0.0.1:8083`;
- `kafka-ui`: `provectuslabs/kafka-ui:v0.7.2`, host endpoint
  `127.0.0.1:8082`;
- idempotent MySQL, PostgreSQL, Kafka-topic, connector, and checkpoint init jobs.

All four pinned third-party images were verified as native `linux/arm64`. The
batch stack can still start with only its original two Compose files; no MySQL,
Kafka, Connect, or Kafka UI service is then active.

## Credentials

Copy the Phase 07 key names from `.env.example` into ignored
`airflow/.env`. Use strong local-only values for:

```dotenv
MYSQL_CDC_ROOT_PASSWORD=<local secret>
MYSQL_CDC_PASSWORD=<local secret>
```

Do not echo, resolve, or commit these values. The verified `.env` mode was
`600`. The connector bootstrap builds its JSON request in memory from the
environment and never writes or prints the resolved configuration.

The CDC username is fixed as `debezium`; the MySQL image's `MYSQL_USER`
auto-provisioning is intentionally not used. The idempotent bootstrap revokes
existing grants before granting only `SELECT` on `phase07_shop.*` and the
global `RELOAD`, `SHOW DATABASES`, `LOCK TABLES`, `REPLICATION SLAVE`, and
`REPLICATION CLIENT` privileges required for the verified snapshot/binlog
workflow. It grants neither global `SELECT` nor `ALL` on the source database.

No cloud credential, GCP service, SQL Server VM, or BigQuery resource is used.

## Source, topics, and sinks

Versioned SQL contracts are under `sql/phase07/`:

- `001_mysql_source.sql`: idempotent `orders` source table;
- `002_postgres_sink.sql`: `cdc.order_events` and `cdc.orders_current`.

The separate `phase07_init_mysql.sh` bootstrap creates/updates the fixed
Debezium account from the ignored environment secret and reconciles its narrow
grants without exposing the password.

Kafka topic:

```text
phase07.phase07_shop.orders
```

The three Connect internal topics use `cleanup.policy=compact`. The Debezium
schema-history topic intentionally uses `cleanup.policy=delete` with
`retention.ms=-1`: Debezium 3.2 writes keyless history records, which Kafka
rejects on a compacted topic. The data topic uses `delete`. Startup only creates
missing topics or reconciles safe topic configuration; it never resets or
deletes topics or volumes.

`cdc.order_events` is append-only for the application and is uniquely keyed by
Kafka `(topic, partition, offset)`. It records `r/c/u/d`, tombstones, and
malformed records. `cdc.orders_current` upserts or soft-deletes by source order
ID only when the incoming offset is newer for the same topic/partition. This
makes database writes safe if Spark commits PostgreSQL before committing its
checkpoint and later retries the micro-batch.

The Phase 07 topic is fixed at one partition. That preserves per-order offset
ordering used by the guarded current-state upsert.

Debezium emits MySQL decimals with `decimal.handling.mode=string`. Spark parses
the string directly as `Decimal`, avoiding the precision loss that a binary
floating-point intermediate would cause for `DECIMAL(18,2)` values.

## Build and start

Run from `airflow/`:

```bash
docker compose --env-file .env \
  -f docker-compose.batch.yaml \
  -f docker-compose.yaml \
  -f docker-compose.streaming.yaml \
  --profile phase07 config --quiet

docker compose --env-file .env \
  -f docker-compose.batch.yaml \
  -f docker-compose.yaml \
  -f docker-compose.streaming.yaml \
  build airflow-init

docker compose --env-file .env \
  -f docker-compose.batch.yaml \
  -f docker-compose.yaml \
  -f docker-compose.streaming.yaml \
  --profile phase07 up -d \
  mysql kafka phase07-mysql-init phase07-kafka-init \
  connect phase07-connect-bootstrap phase07-sink-init kafka-ui

docker compose --env-file .env \
  -f docker-compose.batch.yaml \
  -f docker-compose.yaml \
  -f docker-compose.streaming.yaml \
  --profile phase07 run --rm --no-deps phase07-checkpoint-init

docker compose --env-file .env \
  -f docker-compose.batch.yaml \
  -f docker-compose.yaml \
  -f docker-compose.streaming.yaml \
  --profile phase07 up -d --force-recreate \
  airflow-api-server airflow-scheduler airflow-dag-processor
```

The checkpoint named volume is mounted at
`/opt/airflow/checkpoints/mysql_orders`, outside Airflow logs. The init job makes
it writable by the Airflow runtime without putting checkpoint files in Git.

## Run modes

The normal verification path is bounded:

```bash
docker exec airflow-airflow-scheduler-1 \
  airflow dags unpause mysql_cdc_to_postgres

docker exec airflow-airflow-scheduler-1 \
  airflow dags trigger mysql_cdc_to_postgres \
  --run-id phase07_manual_YYYYMMDDTHHMMSSZ
```

The DAG always uses `startingOffsets=earliest`. On the first run the checkpoint
starts at the earliest retained record. Later runs resume from the persistent
checkpoint rather than replaying committed offsets.

For a continuous learning demo, first start the `phase07` stack, then run the
Spark service directly rather than inside an Airflow task:

```bash
docker compose --env-file .env \
  -f docker-compose.batch.yaml \
  -f docker-compose.yaml \
  -f docker-compose.streaming.yaml \
  --profile phase07-demo run --rm phase07-spark
```

Stop the demo with `Ctrl-C`. It uses a five-second processing-time trigger and
the same durable checkpoint.

## Verification procedure

1. Confirm MySQL, Kafka, Connect, and the Airflow services are healthy.
2. Confirm connector and its single task are `RUNNING`.
3. Confirm all three Connect internal topics are compact.
4. Perform deterministic source insert, update, and delete operations.
5. Add one intentionally malformed Kafka value.
6. Trigger the bounded DAG and wait for every task to succeed.
7. Reconcile MySQL source rows, Kafka end offsets, append-only event TPOs,
   active current rows, soft-deleted rows, and amounts.
8. Trigger a second DAG run without changing the source and confirm counts do
   not increase.
9. Insert a large `DECIMAL(18,2)` probe and verify the exact string/value in
   MySQL, Kafka, the append-only JSON payload, and PostgreSQL current state.
10. Run `phase03_postgres_smoke` as the batch/Airflow regression.

## Verified evidence — 2026-08-27

- connector: `RUNNING`; task: `RUNNING`;
- Kafka data topic: one partition, end offset `8`;
- event ledger: `8` rows and `8` distinct TPOs, offsets `0..7`;
- event kinds: create `2`, update `2`, delete `1`, tombstone `1`, malformed `1`;
- MySQL source: `2` live rows, total `10000000000000025.74`;
- PostgreSQL current sink: `2` active rows, `1` soft-deleted row, active total
  `10000000000000025.74`;
- deleted order `700071`: final amount `12.50`, status `updated`, soft-deleted;
- live order `700072`: amount `25.75`, status `paid`;
- precision order `700073`: MySQL, Kafka string, event JSON string, and
  PostgreSQL amount all exactly `9999999999999999.99`;
- `phase07_hardening_20260827T073000Z_run1`: `success`;
- `phase07_hardening_20260827T073000Z_run2`: `success`;
- after run 2: event/current counts unchanged;
- checkpoint: twelve files after two additional commits, persistent named
  volume preserved;
- MySQL, Connect REST, and Kafka UI host ports are bound only to `127.0.0.1`;
- connector/task: `RUNNING/RUNNING`; decimal mode: `string`;
- Debezium grants contain no global `SELECT` and no database `ALL`;
- `phase07_hardening_regression_20260827T073000Z`: `success`;
- Airflow DAG import errors: none.

## Troubleshooting

- Connector task fails immediately: inspect its redacted task trace and verify
  the schema-history topic is `delete` with unlimited retention; only the three
  Connect internal topics should be compact.
- DAG remains queued: newly created DAGs are paused by default; unpause this DAG
  once before triggering.
- Spark cannot write its checkpoint: rerun `phase07-checkpoint-init`; do not move
  the checkpoint under `airflow/logs`.
- Spark cannot load Kafka source: rebuild the custom image. The pinned Kafka
  connector package is resolved into the image during build.
- Reapplying startup: use the idempotent init/bootstrap jobs. Do not delete
  `_connect` topics, the data topic, or any Docker volume.

## Stop and restart without data loss

Stop only Phase 07 long-running services:

```bash
docker compose --env-file .env \
  -f docker-compose.batch.yaml \
  -f docker-compose.yaml \
  -f docker-compose.streaming.yaml \
  --profile phase07 stop kafka-ui connect kafka mysql
```

Restart using the normal startup sequence. Never run `docker compose down -v`:
it would delete MySQL data, Kafka topics/state, PostgreSQL data, Airflow auth,
and Spark checkpoints.

## Out of scope

Phase 07 does not modify Phase 04–06 batch tables, use the GCP SQL Server VM,
write GCS/BigQuery, change cloud/IAM resources, operate Kafka Connect in a
multi-node production topology, or define production retention/security/SLA
policies.
