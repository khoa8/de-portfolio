# airflow/dags/spark_csv_to_postgres.py
# DAG gọi spark-submit để chạy job spark/spark_csv_to_postgres.py
from datetime import datetime
from airflow import DAG
from airflow.providers.apache.spark.operators.spark_submit import SparkSubmitOperator

# Đường dẫn file CSV trong container airflow-worker
CSV_PATH   = "/opt/airflow/data/danhsach.csv"
TARGET_TBL = "public.danhsach"
WRITE_MODE = "append"

with DAG(
    dag_id="spark_csv_to_postgres",
    start_date=datetime(2025, 9, 1),
    schedule=None,
    catchup=False,
    tags=["spark","csv","postgres"],
    doc_md="""
    # Spark CSV -> Postgres
    Đọc file CSV (`/opt/airflow/data/danhsach.csv`) và ghi vào Postgres (bảng `public.danhsach`) bằng Spark.
    """,
) as dag:

    run_spark = SparkSubmitOperator(
        task_id="csv_to_postgres",
        application="/opt/airflow/spark/spark_csv_to_postgres.py",
        conn_id="spark_conn",   # Tạo Airflow Connection 'spark_conn': Conn Type=Spark, Host='local' (nếu chạy local mode)
        packages="org.postgresql:postgresql:42.7.3",
        application_args=[
            "--csv",   CSV_PATH,
            "--table", TARGET_TBL,
            "--mode",  WRITE_MODE,
            "--sep",   ",",
            "--header","true",
        ],
        # Một vài cấu hình nhẹ, tuỳ máy
        conf={
            "spark.driver.memory": "1g",
            "spark.executor.memory": "1g",
        },
    )

