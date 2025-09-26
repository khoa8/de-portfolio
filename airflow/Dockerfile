# airflow/Dockerfile
FROM apache/airflow:3.0.4

USER root
# Cài Java 17 (multi-arch, chạy được trên M1)
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends openjdk-17-jre-headless ca-certificates-java; \
    rm -rf /var/lib/apt/lists/*; \
    JH="$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")"; \
    echo "JAVA_HOME=${JH}" >> /etc/environment; \
    ln -s "${JH}" /usr/lib/jvm/java-17 || true
ENV JAVA_HOME=/usr/lib/jvm/java-17

USER airflow
# PySpark + Spark provider + psycopg2 (UPsert) + (tùy chọn) kafka-python (producer)
RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir \
      pyspark==3.5.1 \
      apache-airflow-providers-apache-spark==5.2.1 \
      psycopg2-binary==2.9.9 \
      kafka-python==2.0.2

