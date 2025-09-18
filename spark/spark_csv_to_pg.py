# /opt/airflow/spark/spark_csv_to_pg.py

from pyspark.sql import SparkSession, functions as F

# ====== CONFIG (đổi cho phù hợp nếu cần) ======
SRC_CSV       = "/opt/airflow/data/E01OrderHeader.csv"   # CSV bạn đã đổi tên
POSTGRES_URL  = "jdbc:postgresql://postgres:5432/airflow"
POSTGRES_USER = "airflow"
POSTGRES_PASS = "airflow"
TARGET_TABLE  = "public.E01_orders_from_csv"           # bảng đích trong Postgres
# =============================================


def build_spark() -> SparkSession:
    """
    Tạo SparkSession ở local mode.
    Yêu cầu: trong container đã cài Java (OpenJDK 17) & PySpark, và có JAVA_HOME.
    """
    spark = (
        SparkSession.builder
        .appName("csv_to_pg")
        # Tải JDBC driver Postgres
        .config("spark.jars.packages", "org.postgresql:postgresql:42.7.3")
        # Bật 'khoan dung': cast sai trả về NULL thay vì ném lỗi
        .config("spark.sql.ansi.enabled", "false")
        .getOrCreate()
    )
    return spark


def read_csv(spark: SparkSession):
    """
    Đọc CSV có header. Không đoán schema để giữ nguyên chuỗi, lát nữa tự chuyển kiểu.
    """
    df = spark.read.option("header", True).csv(SRC_CSV)
    return df


def transform(df):
    """
    - Chọn các cột chính từ file thực tế:
        OrderCode -> order_id
        SiteID    -> store_id
        DocDate   -> order_dt (timestamp)
    - Dọn DocDate ("NULL"/trống -> NULL), parse nhiều format phổ biến.
    - Tính KPI: số đơn theo ngày.
    """
    # chuẩn hóa cột ngày: "NULL"/"" -> NULL
    clean_dt = F.when(
        F.col("DocDate").isNull() |
        (F.trim(F.lower(F.col("DocDate"))).isin("null", "")),
        None
    ).otherwise(F.col("DocDate"))

    # parse theo nhiều format; coalesce sẽ lấy format parse được đầu tiên
    order_dt = F.coalesce(
        F.to_timestamp(clean_dt, "yyyy-MM-dd HH:mm:ss.SSS"),
        F.to_timestamp(clean_dt, "yyyy-MM-dd HH:mm:ss"),
        F.to_timestamp(clean_dt, "yyyy-MM-dd")
    )

    df2 = (
        df
        .withColumn("order_id", F.col("OrderCode"))
        .withColumn("store_id", F.col("SiteID"))
        .withColumn("order_dt", order_dt)
    )

    # KPI: số đơn theo ngày (bỏ bản ghi không parse được ngày)
    result = (
        df2.filter(F.col("order_dt").isNotNull())
           .groupBy(F.to_date("order_dt").alias("order_date"))
           .agg(F.countDistinct("order_id").alias("orders"))
           .orderBy("order_date")
    )

    # Nếu muốn thêm doanh thu/ngày thì mở comment đoạn dưới:
    # to_num = lambda c: F.when(
    #     F.col(c).isNull() | (F.trim(F.lower(F.col(c))).isin("null","")), None
    # ).otherwise(F.col(c).cast("double"))
    # df2 = df2.withColumn("total_value_num", to_num("TotalValue"))
    # revenue_by_day = (df2.filter(F.col("order_dt").isNotNull())
    #                        .groupBy(F.to_date("order_dt").alias("order_date"))
    #                        .agg(F.sum("total_value_num").alias("revenue")))
    # result = (result.join(revenue_by_day, on="order_date", how="left")
    #                 .orderBy("order_date"))

    return result


def write_to_postgres(df):
    """
    Ghi DataFrame về Postgres qua JDBC.
    - mode="overwrite": ghi đè toàn bảng đích mỗi lần chạy (dễ demo).
      Nếu muốn upsert nâng cao, cần viết thêm logic jdbc/merge riêng.
    """
    (df.write
       .format("jdbc")
       .option("url", POSTGRES_URL)
       .option("dbtable", TARGET_TABLE)
       .option("user", POSTGRES_USER)
       .option("password", POSTGRES_PASS)
       .option("driver", "org.postgresql.Driver")
       .mode("overwrite")
       .save())


def main():
    spark = build_spark()
    try:
        df_raw = read_csv(spark)

        # debug nhanh: mở 2 dòng dưới nếu muốn soi schema & vài dòng đầu
        # df_raw.printSchema()
        # df_raw.show(5, truncate=False)

        result = transform(df_raw)
        write_to_postgres(result)

        cnt = result.count()
        print(f"DONE -> wrote {cnt} row(s) to {TARGET_TABLE}")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()

