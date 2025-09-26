# spark/orders_stream_upsert.py
# Đọc Kafka topic Debezium (dbserver1.sales.orders) -> UPSERT vào Postgres (public.a_sep22_orders_cdc)

import os
import psycopg2
from contextlib import closing
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, from_json
from pyspark.sql.types import StructType, StructField, IntegerType, DoubleType, StringType

# 1) Khai báo schema cho payload Debezium
after_schema = StructType([
    StructField("id", IntegerType()),
    StructField("user_id", IntegerType()),
    StructField("amount", DoubleType()),
    StructField("status", StringType()),
    StructField("updated_at", StringType()),
])
payload_schema = StructType([
    StructField("before", StringType()),
    StructField("after", after_schema),
    StructField("op", StringType()),  # 'c' (create), 'u' (update), 'd' (delete)
])
value_schema = StructType([StructField("payload", payload_schema)])

# 2) Thông số Postgres (đã chạy trong compose)
PG_HOST = os.getenv("PG_URL", "postgres")
PG_DB   = os.getenv("PG_DB", "airflow")
PG_USR  = os.getenv("PG_USR", "airflow")
PG_PWD  = os.getenv("PG_PWD", "airflow")
PG_PORT = os.getenv("PG_PORT","5432")
TARGET  = "public.a_sep22_orders_cdc"   # Bảng đích, khóa chính = id

# 3) Spark session
spark = (SparkSession.builder
         .appName("orders_cdc_stream_upsert")
         .config("spark.sql.shuffle.partitions", "2")
         .getOrCreate())

# 4) Đọc stream từ Kafka
kdf = (spark.readStream
       .format("kafka")
       .option("kafka.bootstrap.servers", "kafka:9092")
       .option("subscribe", "dbserver1.sales.orders")
       .option("startingOffsets", "latest")  # đổi 'earliest' nếu muốn replay
       .load())

# 5) Parse JSON Debezium -> lấy trường 'after' (trạng thái mới)
j = kdf.selectExpr("CAST(value AS STRING) AS s") \
       .select(from_json(col("s"), value_schema).alias("v"))

rows = j.select(
    col("v.payload.after.id").alias("id"),
    col("v.payload.after.user_id").alias("user_id"),
    col("v.payload.after.amount").alias("amount"),
    col("v.payload.after.status").alias("status"),
    col("v.payload.after.updated_at").alias("updated_at"),
    col("v.payload.op").alias("op")
).where(col("op").isin("c","u")).dropna(subset=["id"])

# 6) ---- ĐÂY LÀ PHẦN UPSERT (foreachBatch) ----
def upsert_batch(df, epoch):
    """
    Nhận 1 micro-batch từ stream và thực hiện UPSERT vào Postgres:
      - Nếu id CHƯA tồn tại -> INSERT
      - Nếu id ĐÃ tồn tại   -> UPDATE các cột theo bản ghi mới
    """
    # Thu gọn DataFrame rồi chuyển sang Pandas để executemany
    pdf = df.select("id","user_id","amount","status","updated_at").toPandas()
    if pdf.empty:
        return

    with closing(psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USR, password=PG_PWD
    )) as conn, conn, conn.cursor() as cur:
        # Tạo bảng nếu chưa có (PK = id)
        cur.execute(f"""
          CREATE TABLE IF NOT EXISTS {TARGET}(
            id INT PRIMARY KEY,
            user_id INT,
            amount DOUBLE PRECISION,
            status VARCHAR(50),
            updated_at TIMESTAMP
          );
        """)

        # ----- CÂU LỆNH UPSERT CỐT LÕI -----
        # INSERT ... ON CONFLICT (id) DO UPDATE ...
        upsert_sql = f"""
          INSERT INTO {TARGET} (id, user_id, amount, status, updated_at)
          VALUES (%s, %s, %s, %s, %s)
          ON CONFLICT (id) DO UPDATE SET
            user_id   = EXCLUDED.user_id,
            amount    = EXCLUDED.amount,
            status    = EXCLUDED.status,
            updated_at= EXCLUDED.updated_at;
        """
        cur.executemany(upsert_sql, list(pdf.itertuples(index=False, name=None)))

# 7) Gắn foreachBatch & checkpoint
(rows.writeStream
     .outputMode("update")  # hoặc 'append', vì ta tự upsert
     .option("checkpointLocation", "/opt/airflow/logs/chk/orders_cdc_upsert/")
     .foreachBatch(upsert_batch)
     .start()
     .awaitTermination())

