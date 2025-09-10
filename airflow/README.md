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
