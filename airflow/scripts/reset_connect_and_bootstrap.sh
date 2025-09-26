#!/usr/bin/env bash
set -euo pipefail

COMPOSE="docker compose"         # nếu bạn dùng docker-compose, đổi biến này
CONNECT_HOST=${CONNECT_HOST:-http://localhost:8083}
CONNECT_NAME=${CONNECT_NAME:-mysql-sales-cdc}
CONNECT_CONFIG_FILE=${CONNECT_CONFIG_FILE:-config/mysql_source.json}

# ---- helpers ----
wait_kafka() {
  echo "[*] Chờ Kafka healthy..."
  $COMPOSE ps kafka
  # kiểm tra liệt kê topic cho tới khi OK
  for i in {1..30}; do
    if $COMPOSE exec -T kafka bash -lc '/opt/bitnami/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --list >/dev/null 2>&1'; then
      echo "[✓] Kafka sẵn sàng"
      return 0
    fi
    sleep 2
  done
  echo "[x] Kafka chưa sẵn sàng"; exit 1
}

wait_connect() {
  echo "[*] Chờ Kafka Connect REST trên 8083..."
  for i in {1..30}; do
    if curl -fsS "$CONNECT_HOST" >/dev/null; then
      echo "[✓] Connect REST sẵn sàng"; return 0
    fi
    sleep 2
  done
  echo "[x] Connect REST chưa sẵn sàng"; exit 1
}

delete_connect_topics() {
  echo "[*] Xoá 3 topic nội bộ _connect_* (Connect sẽ tự tạo lại)"
  $COMPOSE exec -T kafka bash -lc '\
  for t in _connect_offsets _connect_configs _connect_statuses; do
    /opt/bitnami/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --topic "$t" --delete || true;
  done'
  echo "[✓] Đã xoá (hoặc không tồn tại)"
}

restart_connect() {
  echo "[*] Restart service connect"
  $COMPOSE restart connect
}

upsert_connector() {
  echo "[*] Khởi tạo/ cập nhật connector: $CONNECT_NAME"
  # Nếu đã tồn tại → PUT config “phẳng”; nếu chưa → POST wrapper
  if curl -fsS "$CONNECT_HOST/connectors/$CONNECT_NAME" >/dev/null; then
    jq '.config' "$CONNECT_CONFIG_FILE" > /tmp/config_only.json
    curl -fsS -X PUT "$CONNECT_HOST/connectors/$CONNECT_NAME/config" \
      -H "Content-Type: application/json" \
      --data-binary @/tmp/config_only.json >/dev/null
    curl -fsS -X POST "$CONNECT_HOST/connectors/$CONNECT_NAME/restart" >/dev/null
    echo "[✓] Updated & restarted $CONNECT_NAME"
  else
    curl -fsS -X POST "$CONNECT_HOST/connectors" \
      -H "Content-Type: application/json" \
      --data-binary @"$CONNECT_CONFIG_FILE" >/dev/null
    echo "[✓] Created $CONNECT_NAME"
  fi
}

# ---- main flow ----
echo "== Kafka Connect reset & bootstrap =="
wait_kafka
delete_connect_topics
restart_connect
wait_connect
upsert_connector

echo "[✓] Xong. Kiểm tra:"
echo "    curl -s $CONNECT_HOST/connectors/$CONNECT_NAME/status | jq ."
