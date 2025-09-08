1. Install UTM - virtural machine
2. Download Ubuntu image *.iso
3. Setup the Ubuntu VM
   CPU: 6–8 vCPU
   RAM: 8–16 GB
   Disk: 40 GB+
4. ```
   sudo apt update
   sudo apt install -y spice-vdagent qemu-guest-agent
   ```
    spice-vdagent: bật copy/paste giữa macOS ↔ Ubuntu; cần thiết cả với Apple backend.
    qemu-guest-agent: thêm tính năng đồng bộ thời gian & trao đổi thông tin VM–host. 
5. Setup Docker
   https://docs.docker.com/engine/install/ubuntu/#install-using-the-repository
B1: Update & cài gói phụ trợ
```
sudo apt-get update
sudo apt-get install -y ca-certificates curl
```
B2: Tạo thư mục keyrings
```
sudo install -m 0755 -d /etc/apt/keyrings
```
B3: Tải GPG key về và set quyền
```
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```
B4: Thêm repo Docker
```
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```
B5: Update lại index
```
sudo apt-get update
```
B6: Cài gói
```
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo docker run hello-world
```
B7: chạy Docker ko cần sudo, hoàn tất
Cho phép user hiện tại chạy docker không cần sudo:
```
sudo usermod -aG docker $USER   # thêm user vào group 'docker'
newgrp docker                    # nạp lại group trong shell hiện tại (khỏi logout/login)
docker --version                 # in phiên bản docker-cli
docker compose version           # in phiên bản compose plugin
docker run --rm hello-world      # chạy container test rồi tự xóa (--rm)
```
6. Cài Apache Airflow bằng Docker Compose (quick-start)
   https://airflow.apache.org/docs/apache-airflow/stable/howto/docker-compose/index.html
   ```
   mkdir -p ~/airflow && cd ~/airflow               # tạo và vào thư mục dự án Airflow
   echo -e "AIRFLOW_UID=$(id -u)" > .env
   curl -LfO 'https://airflow.apache.org/docs/apache-airflow/3.0.4/docker-compose.yaml'
   ```
   #Khởi tạo database/volumes Airflow:
   ```
   docker compose up airflow-init
   ```
   #chạy 'airflow db init' & tạo user mặc định trong container theo cấu hình

   
