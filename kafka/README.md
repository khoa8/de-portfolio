# Kafka and CDC notes

This directory is a concise companion to the canonical
[Phase 07 runbook](../docs/runbooks/07-mysql-kafka-spark-streaming.md). The
active implementation is defined by `airflow/docker-compose.streaming.yaml`,
not by legacy scripts or connector JSON files retained elsewhere in the
repository.

## Verified topology

```text
MySQL phase07_shop.orders
  -> Debezium connector phase07-mysql-orders-cdc
  -> Kafka topic phase07.phase07_shop.orders
  -> Spark Structured Streaming
  -> PostgreSQL cdc.order_events + cdc.orders_current
```

- Kafka image: `apache/kafka:3.9.1`, single-node KRaft.
- Connect image: `quay.io/debezium/connect:3.2.4.Final`.
- Kafka UI image: `provectuslabs/kafka-ui:v0.7.2`.
- Compose network: `de_network`.
- MySQL, Connect REST, and Kafka UI bind to macOS loopback only.
- The batch stack does not start streaming services unless the `phase07`
  profile is selected.

## Safe startup and validation

Run from the repository root:

```bash
docker compose --env-file airflow/.env \
  -f airflow/docker-compose.batch.yaml \
  -f airflow/docker-compose.yaml \
  -f airflow/docker-compose.streaming.yaml \
  --profile phase07 config --quiet

docker compose --env-file airflow/.env \
  -f airflow/docker-compose.batch.yaml \
  -f airflow/docker-compose.yaml \
  -f airflow/docker-compose.streaming.yaml \
  --profile phase07 up -d \
  mysql kafka phase07-mysql-init phase07-kafka-init \
  connect phase07-connect-bootstrap phase07-sink-init kafka-ui
```

Use `config --quiet`; resolved Compose output can contain environment-backed
credentials.

Safe health checks:

```bash
curl --fail --silent http://127.0.0.1:8083/connectors \
  >/dev/null
curl --fail --silent --output /dev/null \
  http://127.0.0.1:8082/
```

Inspect connector status without printing its resolved configuration or
password:

```bash
curl --fail --silent \
  http://127.0.0.1:8083/connectors/phase07-mysql-orders-cdc/status
```

## Topic and checkpoint contracts

The bootstrap creates topics idempotently with `--if-not-exists`:

- `phase07_connect_configs`, `phase07_connect_offsets`, and
  `phase07_connect_statuses` use `cleanup.policy=compact`;
- `phase07_schema_history` uses `delete` with unlimited retention because
  Debezium writes keyless schema-history records;
- `phase07.phase07_shop.orders` is a one-partition data topic.

Spark uses `startingOffsets=earliest` for a new checkpoint and resumes from the
persistent `phase07_spark_checkpoints` volume thereafter. The Airflow DAG uses
the bounded `availableNow` trigger; the optional `phase07-demo` profile uses a
processing-time trigger outside Airflow.

Never delete or recreate topics, offsets, the MySQL/Kafka volumes, or the Spark
checkpoint as a normal startup or troubleshooting step.

## Data and security contracts

- Debezium emits MySQL decimals as strings. The verified `DECIMAL(18,2)` probe
  `9999999999999999.99` reaches PostgreSQL without a floating-point
  intermediate.
- The fixed `debezium` account receives `SELECT` only on
  `phase07_shop.*` plus the global snapshot/binlog privileges documented in the
  Phase 07 runbook. It receives no global `SELECT` and no database `ALL`.
- `cdc.order_events` is append-only and unique by Kafka
  topic-partition-offset.
- `cdc.orders_current` uses newer-offset guarded upserts and soft deletes.
- Create/read/update/delete events, tombstones, and malformed values are all
  handled explicitly.

## Legacy artifacts

The following files are historical references and are not the active Phase 07
startup path:

- `airflow/config/mysql_source.json`;
- `airflow/dags/realtime_orders.py`;
- `airflow/scripts/connect_compact_and_bootstrap.sh`;
- `airflow/scripts/reset_connect_and_bootstrap.sh`;
- `airflow/scripts/demo_stream.sh`;
- `spark/orders_stream_upsert.py`.

They remain source-controlled for migration history. Do not use their reset
workflow, connection names, topic names, images, or Airflow 2 patterns for the
verified stack.

## Stop without losing state

```bash
docker compose --env-file airflow/.env \
  -f airflow/docker-compose.batch.yaml \
  -f airflow/docker-compose.yaml \
  -f airflow/docker-compose.streaming.yaml \
  --profile phase07 stop kafka-ui connect kafka mysql
```

Do not add `-v` to a shutdown command. See the
[Phase 07 runbook](../docs/runbooks/07-mysql-kafka-spark-streaming.md) for the
full lifecycle, verification evidence, and troubleshooting procedure.
