#!/usr/bin/env bash
set -euo pipefail

bootstrap_server="${KAFKA_BOOTSTRAP_SERVERS:-kafka:9092}"
cdc_topic="${KAFKA_CDC_TOPIC:-phase07.phase07_shop.orders}"
kafka_bin="/opt/kafka/bin"

ensure_topic() {
  local topic="$1"
  local cleanup_policy="$2"

  "${kafka_bin}/kafka-topics.sh" \
    --bootstrap-server "${bootstrap_server}" \
    --create --if-not-exists \
    --topic "${topic}" \
    --partitions 1 \
    --replication-factor 1 >/dev/null

  "${kafka_bin}/kafka-configs.sh" \
    --bootstrap-server "${bootstrap_server}" \
    --alter \
    --entity-type topics \
    --entity-name "${topic}" \
    --add-config "cleanup.policy=${cleanup_policy}" >/dev/null
}

for topic in \
  phase07_connect_configs \
  phase07_connect_offsets \
  phase07_connect_statuses
do
  ensure_topic "${topic}" compact
done

ensure_topic phase07_schema_history delete
"${kafka_bin}/kafka-configs.sh" \
  --bootstrap-server "${bootstrap_server}" \
  --alter \
  --entity-type topics \
  --entity-name phase07_schema_history \
  --add-config retention.ms=-1 >/dev/null
ensure_topic "${cdc_topic}" delete

for topic in \
  phase07_connect_configs \
  phase07_connect_offsets \
  phase07_connect_statuses
do
  description=$("${kafka_bin}/kafka-configs.sh" \
    --bootstrap-server "${bootstrap_server}" \
    --entity-type topics \
    --entity-name "${topic}" \
    --describe)
  if [[ "${description}" != *"cleanup.policy=compact"* ]]; then
    echo "Phase 07 topic policy verification failed for ${topic}" >&2
    exit 1
  fi
done

echo "Phase 07 Kafka topics are present; all Connect internal topics are compact."
