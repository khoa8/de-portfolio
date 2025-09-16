# Airflow (local via Docker Compose)
## Yêu cầu
- Docker / Docker Compose
- Tạo file `.env` từ mẫu:
  cp .env.example .env
  #Nếu dùng Linux: AIRFLOW_UID=$(id -u)

## Chạy lần đầu
```
docker compose up airflow-init
docker compose up -d
```

Mở UI: http://localhost:8080  (user/pass: airflow/airflow)

## Thư mục
- dags/: đặt các DAG .py
- data/: dữ liệu mẫu (raw/processed/warehouse)
- plugins/: plugin Airflow (nếu có)

## Dừng
docker compose down   # giữ volumes
#hoặc xóa sạch:
```docker compose down -v```

## Local File to Postgres
Chép CSV về đúng chỗ (lưu ý tên file có ngoặc vuông → nhớ bọc trong dấu nháy khi dùng shell):
```
mkdir -p data
cp "[rms].[E01OrderHeader].csv" data/
```

Tạo Connection Postgres trong Airflow UI:
Conn Id: pg_analytics
Type: Postgres
Host: postgres · DB/schema: airflow · User/Pass: airflow/airflow · Port: 5432
#Xem vài dòng đầu
```
docker compose exec postgres \
  psql -U airflow -d airflow -c 'SELECT * FROM public."E01OrderHeader" LIMIT 5;'
```
Nếu giữ Connection kiểu “đúng chuẩn” (user de, DB analytics) thì thay -U airflow -d airflow thành -U de -d analytics.

# Airflow – 3 pipelines căn bản (Local CSV → Postgres, Google Sheet → Postgres, MySQL → Postgres)
## 0) Kiến trúc & thư mục
de-portfolio/
└─ airflow/
   ├─ dags/                   # DAGs Airflow
   ├─ data/                   # dữ liệu local (CSV)  ← được mount vào container
   ├─ plugins/                # (tùy chọn) code phụ trợ
   ├─ spark/                  # (tùy chọn) job Spark
   ├─ config/ logs/
   └─ docker-compose.yaml     # stack Airflow 3 (apiserver)


Airflow 3.x: service UI là airflow-apiserver (không còn webserver). UI tại http://localhost:8080.

Mount bắt buộc (trong docker-compose.yaml, khối x-airflow-common.volumes):

- ${AIRFLOW_PROJ_DIR:-.}/dags:/opt/airflow/dags
- ${AIRFLOW_PROJ_DIR:-.}/logs:/opt/airflow/logs
- ${AIRFLOW_PROJ_DIR:-.}/config:/opt/airflow/config
- ${AIRFLOW_PROJ_DIR:-.}/plugins:/opt/airflow/plugins
- ${AIRFLOW_PROJ_DIR:-.}/data:/opt/airflow/data   # để DAG thấy file CSV


.env (Linux) để hết cảnh báo AIRFLOW_UID:

AIRFLOW_UID=$(id -u)

(Đừng commit .env)

## 1) Cách chạy/khởi động lại

Lần đầu (hoặc sau khi pull):
```
docker compose up airflow-init
docker compose up -d
```

Mỗi lần bật lại VM:
```
cd airflow
docker compose up -d
```

Kiểm tra: docker compose ps

Restart một service (ví dụ scheduler):
```
docker compose restart airflow-scheduler
```
#Chỉ cần restart apiserver nếu bạn vừa đổi cấu hình ảnh hưởng UI

## 2) Kết nối & biến số trong Airflow
2.1 Postgres Connection

Tạo Connection ID pg_analytics (Airflow UI → Admin → Connections):

Conn Id: pg_analytics

Conn Type: Postgres

Host: postgres

Schema (DB): airflow

Login: airflow

Password: airflow

Port: 5432

Ghi nhớ: user/DB mặc định là airflow. Nếu dùng user/DB khác phải sửa lại ở DAG.

2.2 Airflow Variables (cho Pipeline 2 – upsert nhiều sheet)

Key: gdrive_sources (giá trị là mảng JSON)

[
  {
    "sheet_id": "1dPpkqWwyz107OfuSC2C8DUsvPaB6KBYz",
    "gid": "544507475",
    "target_table": "e00ordertype",
    "keys": ["rowid"],
    "column_map": {
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
      "SyncDate": "syncdate"
    }
  },
  {
    "sheet_id": "1HYb5SItSYDNPrfmy7v6_oUAVX3z5QbvpVY3peiQAI_s",
    "gid": "893770031",
    "target_table": "e00status",
    "keys": ["rowid"]
  }
]


Google Sheet đọc qua URL .../export?format=csv phải share “Anyone with the link – Viewer”; nếu không sẽ lỗi 401/403.

## 3) Pipeline 1 – Local file → Postgres

Mục tiêu: nạp 1 file CSV nhỏ vào Postgres (idempotent).

Đặt file vào airflow/data/ (ví dụ fact_sales_YYYYMMDD.csv).

DAG: dags/csv_to_postgres.py (hoặc tên bạn đang dùng).

Tạo bảng nếu chưa có.

Đọc CSV bằng pandas/spark (tuỳ file DAG của bạn).

