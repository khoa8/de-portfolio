#!/usr/bin/env bash
set -euo pipefail

# ==== cấu hình ====
ITERATIONS=${ITERATIONS:-10}
SLEEP_BETWEEN=${SLEEP_BETWEEN:-3}
MYSQL_USER=${MYSQL_USER:-airflow}
MYSQL_PASS=${MYSQL_PASS:-airflow}
MYSQL_DB=${MYSQL_DB:-sales}
MYSQL_SVC=${MYSQL_SVC:-mysql}

# chạy SQL KHÔNG in header ( -N ) & xuất TSV ( -B )
run_sql_out () {
  docker compose exec -T "${MYSQL_SVC}" \
    mysql -N -B -u"${MYSQL_USER}" -p"${MYSQL_PASS}" -D "${MYSQL_DB}" -e "$1"
}

run_sql () {
  docker compose exec -T "${MYSQL_SVC}" \
    mysql -u"${MYSQL_USER}" -p"${MYSQL_PASS}" -D "${MYSQL_DB}" -e "$1"
}

echo "== Demo streaming: INSERT rồi UPDATE cách nhau ${SLEEP_BETWEEN}s, lặp ${ITERATIONS} vòng =="

# Bảo đảm bảng tồn tại
run_sql "
CREATE TABLE IF NOT EXISTS orders (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  amount DECIMAL(10,2) NOT NULL,
  status VARCHAR(50) NOT NULL,
  updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
"

for i in $(seq 1 "${ITERATIONS}"); do
  echo "--- vòng ${i}/${ITERATIONS} ---"

  # ========== INSERT: user_id trong khoảng 1..1000 ==========
  # Chèn và lấy lại thông tin hàng vừa chèn
  ins_row=$(run_sql_out "
    SET @uid := FLOOR(RAND()*1000)+1;
    SET @amt := ROUND(RAND()*100,2);
    INSERT INTO orders (user_id, amount, status, updated_at)
    VALUES (@uid, @amt, 'new', NOW());
    SELECT id, user_id, amount, status FROM orders WHERE id = LAST_INSERT_ID();
  ")
  # ins_row dạng TSV: id \t user_id \t amount \t status
  IFS=$'\t' read -r ins_id ins_uid ins_amt ins_status <<< "$ins_row"
  echo "--INSERT -> id=${ins_id}, user_id=${ins_uid}, amount=${ins_amt}, status=${ins_status}"

  sleep "${SLEEP_BETWEEN}"

  # ========== UPDATE ngẫu nhiên 1 đơn hiện có ==========
  upd_row=$(run_sql_out "
    SET @rid := (SELECT id FROM orders ORDER BY RAND() LIMIT 1);
    UPDATE orders
       SET status = CASE FLOOR(RAND()*3)
                      WHEN 0 THEN 'paid'
                      WHEN 1 THEN 'shipped'
                      ELSE 'cancelled'
                    END,
           amount = ROUND(amount + (RAND()*10-5), 2),
           updated_at = NOW()
     WHERE id = @rid;
    SELECT id, user_id, amount, status FROM orders WHERE id = @rid;
  ")
  IFS=$'\t' read -r upd_id upd_uid upd_amt upd_status <<< "$upd_row"
  echo "--UPDATE -> id=${upd_id}, user_id=${upd_uid}, amount=${upd_amt}, status=${upd_status}"

  sleep "${SLEEP_BETWEEN}"
done


total=$(run_sql_out "SELECT COUNT(*) FROM orders;")
echo "Total orders: ${total}"

