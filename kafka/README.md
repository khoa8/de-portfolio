
# Kafka Notes & Troubleshooting — DE Portfolio (Airflow + Spark + Debezium + Kafka)

This README summarizes key **do’s/don’ts**, **common issues**, and **fixes** for the Kafka side of this project.

> Stack highlights: Bitnami Kafka (KRaft, single node), Debezium Kafka Connect (MySQL CDC), Kafka UI, Airflow (SparkSubmitOperator), MySQL (source), Postgres (sink). All services share the Docker network `de-net`.

---

## Architecture (quick)
```
MySQL (sales.orders) --CDC--> Debezium (Kafka Connect) --topics--> Kafka
                                                              \--> Kafka UI (8082)
Kafka --Spark Structured Streaming--> Airflow Spark job --> Postgres (orders_cdc)
```
- **Airflow UI:** `http://localhost:8080`  
- **Kafka UI:** `http://localhost:8082`  
- **Kafka Connect REST:** `http://localhost:8083`  
- **Adminer:** `http://localhost:8081`

---

## Critical Docker Compose Notes

- Put **all** services that need to talk to each other on **`de-net`** (including **all Airflow services** + **Redis**, MySQL, Postgres, Kafka, Connect, Kafka UI, Adminer).
- Persist data with volumes:
  - `kafka: - kafka-data:/bitnami/kafka`
  - `postgres: - postgres-db-volume:/var/lib/postgresql/data`
  - `mysql: - mysql-data:/var/lib/mysql`
- **Do NOT** run `docker compose down -v` unless you intentionally want to wipe data (Kafka topics, Connect state, DBs).
- Airflow security/session (avoid random 500s):
  - Set `AIRFLOW__CORE__FERNET_KEY` and `AIRFLOW__WEBSERVER__SECRET_KEY` **once** and keep them.
- Kafka broker (Bitnami KRaft) must have:
  ```yaml
  environment:
    - KAFKA_ENABLE_KRAFT=yes
    - KAFKA_CFG_NODE_ID=1
    - KAFKA_CFG_PROCESS_ROLES=broker,controller
    - KAFKA_CFG_CONTROLLER_QUORUM_VOTERS=1@kafka:9093
    - KAFKA_CFG_LISTENERS=PLAINTEXT://:9092,CONTROLLER://:9093
    - KAFKA_CFG_ADVERTISED_LISTENERS=PLAINTEXT://kafka:9092
    - KAFKA_CFG_CONTROLLER_LISTENER_NAMES=CONTROLLER
    - KAFKA_CFG_INTER_BROKER_LISTENER_NAME=PLAINTEXT
    - KAFKA_CFG_AUTO_CREATE_TOPICS_ENABLE=true
    - ALLOW_PLAINTEXT_LISTENER=yes
  ```

---

## Debezium Kafka Connect — **Internal topics must be compact**
Connect requires its 3 internal topics to have `cleanup.policy=compact`:
- `_connect_offsets`
- `_connect_configs`
- `_connect_statuses`

If these are `delete`, Connect will **start then stop** and 8083 will refuse connections.

### Fix (without deleting data):
```bash
./scripts/connect_compact_and_bootstrap.sh
```
This script:
1) Alters 3 topics to `cleanup.policy=compact` (and `retention.ms=-1`),  
2) Restarts `connect`,  
3) (Re)creates/updates connector from `config/mysql_source.json`.

### Full reset (wipe Connect internals, then re-create connector):
```bash
./scripts/reset_connect_and_bootstrap.sh
```
This script deletes `_connect_*` topics, restarts `connect`, and re-creates the connector.

> Ensure your `config/mysql_source.json` contains:
> ```json
> "schema.history.internal.kafka.bootstrap.servers": "kafka:9092",
> "schema.history.internal.kafka.topic": "schema-changes.sales"
> ```

---

## MySQL privileges for Debezium
The Debezium user needs:
```sql
GRANT REPLICATION SLAVE, REPLICATION CLIENT, RELOAD, LOCK TABLES ON *.* TO 'airflow'@'%';
GRANT SELECT ON sales.* TO 'airflow'@'%';
FLUSH PRIVILEGES;
```
Typical MySQL source settings (in compose):
```
--server-id=1 --log-bin=mysql-bin --binlog-format=ROW --binlog-row-image=FULL
--gtid-mode=ON --enforce-gtid-consistency=ON
```

---

## Connector lifecycle (after reboot)

**Quick path (3 commands):**
```bash
docker compose up -d
./scripts/connect_compact_and_bootstrap.sh
docker compose run --rm airflow-cli airflow dags trigger realtime_orders
```

**Checks:**
```bash
curl -sf http://localhost:8080/api/v2/version && echo "Airflow OK"
curl -s  http://localhost:8083/ | jq .
curl -s  http://localhost:8083/connectors | jq .
curl -s  http://localhost:8083/connectors/mysql-sales-cdc/status | jq .
docker compose exec kafka bash -lc '/opt/bitnami/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --list | grep dbserver1 || true'
```

---

## Spark Streaming (reader) — must include Kafka JAR

