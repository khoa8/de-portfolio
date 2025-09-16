from datetime import datetime, timedelta
import pandas as pd

from airflow import DAG
# Airflow 3.x: PythonOperator ở "standard" provider (khác Airflow 2.x)
from airflow.providers.standard.operators.python import PythonOperator
# Dùng PostgresHook để lấy SQLAlchemy engine từ Airflow Connection (thay cho module_connect.*)
from airflow.providers.postgres.hooks.postgres import PostgresHook
# Đọc cấu hình Sheet ID + gid từ Airflow Variables (không hard-code)
from airflow.models import Variable

# ========= THAM SỐ HOÁ ==============
# Đọc SHEET_ID và gid từ Airflow Variables
SHEET_ID = Variable.get("sheet_id", default_var="1CEdUKoIlsAtmEG1E5P-Tt_AHS6VHGocD")
SHEET_GID = Variable.get("gid", default_var="634132054")
SHEET_CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?gid={SHEET_GID}&format=csv"

# Tên bảng đích trong Postgres
TARGET_TABLE = "e00ordertype"
PG_CONN_ID = "pg_analytics"  # chỉnh nếu đặt ID khác
# ====================================

default_args = {
    "owner": "airflow",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

def extract_data_from_ggsheet():

    # Đọc Google Sheet (CSV export) -> DataFrame.

    df = pd.read_csv(SHEET_CSV_URL)
    print("Sheet URL:", SHEET_CSV_URL)
    print("Columns:", list(df.columns))
    print("Shape:", df.shape)
    # Nếu muốn kiểm tra sâu hơn:
    # print(df.head(5).to_string(index=False))
    # Không return để tránh XCom lớn
    # (Nếu cần, có thể lưu tạm CSV ra /opt/airflow/data rồi task sau đọc lại.)

def load_data_to_pgdb():
    # 1) Đọc Sheet (CSV export)
    df = pd.read_csv(SHEET_CSV_URL)

    # 2) Chuẩn hóa tên cột -> lowercase cho khớp bảng e00ordertype
    colmap = {
        "RowID": "rowid",
        "FunctType": "functtype",
        "TypeID": "typeid",
        "TypeName": "typename",
        "FunctName": "functname",
        "CreatedBy": "createdby",
        "CreatedDate": "createddate",
        "UpdatedBy": "updatedby",
        "UpdatedDate": "updateddate",
        "StatusSync": "statussync",
        "SyncDate": "syncdate",
    }
    df = df.rename(columns=colmap)[list(colmap.values())]

    # 3) Ép kiểu & dọn dữ liệu để tránh trùng khóa
    # - RowID phải là số nguyên, không null
    df["rowid"] = pd.to_numeric(df["rowid"], errors="coerce")
    df = df[df["rowid"].notna()]
    df["rowid"] = df["rowid"].astype("int64")

    # (tuỳ chọn) ép kiểu cho cột số/nonce khác nếu cần
    # for c in ["typeid", "statussync"]:
    #     df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")

    # - Thời gian (nếu có), cho mềm để không vấp lỗi định dạng
    for c in ["createddate", "updateddate", "syncdate"]:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")

    # - LOẠI TRÙNG THEO rowid (giữ dòng cuối cùng nếu có nhiều dòng cùng rowid)
    dup_count = len(df) - df["rowid"].nunique()
    if dup_count > 0:
        print(f"Found {dup_count} duplicate rowid(s) -> dropping duplicates.")
    df = df.drop_duplicates(subset=["rowid"], keep="last")

    # 4) Kết nối DB
    hook = PostgresHook(postgres_conn_id=PG_CONN_ID)
    engine = hook.get_sqlalchemy_engine()

    # 5) Full refresh: TRUNCATE rồi nạp lại (không đụng PK vì đã loại trùng)
    with engine.begin() as conn:
        conn.execute("TRUNCATE TABLE public.e00ordertype;")

    df.to_sql(
        "e00ordertype",
        engine,
        schema="public",
        if_exists="append",
        index=False,
        method="multi",
        chunksize=1000,
    )
    print(f"Full refresh xong: {len(df)} dòng vào public.e00ordertype "
          f"(unique rowid={df['rowid'].nunique()})")

with DAG(
    dag_id="GGSheet_to_Postgres_Pipeline",
    description="Load Google Sheet (CSV export) into Postgres",
    start_date=datetime(2025, 9, 1),  # quá khứ gần, catchup=False nên không backfill
    schedule="@daily",                # chạy hằng ngày; muốn chạy tay thì đổi thành schedule=None
    catchup=False,
    default_args=default_args,
    tags=["p2", "drive", "postgres"],
) as dag:

    task1 = PythonOperator(
        task_id="load_data_from_ggsheet",
        python_callable=extract_data_from_ggsheet,
        do_xcom_push=False,  # tránh đẩy DataFrame vào metadata DB
    )

    task2 = PythonOperator(
        task_id="load_data_to_db_postgres",
        python_callable=load_data_to_pgdb,
        do_xcom_push=False,
    )

    task1 >> task2

