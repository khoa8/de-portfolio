# Airflow (local via Docker Compose)

## Yêu cầu
- Docker / Docker Compose
- Tạo file `.env` từ mẫu:
  cp .env.example .env
  # Nếu dùng Linux: AIRFLOW_UID=$(id -u)

## Chạy lần đầu
docker compose up airflow-init
docker compose up -d

Mở UI: http://localhost:8080  (user/pass: airflow/airflow)

## Thư mục
- dags/: đặt các DAG .py
- data/: dữ liệu mẫu (raw/processed/warehouse)
- plugins/: plugin Airflow (nếu có)

## Dừng
docker compose down   # giữ volumes
# hoặc xóa sạch:
# docker compose down -v
