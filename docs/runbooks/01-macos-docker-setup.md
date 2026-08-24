# Phase 01 — macOS Docker Development Environment

## Goal

Set up the local foundation for the Data Engineering portfolio directly on macOS using Docker Desktop. This runbook is intended to work from a clean checkout and does not depend on the old UTM VM.

## Architecture

```text
macOS
  ├── Git
  ├── VS Code / Terminal
  └── Docker Desktop
       ├── de_postgres
       └── de_adminer
```

Airflow, Spark, Kafka, MySQL, and Debezium are intentionally not started in this phase.

## Prerequisites

```bash
git --version
docker --version
docker compose version

docker info --format \
'Server: {{.ServerVersion}} | OS: {{.OperatingSystem}} | Arch: {{.Architecture}}'
```

The current development machine uses Apple Silicon (`aarch64`).

## Clone the repository

```bash
cd ~/Projects
git clone https://github.com/khoa8/de-portfolio.git
cd de-portfolio
```

During recovery work, development was performed on:

```bash
git switch -c portfolio-recovery
```

Future users should use the appropriate current development branch.

## Environment variables

The real local environment file is:

```text
airflow/.env
```

It must not be committed.

Example local values:

```dotenv
POSTGRES_USER=airflow
POSTGRES_PASSWORD=airflow
POSTGRES_DB=airflow
POSTGRES_HOST_PORT=5433
```

The repository should contain `airflow/.env.example` with placeholder/default development values.

## Why host port 5433?

Another local project already uses `localhost:5432`, so this project maps:

```text
macOS localhost:5433
        ↓
PostgreSQL container:5432
```

Inside the Docker network, containers still use:

```text
postgres:5432
```

`5433` is host-facing. `5432` remains the PostgreSQL container port.

## Docker Compose file

The lightweight batch-development Compose file is:

```text
airflow/docker-compose.batch.yaml
```

At this phase it contains only PostgreSQL and Adminer.

## Validate Compose

```bash
docker compose \
  -f airflow/docker-compose.batch.yaml \
  config
```

This parses Compose and resolves `.env` variables without starting services.

## Start services

```bash
docker compose \
  -f airflow/docker-compose.batch.yaml \
  up -d
```

Check status:

```bash
docker compose \
  -f airflow/docker-compose.batch.yaml \
  ps
```

Expected services:

```text
de_postgres
de_adminer
```

PostgreSQL should become healthy.

## Verify PostgreSQL

```bash
docker exec de_postgres \
  psql -U airflow -d airflow \
  -c "SELECT version();"
```

No host installation of `psql` is required because this command runs inside the PostgreSQL container.

## Adminer

Adminer is available at:

```text
http://localhost:8081
```

Use:

```text
System:   PostgreSQL
Server:   postgres
Username: airflow
Password: <value from .env>
Database: airflow
```

Do not use `localhost` as the server name from Adminer. Adminer is itself a container and reaches PostgreSQL through Docker DNS using the service name `postgres`.

## Docker networking concept

```text
Mac browser
   ↓ localhost:8081
Adminer container
   ↓ postgres:5432
PostgreSQL container
```

## Docker volume concept

```text
de_postgres container
        ↓
named Docker volume
        ↓
persistent database files
```

Stopping or recreating the container does not automatically delete the database volume.

To stop without deleting data:

```bash
docker compose \
  -f airflow/docker-compose.batch.yaml \
  down
```

To delete the local Compose volume as well:

```bash
docker compose \
  -f airflow/docker-compose.batch.yaml \
  down -v
```

Use `-v` carefully.

## Verification checklist

The phase is complete when:

- Docker Desktop is running.
- The repository is available locally.
- `.env` is ignored by Git.
- `de_postgres` is healthy.
- PostgreSQL is exposed on host port `5433`.
- `de_adminer` is reachable on host port `8081`.
- Adminer can connect to `postgres:5432`.
- Existing containers from other projects remain unaffected.

## Key concepts learned

### Container isolation

Different projects can run independent PostgreSQL containers at the same time if host ports do not conflict.

### Host port vs container port

`localhost:5433` and `postgres:5432` refer to different network contexts.

### Service discovery

Docker Compose services reach each other using service names such as `postgres`.

### Persistent volumes

Containers are disposable runtime instances. Persistent database files belong in volumes.

## Verified result

This phase was successfully verified on macOS with Docker Desktop on Apple Silicon.

```text
macOS
   │
   ├── localhost:5433 ──→ de_postgres:5432
   │
   └── localhost:8081 ──→ de_adminer:8080
                              │
                              └── postgres:5432
```

The next phase creates the separate business database and PostgreSQL data-layer schemas.
