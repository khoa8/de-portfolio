from datetime import datetime, timedelta
import io, re
import pandas as pd

from airflow import DAG
from airflow.sdk import Variable
from airflow.providers.standard.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook

PG_CONN_ID = "pg_analytics"

def _norm(s: str) -> str:
    return re.sub(r"[^0-9a-zA-Z_]", "_", re.sub(r"\s+", "_", s.strip())).lower()

def sel_expr(col: str, casts: dict) -> str:
    base = f'NULLIF("{col}", \'\')'   # rỗng -> NULL
    typ = casts.get(col)
    return f"{base}::{typ}" if typ else base

def upsert_all():
    sources = Variable.get("gdrive_sources", deserialize_json=True)
    hook = PostgresHook(postgres_conn_id=PG_CONN_ID)
    with hook.get_conn() as conn, conn.cursor() as cur:
        for src in sources:
            sid, gid   = src["sheet_id"], src["gid"]
            table      = src["target_table"]
            keys       = src["keys"]
            colmap     = src.get("column_map")
            casts      = src.get("casts", {})

            url = f"https://docs.google.com/spreadsheets/d/{sid}/export?gid={gid}&format=csv"
            df = pd.read_csv(url)

            # chuẩn hoá tên cột
            if colmap: df = df.rename(columns=colmap)
            else:      df.columns = [_norm(c) for c in df.columns]

            # chắc chắn có cột khóa + dedup theo khóa
            for k in keys:
                if k not in df.columns:
                    raise ValueError(f"Missing key '{k}' for table {table}")
            df = df.drop_duplicates(subset=keys, keep="last")

            cols = list(df.columns)
            key_sql = ", ".join(f'"{k}"' for k in keys)
            col_defs = ", ".join(f'"{c}" TEXT' for c in cols)
            col_list = ", ".join(f'"{c}"' for c in cols)
            non_key = [c for c in cols if c not in keys]
            upd_set = ", ".join(f'"{c}"=EXCLUDED."{c}"' for c in non_key) or ""

            # tạo bảng & index khóa nếu chưa có (generic TEXT; nếu bảng typed sẵn thì lệnh này không đè)
            cur.execute(f'CREATE TABLE IF NOT EXISTS public."{table}" ({col_defs});')
            cur.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS "{table}_uniq_{"_".join(keys)}" ON public."{table}" ({key_sql});')

            # staging tạm
            cur.execute("DROP TABLE IF EXISTS stg_generic;")
            cur.execute(f'CREATE TEMP TABLE stg_generic ({col_defs});')

            # COPY từ memory (không ghi ra đĩa)
            buf = io.StringIO()
            df.to_csv(buf, index=False)
            buf.seek(0)
            cur.copy_expert(f'COPY stg_generic({col_list}) FROM STDIN WITH CSV HEADER', buf)

            # INSERT ... ON CONFLICT (UPSERT)
            select_cols = ", ".join(sel_expr(c, casts) for c in cols)
            on_conflict = f"ON CONFLICT ({key_sql}) DO NOTHING" if not upd_set \
                          else f"ON CONFLICT ({key_sql}) DO UPDATE SET {upd_set}"
            cur.execute(f'''
                INSERT INTO public."{table}"({col_list})
                SELECT {select_cols} FROM stg_generic
                {on_conflict};
            ''')

            print(f"UPSERT OK -> {table} (rows={len(df)}, keys={keys})")

default_args = {"retries": 1, "retry_delay": timedelta(minutes=5)}

with DAG(
    dag_id="GGSheet_to_Postgres_Upsert_Pipeline",
    start_date=datetime(2025, 9, 1),
    schedule=None,
    catchup=False,
    default_args=default_args,
) as dag:
    PythonOperator(task_id="load_gsheets_upsert_to_postgres", python_callable=upsert_all)

