FROM apache/airflow:3.0.4

ARG MSSQL_JDBC_VERSION=13.4.0.jre11
ARG MSSQL_JDBC_SHA256=e36f5237c1267983e5b88dc2169f6b9d7e50eceec6dc1ca31018e3877e14af66
ARG POSTGRESQL_JDBC_VERSION=42.7.7
ARG POSTGRESQL_JDBC_SHA256=157963d60ae66d607e09466e8c0cdf8087e9cb20d0159899ffca96bca2528460

USER root
# Cài Java 17 (multi-arch, chạy được trên M1)
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends openjdk-17-jre-headless ca-certificates-java curl; \
    rm -rf /var/lib/apt/lists/*; \
    JH="$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")"; \
    echo "JAVA_HOME=${JH}" >> /etc/environment; \
    ln -s "${JH}" /usr/lib/jvm/java-17 || true; \
    install -d -m 0755 /opt/airflow/jars; \
    curl --fail --show-error --silent --location \
      "https://repo.maven.apache.org/maven2/com/microsoft/sqlserver/mssql-jdbc/${MSSQL_JDBC_VERSION}/mssql-jdbc-${MSSQL_JDBC_VERSION}.jar" \
      --output "/opt/airflow/jars/mssql-jdbc-${MSSQL_JDBC_VERSION}.jar"; \
    echo "${MSSQL_JDBC_SHA256}  /opt/airflow/jars/mssql-jdbc-${MSSQL_JDBC_VERSION}.jar" | sha256sum --check --strict; \
    curl --fail --show-error --silent --location \
      "https://repo.maven.apache.org/maven2/org/postgresql/postgresql/${POSTGRESQL_JDBC_VERSION}/postgresql-${POSTGRESQL_JDBC_VERSION}.jar" \
      --output "/opt/airflow/jars/postgresql-${POSTGRESQL_JDBC_VERSION}.jar"; \
    echo "${POSTGRESQL_JDBC_SHA256}  /opt/airflow/jars/postgresql-${POSTGRESQL_JDBC_VERSION}.jar" | sha256sum --check --strict; \
    chmod 0644 /opt/airflow/jars/*.jar
ENV JAVA_HOME=/usr/lib/jvm/java-17
ENV PHASE04_JDBC_JARS=/opt/airflow/jars/mssql-jdbc-13.4.0.jre11.jar,/opt/airflow/jars/postgresql-42.7.7.jar

USER airflow
# Keep Airflow pinned while adding the PostgreSQL, Spark, and Google Cloud
# dependencies used by the verified batch phases.
RUN python -m pip install --no-cache-dir \
      apache-airflow==3.0.4 \
      apache-airflow-providers-postgres==6.2.3 \
      apache-airflow-providers-google==17.0.0 \
      pyspark==3.5.1 \
      apache-airflow-providers-apache-spark==5.2.1 \
      psycopg2-binary==2.9.9 \
      kafka-python==2.0.2
