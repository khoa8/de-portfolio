from datetime import datetime
from airflow import DAG
from airflow.providers.apache.spark.operators.spark_submit import SparkSubmitOperator

with DAG(
    dag_id="realtime_orders",
    start_date=datetime(2025, 9, 1),
    schedule="@once",
    catchup=False,
    tags=["kafka","cdc","spark"],
    doc_md="""
    Đọc CDC MySQL từ Kafka -> upsert Postgres (a_sep22_orders_cdc).
    """
) as dag:

    spark_stream = SparkSubmitOperator(
        task_id="orders_stream_upsert",
        application="/opt/airflow/spark/orders_stream_upsert.py",
        conn_id="spark_conn",
        packages=(
            "org.postgresql:postgresql:42.7.3,"
            "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1"
        )
    )

