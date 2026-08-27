#!/usr/bin/env python3
"""Create or update the Phase 07 Debezium connector without writing resolved config."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request


CONNECTOR_NAME = "phase07-mysql-orders-cdc"


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment key: {name}")
    return value


def _request(url: str, method: str = "GET", payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read()
    return json.loads(body) if body else {}


def main() -> None:
    connect_url = os.environ.get("KAFKA_CONNECT_URL", "http://connect:8083").rstrip("/")
    database = os.environ.get("MYSQL_CDC_DATABASE", "phase07_shop")
    password = _required("MYSQL_CDC_PASSWORD")

    config = {
        "connector.class": "io.debezium.connector.mysql.MySqlConnector",
        "tasks.max": "1",
        "database.hostname": "mysql",
        "database.port": "3306",
        "database.user": "debezium",
        "database.password": password,
        "database.server.id": "184054",
        "database.include.list": database,
        "table.include.list": f"{database}.orders",
        "topic.prefix": "phase07",
        "include.schema.changes": "false",
        "snapshot.mode": "initial",
        "snapshot.locking.mode": "minimal",
        "decimal.handling.mode": "string",
        "time.precision.mode": "connect",
        "tombstones.on.delete": "true",
        "schema.history.internal.kafka.bootstrap.servers": "kafka:9092",
        "schema.history.internal.kafka.topic": "phase07_schema_history",
        "schema.history.internal.store.only.captured.tables.ddl": "true",
        "topic.creation.enable": "true",
        "topic.creation.default.partitions": "1",
        "topic.creation.default.replication.factor": "1",
    }

    for attempt in range(30):
        try:
            _request(connect_url)
            break
        except (OSError, urllib.error.URLError):
            if attempt == 29:
                raise RuntimeError("Kafka Connect did not become ready")
            time.sleep(2)

    _request(
        f"{connect_url}/connectors/{CONNECTOR_NAME}/config",
        method="PUT",
        payload=config,
    )
    _request(
        f"{connect_url}/connectors/{CONNECTOR_NAME}/restart"
        "?includeTasks=true&onlyFailed=true",
        method="POST",
    )

    for attempt in range(30):
        try:
            status = _request(f"{connect_url}/connectors/{CONNECTOR_NAME}/status")
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and attempt < 29:
                time.sleep(2)
                continue
            raise
        connector_state = status.get("connector", {}).get("state")
        task_states = [task.get("state") for task in status.get("tasks", [])]
        if connector_state == "RUNNING" and task_states == ["RUNNING"]:
            print(
                f"Connector {CONNECTOR_NAME}: connector=RUNNING, tasks=1/1 RUNNING"
            )
            return
        if any(state == "FAILED" for state in task_states) and attempt >= 10:
            raise RuntimeError("Debezium connector task entered FAILED state")
        time.sleep(2)

    raise RuntimeError("Debezium connector did not reach RUNNING state")


if __name__ == "__main__":
    main()
