# airflow/spark/spark_csv_to_postgres.py
# Mục tiêu: đọc CSV (UTF-8) -> ghi vào Postgres qua JDBC
# Dùng lại được cho nhiều file nhờ tham số dòng lệnh: --csv, --table, --mode, --sep, --header

import re
import argparse
from pyspark.sql import SparkSession

def sanitize_col(name: str) -> str:
    """Chuẩn hoá tên cột: lowercase, thay khoảng trắng/ký tự lạ bằng '_'."""
    s = re.sub(r"\s+", "_", name.strip().lower())
    s = re.sub(r"[^0-9a-z_]", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "col"

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv",   required=True, help="Đường dẫn CSV trong container (vd: /opt/airflow/data/danhsach.csv)")
    p.add_argument("--table", required=True, help="Bảng đích (vd: public.danhsach)")
    p.add_argument("--mode",  default="append", choices=["append", "overwrite"], help="append/overwrite (mặc định append)")
    p.add_argument("--sep",   default=",", help="Delimiter (mặc định ',')")
    p.add_argument("--header", default="true", choices=["true","false"], help="CSV có header? (default true)")
    args = p.parse_args()

    spark = (
        SparkSession.builder
        .appName("CSV->Postgres")
        # JDBC drivers sẽ được Spark tự kéo về khi submit (packages), nhưng thêm ở đây cũng OK
        .config("spark.jars.packages", "org.postgresql:postgresql:42.7.3")
        .getOrCreate()
    )

    # 1) Đọc CSV
    df = (
        spark.read
        .option("header", args.header)
        .option("sep", args.sep)
        .option("inferSchema", "true")  # đoán kiểu cơ bản
        .option("encoding", "utf-8")
        .csv(args.csv)
    )

    # 2) Chuẩn hoá tên cột để khỏi gặp lỗi tên cột có dấu/khoảng trắng
    df = df.toDF(*[sanitize_col(c) for c in df.columns])

    # 3) Ghi vào Postgres
    (
        df.write.mode(args.mode).format("jdbc")
        .option("url", "jdbc:postgresql://postgres:5432/airflow")           # host/service trong docker-compose
        .option("driver", "org.postgresql.Driver")
        .option("dbtable", args.table)                                       # ví dụ: public.danhsach
        .option("user", "airflow").option("password", "airflow")
        .save()
    )

    print(f"[OK] Wrote {df.count()} rows to {args.table} (mode={args.mode})")
    spark.stop()

if __name__ == "__main__":
    main()

