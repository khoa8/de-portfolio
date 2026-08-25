# Phase 03 — Airflow setup

## Goal

Run a reproducible local Apache Airflow 3.0.4 environment on macOS Docker Desktop, using `LocalExecutor`, the Phase 02 PostgreSQL service, and a read-only smoke DAG against `ecom_dw`.

This is a local learning environment. SimpleAuthManager is intentionally used for development only.

## Verified architecture

```text
macOS
  └── Docker Compose project: airflow
      ├── postgres (PostgreSQL 16)
      │   ├── airflow  — Airflow metadata
      │   └── ecom_dw  — business data
      ├── adminer
      ├── airflow-api-server
      ├── airflow-scheduler (LocalExecutor task processes)
      ├── airflow-dag-processor
      └── airflow-init (one-off migration and secret preparation)
```

`airflow/docker-compose.batch.yaml` owns PostgreSQL, Adminer, `de_postgres_data`, and `de_network`. `airflow/docker-compose.yaml` adds only the Airflow services and the non-database `airflow_auth` volume. Both files must be supplied to the same Compose command so the service DNS name `postgres` and network are shared.

The active Phase 03 runtime has no Redis, Celery worker, Flower, triggerer, Kafka, Debezium Connect, Kafka UI, or MySQL service.

## Why LocalExecutor

This phase runs on one Docker Desktop host and has no distributed-worker requirement. `LocalExecutor` executes parallel task subprocesses in the scheduler container, avoiding the Redis/Celery operational layer while still exercising Airflow 3's scheduler and Task Execution API path.

## Configuration and secrets

Create the local environment file once if it does not already exist:

```bash
cd airflow
cp .env.example .env
```

Edit `.env` locally and never commit it. The required PostgreSQL keys are `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, and `POSTGRES_HOST_PORT`. `AIRFLOW_UID` and `AIRFLOW_UI_USERNAME` are optional; their local defaults are `50000` and `airflow`.

Do not print resolved Compose configuration because it contains environment-expanded credentials. Validate it quietly:

```bash
docker compose --env-file .env \
  -f docker-compose.batch.yaml \
  -f docker-compose.yaml \
  config --quiet
```

Airflow metadata uses `postgres:5432/airflow`. The environment-backed `AIRFLOW_CONN_PG_DW` is JSON and resolves safely as:

```text
connection ID: pg_dw
type:          postgres
host:          postgres
port:          5432
database:      ecom_dw
```

Port `5433` is only the PostgreSQL port exposed to macOS. Airflow containers must use `postgres:5432`.

The init service generates a shared Task Execution API JWT secret and Fernet key in the `airflow_auth` named volume with mode `600`. These values are not stored in `.env`, Compose, or Git. Preserve that volume during normal stop/restart operations.

## Build and start

Build the custom ARM64-compatible image. It retains Java 17, PySpark, the Spark provider, and Kafka client dependencies for later phases, and adds the PostgreSQL provider/PostgresHook.

```bash
docker compose --env-file .env \
  -f docker-compose.batch.yaml \
  -f docker-compose.yaml \
  build airflow-init
```

Run the idempotent metadata migration and auth-volume preparation:

```bash
docker compose --env-file .env \
  -f docker-compose.batch.yaml \
  -f docker-compose.yaml \
  up airflow-init
```

Start the long-running services:

```bash
docker compose --env-file .env \
  -f docker-compose.batch.yaml \
  -f docker-compose.yaml \
  up -d airflow-api-server airflow-scheduler airflow-dag-processor
```

Check service health:

```bash
docker compose --env-file .env \
  -f docker-compose.batch.yaml \
  -f docker-compose.yaml \
  ps
curl --fail http://localhost:8080/api/v2/version
```

The UI is at `http://localhost:8080`.

## SimpleAuthManager login

Airflow 3.0.4 SimpleAuthManager reads users from `core.simple_auth_manager_users`. The configured local username receives the `admin` role; authentication is not globally disabled.

On first API-server startup, SimpleAuthManager natively generates a 16-character password and stores it in `/opt/airflow/auth/simple_auth_manager_passwords.json.generated` inside the `airflow_auth` named volume. Retrieve it only when needed from your own terminal, then avoid copying it into documentation or Git:

```bash
docker compose --env-file .env \
  -f docker-compose.batch.yaml \
  -f docker-compose.yaml \
  exec airflow-api-server \
  sh -c 'cat "$AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_PASSWORDS_FILE"'
```

This is the native Airflow 3.0.4 SimpleAuthManager workflow. Airflow 2 FAB commands, `_AIRFLOW_WWW_USER_*`, and `AIRFLOW_ADMIN_*` variables are not used.

## DAG quarantine