Idempotent: có 2 cách

Dễ nhất: TRUNCATE + INSERT lại (full refresh).

Chuẩn hơn: UPSERT bằng INSERT ... ON CONFLICT DO UPDATE dựa trên key.

Connection sử dụng: pg_analytics.

Kiểm tra dữ liệu:
```
docker compose exec postgres psql -U airflow -d airflow -c "\dt"
docker compose exec postgres psql -U airflow -d airflow -c "SELECT COUNT(*) FROM public.fact_sales;"
```

## 4) Pipeline 2 – Google Sheet → Postgres (UPSERT)

Mục tiêu: lấy dữ liệu từ Google Sheet(s) về Postgres, không xóa bảng, cập nhật theo khóa.

DAG: dags/ggsheet-to-postgres-upsert.py

Đọc danh sách nguồn từ Variable: gdrive_sources.

Với mỗi item:

Tải CSV qua https://docs.google.com/spreadsheets/d/{sheet_id}/export?gid={gid}&format=csv

Chuẩn hoá cột (nếu có column_map).

DROP duplicate theo keys.

Tạo bảng & unique index nếu chưa có (kiểu TEXT an toàn; nếu bảng typed sẵn thì lệnh này không phá).

UPSERT: INSERT ... ON CONFLICT (keys) DO UPDATE SET ....

Lưu ý cột/kiểu:

Nếu bảng đích đã có kiểu INT/TIMESTAMP, khi upsert từ CSV (chuỗi) cần cast hoặc chuẩn hoá trước (tránh lỗi kiểu, ví dụ "rowid" integer nhưng giá trị là text).

Trường hợp nhanh gọn: tạo bảng đích TEXT trước; sau đó chuyển kiểu bằng DDL khi cần.

Hay gặp & cách xử:

401 Unauthorized: sheet chưa share public.

UndefinedColumn / column case: Postgres lowercase mặc định; map đúng tên cột.

UniqueViolation: đã có dòng khoá trùng → dùng UPSERT (không dùng append thẳng).

## 5) Pipeline 3 – MySQL → Postgres

Mục tiêu: di chuyển dữ liệu từ MySQL sang Postgres (demo đơn giản).

Hai cách bạn đã thử:

Gián tiếp qua CSV

Export MySQL → CSV (đặt vào airflow/data/),

DAG đọc CSV rồi nạp vào Postgres (full refresh hoặc upsert).

Trực tiếp qua hooks (nâng cấp sau)

Dùng MySqlHook chạy query → pandas,

PostgresHook/SQLAlchemy → to_sql/COPY → Postgres,

Với bảng to: ưu tiên COPY/copy_expert (nhanh hơn INSERT lẻ).

Kiểm tra nhanh dữ liệu đích giống phần Pipeline 1.

## 6) Một số lệnh hữu ích
#xem container
```
docker compose ps
docker compose logs -f airflow-scheduler
docker compose logs -f airflow-worker
```
#vào shell trong worker
```
docker compose exec airflow-worker bash
```
#xem DAGs được load
```
docker compose exec airflow-scheduler airflow dags list
```
#chạy/clear DAG từ CLI
```
docker compose exec airflow-scheduler airflow dags trigger CSV_to_Postgres_Pipeline
docker compose exec airflow-scheduler airflow tasks clear -s 2025-09-12 -t load_data_to_db_postgres GGSheet_to_Postgres_Pipeline
```
## 7) Troubleshooting nhanh

WARNING: AIRFLOW_UID not set → tạo file .env với AIRFLOW_UID=$(id -u) (Linux).

psycopg2.OperationalError: password authentication failed for user "de"
→ Bạn đang dùng connection pg_analytics (user airflow) nhưng code/conn trỏ user de. Chỉnh về airflow/airflow hoặc tạo đúng user.

UndefinedColumn / RowID không tồn tại
→ Tên cột/viết hoa–thường lệch; chuẩn hoá bằng rename() hoặc tạo bảng đúng schema.

UniqueViolation khi nạp
→ Đang append vào bảng có PRIMARY KEY/UNIQUE → chuyển sang UPSERT.

Không thấy DAG mới trong UI
→ File phải nằm trong airflow/dags/, tên không bắt đầu bằng _, container scheduler phải đọc được. Kiểm tra docker compose logs -f airflow-scheduler.

Đọc CSV không thấy file
→ Kiểm tra mount data:/opt/airflow/data. Tránh tên file có [ ] (Spark coi như glob), nên đổi tên “sạch”.

## 8) Quy ước commit

OK để commit: dags/, plugins/, spark/, docker-compose.yaml, README.md.

KHÔNG commit: .env, logs/, dữ liệu thật mang tính nhạy cảm.

Nếu cần dữ liệu mẫu: để các file CSV sample dung lượng nhỏ trong data/ hoặc link nguồn.


P1: CSV local → PG (full refresh hoặc upsert).

P2: GSheet → PG (upsert theo keys, khai báo trong Variable:gdrive_sources).

P3: MySQL → PG (CSV trung gian hoặc direct hooks).

Luôn kiểm Connection pg_analytics, mount ./data, và format/keys trước khi nạp.
