# Spark – Notes & Gotchas (thực hành trong dự án này)
## 0) Kiến trúc & triết lý

Tách 2 file:

jobs/*.py = Spark job thuần (chạy bằng spark-submit, chứa logic đọc/transform/ghi).

dags/*.py = Airflow orchestration (lịch, retry, phụ thuộc, alert), gọi SparkSubmitOperator.

Local mode trước, cluster sau: phát triển ban đầu chạy --master local[*]. Khi có cluster (Spark Standalone/YARN/K8s), đổi connection mà không sửa job.

## 1) Build image để KHÔNG mất Java/PySpark khi recreate

Dockerfile (đặt trong airflow/): cài openjdk-17-jdk + pyspark, build thành image riêng của bạn.

docker-compose.yaml → dùng build: (không dùng _PIP_ADDITIONAL_REQUIREMENTS để cài mỗi lần start).

Test nhanh:
```
docker compose exec airflow-worker bash -lc 'java -version; python -c "import pyspark; print(pyspark.__version__)"'
```

Nếu thiếu Java/PySpark → job fail với lỗi JAVA_HOME is not set / ModuleNotFoundError: pyspark.

## 2) Airflow ↔ Spark (SparkSubmitOperator)

Tạo Connection: spark_conn

Conn Type: Spark

Host: local[*] (hoặc set master="local[*]" trực tiếp trong SparkSubmitOperator)

JDBC driver nên khai báo trong operator:
```
packages="org.postgresql:postgresql:42.7.3,mysql:mysql-connector-java:8.0.33"
```

Xem log: phải thấy lệnh sinh ra có --master local[*]. Nếu là --master yarn mà bạn không có YARN ⇒ sẽ fail.

## 3) Mount & đường dẫn file

CSV, staging data để tại airflow/data (host) → container thấy ở /opt/airflow/data.

Tên file có dấu ngoặc vuông/khoảng trắng dễ gây lỗi path; nên đổi tên sạch (snake_case).

Kiểm tra trong container:
```
docker compose exec airflow-worker ls -l /opt/airflow/data
```
## 4) CSV & header/encoding/tên cột

Dùng:
```
(spark.read
  .option("header","true")
  .option("sep", ",")
  .option("encoding","utf-8")
  .option("inferSchema","true")
  .csv("/opt/airflow/data/danhsach.csv"))
```

Sanitize header (khuyến nghị): đổi về lowercase + _ để tránh lỗi tên cột có dấu/khoảng trắng/ký tự lạ.

Nếu bạn cần giữ nguyên tên cột → đừng sanitize, nhưng cẩn thận khi dùng trong SQL/select().

## 5) Kiểu dữ liệu & thời gian (hay dính lỗi)

CSV thường có 'NULL' chuỗi → cần chuẩn hoá về NULL thực trước khi cast.

Với timestamp có millis: "yyyy-MM-dd HH:mm:ss.SSS".
Dọn dữ liệu rồi cast an toàn:
```
from pyspark.sql import functions as F

df = (df
  .withColumn("created_at_raw", F.regexp_replace(F.col("created_at_raw"), r"(?i)^null$", None))
  .withColumn("created_at",
      F.to_timestamp("created_at_raw", "yyyy-MM-dd HH:mm:ss.SSS"))
)
```

Nếu dữ liệu xấu, dùng F.when(...).otherwise(None) trước khi to_timestamp.

## 6) Ghi JDBC (Postgres/MySQL)

Mẫu ghi:
```
(df.write.mode("append").format("jdbc")
   .option("url", "jdbc:postgresql://postgres:5432/airflow")
   .option("driver", "org.postgresql.Driver")
   .option("dbtable", "public.danhsach")
   .option("user", "airflow")
   .option("password", "airflow")
   # tuning
   .option("batchsize", "10000")
   .option("numPartitions", "4")   # nếu bảng đích chịu được
   .save())
```

Schema tạo tự động: nếu bảng chưa có, Spark suy đoán kiểu. Với bảng quan trọng, tạo trước bằng SQL (đúng kiểu & constraint).

Upsert: Spark JDBC không có upsert “native”. Hai hướng thực tế:

Ghi vào bảng tạm stg_*, rồi chạy MERGE/INSERT...ON CONFLICT bằng PostgresHook/MySQLHook.

Dùng foreachBatch (Streaming) để tự viết upsert (phức tạp hơn).

## 7) Hiệu năng cơ bản

Partitioning khi đọc/ghi JDBC:
```
.option("partitionColumn", "id")
.option("lowerBound", "1")
.option("upperBound", "1000000")
.option("numPartitions", "8")
```

Balance giữa numPartitions và tài nguyên Postgres/MySQL (connection/locks). Đừng đặt quá cao nếu DB yếu.

CSV lớn: repartition(n) trước khi ghi để song song tốt hơn; file nhỏ: coalesce(1) để giảm overhead.

## 8) Logging & debug

Đọc log ở Airflow task (driver). Nếu cần log executor chi tiết:

Với local mode, log chủ yếu nằm ở driver.

In df.printSchema() và df.show(5, truncate=False) trước khi ghi để kiểm tra type.

Lỗi hay gặp:

PATH_NOT_FOUND → path CSV sai hoặc mount thiếu.

UNRESOLVED_COLUMN → sai tên cột (do header/ sanitize / gõ nhầm).

CAST_INVALID_INPUT → dữ liệu bẩn trước khi cast timestamp/number.

JAVA_GATEWAY_EXITED → thiếu Java/JAVA_HOME.

## 9) Airflow scheduling, idempotency

Với full reload → mode="overwrite" (cẩn thận lock/permission, và truncate có thể nhanh hơn).

Với incremental:

Filter nguồn theo updated_at/id > last_max_id → chỉ ghi phần mới.

Hoặc chiến lược upsert như mục 6.

Đặt schedule=None khi test; bật lịch sau khi ổn.

## 10) Cấu trúc repo gợi ý
airflow/
├─ dags/
│  ├─ spark_csv_to_postgres.py
│  └─ spark_postgres_to_mysql.py
├─ jobs/
│  ├─ csv_to_postgres.py
│  └─ etl_pg_to_mysql.py
├─ data/
│  └─ danhsach.csv
├─ Dockerfile        # cài openjdk-17 + pyspark
└─ docker-compose.yaml

## 11) Mẹo “đổi cấu hình không cần sửa code”

Biến CSV_PATH, TARGET_TBL, WRITE_MODE… thành Airflow Variables:

UI → Admin → Variables → key: spark_csv_path / spark_target_table…

Trong DAG: đọc bằng from airflow.sdk import Variable.

Hoặc thêm application_args vào SparkSubmitOperator từ Variables.

## 12) ARM/M1 ghi chú

Bạn đang chạy Docker trong Ubuntu VM → tránh lệch kiến trúc.

Nếu build native trên ARM host: chọn image/Java tương thích (openjdk-17 OK).

Với driver JDBC: dùng phiên bản ổn định (Postgres 42.7.x, MySQL 8.0.33+).

## 13) Checklist nhanh trước khi run

 Image Airflow đã bake Java + PySpark (build OK).

 spark_conn = local[*] (hoặc master="local[*]" trong operator).

 CSV thấy được trong container tại /opt/airflow/data/....

 JDBC packages đúng version.

 Bảng đích: tạo sẵn (nếu cần schema chuẩn) hoặc để Spark tự tạo.

 Null/‘NULL’/timestamp đã dọn nếu cần cast.

## 14) Lệnh hay dùng
#Build & up
```
docker compose build --no-cache
docker compose up -d
```
#Kiểm tra file/Java/Spark
```
docker compose exec airflow-worker ls -l /opt/airflow/data
docker compose exec airflow-worker bash -lc 'java -version; python -c "import pyspark; print(pyspark.__version__)"'
```
#Run spark-submit tay (debug nhanh)
```
docker compose exec airflow-worker bash -lc '
spark-submit --master local \
  --packages org.postgresql:postgresql:42.7.3 \
  /opt/airflow/jobs/csv_to_postgres.py \
  --csv /opt/airflow/data/danhsach.csv \
  --table public.danhsach --mode append --sep , --header true'
```
#Kiểm tra Postgres
```
docker compose exec postgres psql -U airflow -d airflow -c "SELECT COUNT(*) FROM public.danhsach;"
```