`airflow/dags/.airflowignore` uses Airflow 3's configured `glob` syntax. It lists exactly the seven legacy DAG filenames. Those files remain version-controlled and unchanged; Airflow does not parse them until their later-phase dependencies are restored.

`phase03_postgres_smoke.py` is the only active Phase 03 DAG. It uses the public `airflow.sdk` DAG/task authoring interfaces and the provider's official `PostgresHook`. Its query is read-only and verifies:

- `current_database()` is `ecom_dw`;
- schema `raw` exists;
- table `raw.orders_raw` exists.

## Verification procedure

```bash
docker compose --env-file .env \
  -f docker-compose.batch.yaml \
  -f docker-compose.yaml \
  exec airflow-scheduler airflow dags list --output=json

docker compose --env-file .env \
  -f docker-compose.batch.yaml \
  -f docker-compose.yaml \
  exec airflow-scheduler airflow dags list-import-errors --output=json

docker compose --env-file .env \
  -f docker-compose.batch.yaml \
  -f docker-compose.yaml \
  exec airflow-scheduler airflow dags unpause phase03_postgres_smoke

docker compose --env-file .env \
  -f docker-compose.batch.yaml \
  -f docker-compose.yaml \
  exec airflow-scheduler airflow dags trigger phase03_postgres_smoke
```

Confirm the DAG-run and task states in the UI or with read-only metadata queries. The scheduler must resolve `airflow-api-server`, and the effective internal URL must be `http://airflow-api-server:8080/execution/`, never `localhost`.

## Verified evidence (2026-08-26, Asia/Ho_Chi_Minh)

- Built `de-airflow:3.0.4` for `arm64` successfully.
- Runtime versions: Airflow `3.0.4`, PostgreSQL provider `6.2.3`, Java `17`, PySpark `3.5.1`.
- Effective executor: `LocalExecutor`.
- Effective auth manager: `airflow.api_fastapi.auth.managers.simple.simple_auth_manager.SimpleAuthManager`.
- Examples: `false`; DAG ignore syntax: `glob`.
- Init/migration exited `0`; metadata revision: `fe199e1abd77`.
- API server, scheduler, DAG processor, and PostgreSQL were healthy; Adminer returned HTTP `200`.
- The scheduler resolved `airflow-api-server` and received HTTP `200` from its version endpoint.
- `pg_dw` resolved to `postgres:5432/ecom_dw` without exposing its password.
- Airflow metadata database contained `45` public tables; none of the checked Airflow metadata tables appeared in `ecom_dw`.
- DAG list contained only `phase03_postgres_smoke`; import-error list was empty.
- Successful run ID: `phase03_verify_20260825T195300Z`; DAG run and task state: `success`.
- Task evidence: `database=ecom_dw, raw_schema=true, orders_table=true`.

### Runtime-driven implementation detail

The first task attempt proved that separate Airflow processes generated different default JWT secrets: the execution endpoint returned `403` with `Invalid auth token: Signature verification failed`. The final implementation therefore generates one JWT secret during init and shares it through `airflow_auth`. After recreating the Airflow services, the second smoke run succeeded end to end. The triggerer, Redis, and Celery were not required.

## Stop and restart without data loss

Stop only Airflow and leave PostgreSQL/Adminer running:

```bash
docker compose --env-file .env \
  -f docker-compose.batch.yaml \
  -f docker-compose.yaml \
  stop airflow-api-server airflow-scheduler airflow-dag-processor
```

Restart with the normal start command. To remove containers and the network while preserving named volumes, `docker compose ... down` is non-destructive to volumes, but it also stops PostgreSQL and Adminer.

> **Destructive command warning:** never run `docker compose down -v`, `docker volume rm`, or an equivalent command for this project unless permanent deletion of PostgreSQL data and generated Airflow auth material is explicitly intended and approved.

## Troubleshooting

- `Permission denied` for the SimpleAuth password file: rerun `airflow-init`; it prepares ownership and mode in `airflow_auth`.
- Execution API `403` / signature verification failure: verify init completed, the JWT file exists, and recreate the API server and scheduler so both read the same secret.
- API health does not become healthy: inspect redacted API logs and check `http://localhost:8080/api/v2/version`.
- DAG missing: confirm `.airflowignore` does not match the smoke file, then check `airflow dags list-import-errors`.
- Database connection error: verify the safe `pg_dw` fields and use `postgres:5432` inside Docker, not host port `5433`.
- Metadata tables in the wrong database: stop and inspect configuration; do not drop or reset either database.

## Out of scope

Phase 03 does not repair or execute legacy DAGs, start Phase 04, run Spark jobs, or start MSSQL, BigQuery, GCS, Kafka, Debezium, MySQL, Redis, Celery, Flower, or a triggerer. It does not change cloud/IAM resources or delete any persistent volume.