In the Airflow DAG `realtime_orders.py`, **include** Kafka package:
```python
packages=(
  "org.postgresql:postgresql:42.7.3,"
  "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1"
)
```
- Use `3.5.1` to match `pyspark==3.5.1`.
- If no Internet access from container, download JARs and pass via `jars=`.

**Job code reminders:**
- For backfill, set `.option("startingOffsets","earliest")` (and a new checkpoint path) to replay topic from beginning.
- For “only new events”, use `latest` (default in the provided code).

---

## Snapshot vs. Streaming

- If the connector is created with:
  ```json
  "snapshot.mode": "initial",
  "snapshot.locking.mode": "none"
  ```
  Debezium will emit the **existing** rows once (snapshot) to the topic, then continue with binlog changes.
- If your Spark job started with `startingOffsets=latest`, it will **not** read old snapshot messages. Use **earliest + new checkpoint** to backfill.

---

## Data generator (demo)

Use the provided script to generate INSERT/UPDATE every 2s per job (~30s session):
```bash
./scripts/demo_stream.sh
# Optional: ITERATIONS/SLEEP_BETWEEN overrides
ITERATIONS=15 SLEEP_BETWEEN=2 ./scripts/demo_stream.sh
```
It prints every action (INSERT & UPDATE) and ends with a single-line total count.

---

## Common Errors & Fixes

### 1) Connect REST (8083) refuses connection / keeps exiting
**Symptom:** Logs show
```
Topic '_connect_offsets' ... required cleanup.policy=compact ... found 'delete'
```
**Fix:** `./scripts/connect_compact_and_bootstrap.sh` (or full reset script).

### 2) Connector shows `"connector.state": "RUNNING"` but `"tasks": []`
- Often missing `"tasks.max":"1"` or worker couldn’t spawn task.
- Fix by PUT config and restart:
  ```bash
  curl -s -X PUT http://localhost:8083/connectors/mysql-sales-cdc/config \
    -H "Content-Type: application/json" \
    -d @config/mysql_source_config_only.json | jq .
  curl -X POST http://localhost:8083/connectors/mysql-sales-cdc/restart
  ```
  Also check logs for MySQL privilege errors (RELOAD/LOCK TABLES etc.).

### 3) Kafka topic `dbserver1.sales.orders` not appearing
- Ensure connector **task** is RUNNING.
- Insert/update a row in MySQL to trigger events.
- Check Connect logs for snapshot/permission errors.

### 4) Airflow UI 500 after moving services to `de-net`
- Airflow services not on `de-net` → cannot resolve `postgres`.
- Fix: add `networks: [de-net]` to the `x-airflow-common` anchor (and `redis`).  
- Set stable `AIRFLOW__CORE__FERNET_KEY` and `AIRFLOW__WEBSERVER__SECRET_KEY`.

### 5) Spark task fails `ClassNotFound: org.apache.spark.sql.kafka010...`
- Missing Kafka JAR. Add `org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1` to `packages`.

### 6) Only new rows appear in Postgres, old rows missing
- Spark started at `latest`. Use `earliest` + new checkpoint (or prefill by CSV → Postgres).

### 7) Debezium snapshot fails with permission like:
```
Access denied; need RELOAD or FLUSH_TABLES
```
- Grant MySQL privileges shown above, then restart connector.

---

## Useful CLI

List topics:
```bash
docker compose exec kafka bash -lc '/opt/bitnami/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --list'
```

Peek messages (from beginning, 2 seconds timeout):
```bash
docker compose exec kafka bash -lc '/opt/bitnami/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server kafka:9092 --topic dbserver1.sales.orders \
  --from-beginning --timeout-ms 2000 | head -n 10'
```

Connect status:
```bash
curl -s http://localhost:8083/ | jq .
curl -s http://localhost:8083/connectors | jq .
curl -s http://localhost:8083/connectors/mysql-sales-cdc/status | jq .
```

Trigger streaming DAG:
```bash
docker compose run --rm airflow-cli airflow dags unpause realtime_orders
docker compose run --rm airflow-cli airflow dags trigger realtime_orders
```

---

## After Reboot — mini checklist
```bash
docker compose up -d
./scripts/connect_compact_and_bootstrap.sh
docker compose run --rm airflow-cli airflow dags trigger realtime_orders
# optional demo
./scripts/demo_stream.sh
```

---

## Files referenced
- `config/mysql_source.json` — Debezium connector config (contains schema history settings).
- `dags/realtime_orders.py` — Airflow DAG for Spark streaming (include Kafka JAR in `packages`).
- `spark/orders_stream_upsert.py` — Upsert logic (`INSERT ... ON CONFLICT` into Postgres).
- `dags/prefill_orders_from_csv.py` — One-shot CSV→Postgres backfill (optional).
- `scripts/demo_stream.sh` — Data generator for demo.
- `scripts/connect_compact_and_bootstrap.sh` — Alter `_connect_*` topics to compact + (re)create connector.
- `scripts/reset_connect_and_bootstrap.sh` — Full reset of Connect internals + (re)create connector.

---

Happy streaming! 🚀
