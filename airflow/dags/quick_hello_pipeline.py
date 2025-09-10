from datetime import datetime
from airflow import DAG
from airflow.operators.python import PythonOperator

def extract():
    print("Extracting raw data...")

def transform():
    print("Transforming data...")

def load():
    print("Loading data...")

with DAG(
    dag_id="quick_hello_pipeline",
    start_date=datetime(2025, 9, 1),
    schedule=None,
    catchup=False,
    tags=["mini"],
):
    t1 = PythonOperator(task_id="extract", python_callable=extract)
    t2 = PythonOperator(task_id="transform", python_callable=transform)
    t3 = PythonOperator(task_id="load", python_callable=load)
    t1 >> t2 >> t3
