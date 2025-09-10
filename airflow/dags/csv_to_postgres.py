from datetime import datetime, timedelta
import pandas as pd

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator  # Airflow 3.x
from airflow.providers.postgres.hooks.postgres import PostgresHook

CSV_PATH = "/opt/airflow/data/[rms].[E01OrderHeader].csv"  # đã mount từ ./data

def load_data_to_dataframe():
    # Đọc một phần đầu để thử nhanh; bỏ nrows nếu muốn nạp hết
    df = pd.read_csv(CSV_PATH, nrows=100)
    return df

def load_data_to_pgdb():
    df = load_data_to_dataframe()
    # Lấy SQLAlchemy engine từ Airflow Connection (không cần module_connect)
    engine = PostgresHook(postgres_conn_id="pg_analytics").get_sqlalchemy_engine()
    # Ghi vào bảng public."E01OrderHeader" (tên bảng đúng như yêu cầu)
    df.to_sql("E01OrderHeader", engine, schema="public", if_exists="append", index=False)

default_args = {
    "owner": "airflow",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="CSV_to_Postgres_Pipeline",
    start_date=datetime(2025, 9, 1),
    schedule=None,              # chạy tay cho đơn giản
    catchup=False,
    default_args=default_args,
    tags=["p1","localfile","postgres"],
) as dag:
    task1 = PythonOperator(task_id="first_task",  python_callable=load_data_to_dataframe)
    task2 = PythonOperator(task_id="second_task", python_callable=load_data_to_pgdb)

    task1 >> task2

