#!/usr/bin/env bash
set -Eeuo pipefail
set +x

: "${MYSQL_ROOT_PASSWORD:?MYSQL_ROOT_PASSWORD is required}"
: "${MYSQL_CDC_PASSWORD:?MYSQL_CDC_PASSWORD is required}"
: "${MYSQL_CDC_DATABASE:?MYSQL_CDC_DATABASE is required}"

if [[ "${MYSQL_CDC_DATABASE}" != "phase07_shop" ]]; then
  echo "Phase 07 MySQL bootstrap only permits database phase07_shop" >&2
  exit 1
fi

# Escape the environment-backed password for a SQL string literal without
# placing it on the process command line or printing it.
escaped_password=${MYSQL_CDC_PASSWORD//\\/\\\\}
escaped_password=${escaped_password//\'/\'\'}

export MYSQL_PWD="${MYSQL_ROOT_PASSWORD}"
mysql_args=(--host=mysql --user=root --batch --skip-column-names)

until mysql "${mysql_args[@]}" --execute="SELECT 1" >/dev/null 2>&1; do
  sleep 2
done

mysql "${mysql_args[@]}" --database="${MYSQL_CDC_DATABASE}" \
  --binary-mode < /phase07/001_mysql_source.sql

mysql "${mysql_args[@]}" <<SQL
CREATE USER IF NOT EXISTS 'debezium'@'%' IDENTIFIED BY '${escaped_password}';
ALTER USER 'debezium'@'%' IDENTIFIED BY '${escaped_password}';
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'debezium'@'%';
GRANT SELECT ON \`phase07_shop\`.* TO 'debezium'@'%';
GRANT RELOAD, SHOW DATABASES, REPLICATION SLAVE, REPLICATION CLIENT,
      LOCK TABLES ON *.* TO 'debezium'@'%';
SQL

unset MYSQL_PWD escaped_password
echo "Phase 07 source schema and least-privilege Debezium account are ready"
