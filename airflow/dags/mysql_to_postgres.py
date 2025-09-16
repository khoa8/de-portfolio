from datetime import datetime, timedelta
import os, csv
import pandas as pd

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from airflow.providers.mysql.hooks.mysql import MySqlHook
from airflow.providers.postgres.hooks.postgres import PostgresHook

# --- Cấu hình cơ bản ---
DATA_DIR = "/opt/airflow/data"        # map từ ./data ngoài host
MYSQL_CONN_ID = "mysql_src"            # bạn tạo trong Airflow UI
PG_CONN_ID    = "pg_analytics"         # bạn đã dùng ở pipeline 1/2
TARGET_TABLE  = "fact_sales"           # bảng đích ở Postgres

# SQL nguồn MySQL (đổi theo bảng thực tế của bạn)
MYSQL_SQL = """
SELECT
  id,
  madonhang,
  ngaydat,
  masanpham,
  slban,
  dongia,
  doanhthu,
  trangthaidonghang
FROM sales.fact_sales;
"""

def extract_mysql_to_csv(**ctx):
    """Kết nối MySQL (qua Airflow Connection) -> SELECT -> ghi CSV vào /opt/airflow/data"""
    ds_nodash = ctx["ds_nodash"]
    csv_path = os.path.join(DATA_DIR, f"mysql_fact_sales_{ds_nodash}.csv")
    os.makedirs(DATA_DIR, exist_ok=True)

    m = MySqlHook(mysql_conn_id=MYSQL_CONN_ID)
    df = m.get_pandas_df(MYSQL_SQL)
    df.to_csv(csv_path, index=False, encoding="utf-8", quoting=csv.QUOTE_MINIMAL)
    print(f"Extracted {len(df)} rows -> {csv_path}")

    # Đưa đường dẫn cho task sau dùng
    ctx["ti"].xcom_push(key="csv_path", value=csv_path)

def load_csv_to_postgres_fullrefresh(**ctx):
    """Full refresh: TRUNCATE bảng đích rồi nạp CSV (COPY -> staging -> INSERT)"""
    csv_path = ctx["ti"].xcom_pull(
    task_ids="extract_mysql_to_csv",
    key="csv_path"
)
    p = PostgresHook(postgres_conn_id=PG_CONN_ID)

    with p.get_conn() as conn, conn.cursor() as cur:
        # Tạo bảng đích nếu chưa có (chỉnh schema theo dữ liệu thực của bạn)
        cur.execute(f"""
        CREATE TABLE IF NOT EXISTS public.{TARGET_TABLE}(
          id                 BIGINT PRIMARY KEY,
          madonhang          TEXT,
          ngaydat            TIMESTAMP,
          masanpham          TEXT,
          slban              INT,
          dongia             NUMERIC,
          doanhthu           NUMERIC,
          trangthaidonghang  TEXT
        );
        """)

        # Xoá sạch dữ liệu cũ
        cur.execute(f"TRUNCATE TABLE public.{TARGET_TABLE};")

        # Staging tạm TEXT để COPY dễ, rồi ép kiểu khi INSERT
        cur.execute("DROP TABLE IF EXISTS stg_fact_sales;")
        cur.execute("""
        CREATE TEMP TABLE stg_fact_sales(
          id                 TEXT,
          madonhang          TEXT,
          ngaydat            TEXT,
          masanpham          TEXT,
          slban              TEXT,
          dongia             TEXT,
          doanhthu           TEXT,
          trangthaidonghang  TEXT
        );
        """)

        with open(csv_path, "r", encoding="utf-8") as f:
            cur.copy_expert("""
                COPY stg_fact_sales(id, madonhang, ngaydat, masanpham, slban, dongia, doanhthu, trangthaidonghang)
                FROM STDIN WITH CSV HEADER
            """, f)

        cur.execute(f"""
        INSERT INTO public.{TARGET_TABLE}(
            id, madonhang, ngaydat, masanpham, slban, dongia, doanhthu, trangthaidonghang
        )
        SELECT
            NULLIF(id,'')::bigint,
            NULLIF(madonhang,'')::text,
            NULLIF(ngaydat,'')::timestamp,
            NULLIF(masanpham,'')::text,
            NULLIF(slban,'')::int,
            NULLIF(dongia,'')::numeric,
            NULLIF(doanhthu,'')::numeric,
            NULLIF(trangthaidonghang,'')::text
        FROM stg_fact_sales;
        """)
    print(f"Full refresh done -> public.{TARGET_TABLE} from {csv_path}")

default_args = {"retries": 1, "retry_delay": timedelta(minutes=5)}

with DAG(
    dag_id="MySQL_to_Postgres_Pipeline",
    description="Extract MySQL -> CSV (/data) -> Postgres (full refresh)",
    start_date=datetime(2025, 9, 1),
    schedule=None,      # chạy tay; ổn rồi hãy đổi '@daily'
    catchup=False,
    default_args=default_args,
    tags=["p3","mysql","postgres"],
) as dag:

    extract = PythonOperator(
        task_id="extract_mysql_to_csv",
        python_callable=extract_mysql_to_csv,
    )

    load = PythonOperator(
        task_id="load_csv_to_postgres_fullrefresh",
        python_callable=load_csv_to_postgres_fullrefresh,
    )

    extract >> load

