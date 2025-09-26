#!/usr/bin/env bash
set -euo pipefail

# ======= Config có thể override qua env khi chạy =======
COMPOSE="${COMPOSE:-docker compose}"                 # hoặc "docker-compose"
BS="${BS:-kafka:9092}"                               # bootstrap server trong docker net
CONNECT_HOST="${CONNECT_HOST:-http://localhost:8083}"
CONNECT_NAME="${CONNECT_NAME:-mysql-sales-cdc}"
CONNECT_CONFIG_FILE="${CONNECT_CONFIG_FILE:-config/mysql_source.json}"

# ======= Helpers =======
log() { echo -e "$@"; }

wait_kafka() {
  log "[*] Đợi Kafka sẵn sàng..."
  for i in {1..30}; do
    if $COMPOSE exec -T kafka bash -lc "/opt/bitnami/kafka/bin/kafka-topics.sh --bootstrap-server $BS --list >/dev/null 2>&1"; then
      log "[✓] Kafka OK"; return 0; fi
    sleep 2
  done
  log "[x] Kafka chưa sẵn sàng"; exit 1
}

ensure_topic_compact() {
  local t="$1"
  log "[*] Sửa topic $t -> cleanup.policy=compact, retention.ms=-1"
  $COMPOSE exec -T kafka bash -lc "\
/opt/bitnami/kafka/bin/kafka-configs.sh --bootstrap-server $BS \
  --alter --entity-type topics --entity-name $t \
  --add-config cleanup.policy=compact,retention.ms=-1 >/dev/null 2>&1 || true"
  # verify
  $COMPOSE exec -T kafka bash -lc "\
/opt/bitnami/kafka/bin/kafka-configs.sh --bootstrap-server $BS \
  --entity-type topics --entity-name $t --describe | grep -E 'cleanup.policy|retention.ms' || true"
}

restart_connect() {
  log "[*] Restart service connect"
  $COMPOSE restart connect >/dev/null
}

wait_connect() {
  log "[*] Đợi Connect REST ${CONNECT_HOST} ..."
  for i in {1..30}; do
    if curl -fsS "${CONNECT_HOST}" >/dev/null; then
      log "[✓] Connect REST OK"; return 0; fi
    sleep 2
  done
  log "[x] Connect REST chưa lên"; exit 1
}

upsert_connector() {
  log "[*] Khởi tạo/cập nhật connector: ${CONNECT_NAME}"
  if curl -fsS "${CONNECT_HOST}/connectors/${CONNECT_NAME}" >/dev/null; then
    # PUT cần "config phẳng"
    jq '.config' "${CONNECT_CONFIG_FILE}" > /tmp/config_only.json
    curl -fsS -X PUT "${CONNECT_HOST}/connectors/${CONNECT_NAME}/config" \
      -H "Content-Type: application/json" \
      --data-binary @/tmp/config_only.json >/dev/null
    curl -fsS -X POST "${CONNECT_HOST}/connectors/${CONNECT_NAME}/restart" >/dev/null
    log "[✓] Updated & restarted ${CONNECT_NAME}"
  else
    curl -fsS -X POST "${CONNECT_HOST}/connectors" \
      -H "Content-Type: application/json" \
      --data-binary @"${CONNECT_CONFIG_FILE}" >/dev/null
    log "[✓] Created ${CONNECT_NAME}"
  fi
}

# ======= Main =======
log "== Compact _connect_* topics + restart Connect + (re)create connector =="

wait_kafka
for t in _connect_offsets _connect_configs _connect_statuses; do
  ensure_topic_compact "$t"
done

restart_connect
wait_connect
upsert_connector

log "[✓] Hoàn tất. Kiểm tra nhanh:"
log "    curl -s ${CONNECT_HOST}/connectors/${CONNECT_NAME}/status | jq . || true"
