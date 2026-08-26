"""Reusable Phase 04 Spark JDBC extract/normalize/load job.

Secrets are read only from the inherited process environment. The command line
accepts a reviewed logical source key and a non-secret Airflow run ID.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, field
from typing import Mapping


CANONICAL_COLUMNS = (
    "order_id",
    "order_date",
    "order_status",
    "buyer_name",
    "total_amount",
    "platform",
)


@dataclass(frozen=True)
class SourceSpec:
    source_table: str
    query: str
    load_table: str
    platform: str
    has_buyer: bool


SOURCE_SPECS = {
    "lazada": SourceSpec(
        source_table="ecom.E01LazadaOrders",
        query="""
            SELECT
                CAST([orderNumber] AS nvarchar(4000)) AS [raw_order_id],
                CAST([createTime] AS nvarchar(4000)) AS [raw_order_date],
                CAST([status] AS nvarchar(4000)) AS [raw_order_status],
                CAST([customerName] AS nvarchar(4000)) AS [raw_buyer_name],
                CAST([paidPrice] AS nvarchar(4000)) AS [raw_total_amount]
            FROM [ecom].[E01LazadaOrders]
        """.strip(),
        load_table="stg_edw.phase04_lazada_orders_load",
        platform="lazada",
        has_buyer=True,
    ),
    "shopee": SourceSpec(
        source_table="ecom.E01ShopeeOrders",
        query="""
            SELECT
                CAST([MaDonHang] AS nvarchar(4000)) AS [raw_order_id],
                CAST([NgayDatHang] AS nvarchar(4000)) AS [raw_order_date],
                CAST([TrangThaiDonHang] AS nvarchar(4000)) AS [raw_order_status],
                CAST([NguoiMua] AS nvarchar(4000)) AS [raw_buyer_name],
                CAST([TongSoTienNguoiMuaThanhToan] AS nvarchar(4000)) AS [raw_total_amount]
            FROM [ecom].[E01ShopeeOrders]
        """.strip(),
        load_table="stg_edw.phase04_shopee_orders_load",
        platform="shopee",
        has_buyer=True,
    ),
    "tiki": SourceSpec(
        source_table="ecom.E01TikiOrders",
        query="""
            SELECT
                CAST([MaDonHang] AS nvarchar(4000)) AS [raw_order_id],
                CAST([NgayDat] AS nvarchar(4000)) AS [raw_order_date],
                CAST([TrangThai] AS nvarchar(4000)) AS [raw_order_status],
                CAST(NULL AS nvarchar(4000)) AS [raw_buyer_name],
                CAST([ThanhTien] AS nvarchar(4000)) AS [raw_total_amount]
            FROM [ecom].[E01TikiOrders]
        """.strip(),
        load_table="stg_edw.phase04_tiki_orders_load",
        platform="tiki",
        has_buyer=False,
    ),
}


@dataclass(frozen=True)
class RuntimeConfig:
    mssql_host: str
    mssql_port: int
    mssql_database: str
    mssql_encrypt: bool
    mssql_trust_server_certificate: bool
    mssql_user: str = field(repr=False)
    mssql_password: str = field(repr=False)
    postgres_user: str = field(repr=False)
    postgres_password: str = field(repr=False)


def get_source_spec(source_key: str) -> SourceSpec:
    try:
        return SOURCE_SPECS[source_key]
    except KeyError as exc:
        raise ValueError(f"Unsupported source key: {source_key!r}") from exc


def _required_value(environ: Mapping[str, str], key: str) -> str:
    value = environ.get(key)
    if value is None or value == "":
        raise ValueError(f"Missing required environment key: {key}")
    return value


def _strict_bool(environ: Mapping[str, str], key: str, default: str) -> bool:
    value = environ.get(key, default).lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{key} must be true or false")
    return value == "true"


def load_runtime_config(environ: Mapping[str, str]) -> RuntimeConfig:
    host = _required_value(environ, "MSSQL_HOST").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", host):
        raise ValueError("MSSQL_HOST contains unsupported characters")

    try:
        port = int(environ.get("MSSQL_PORT", "1433"))
    except ValueError as exc:
        raise ValueError("MSSQL_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("MSSQL_PORT must be between 1 and 65535")

    database = environ.get("MSSQL_DATABASE", "EDW_Tech")
    if database != "EDW_Tech":
        raise ValueError("MSSQL_DATABASE must be EDW_Tech for Phase 04")

    return RuntimeConfig(
        mssql_host=host,
        mssql_port=port,
        mssql_database=database,
        mssql_encrypt=_strict_bool(environ, "MSSQL_ENCRYPT", "true"),
        mssql_trust_server_certificate=_strict_bool(
            environ, "MSSQL_TRUST_SERVER_CERTIFICATE", "false"
        ),
        mssql_user=_required_value(environ, "MSSQL_USER"),
        mssql_password=_required_value(environ, "MSSQL_PASSWORD"),
        postgres_user=_required_value(environ, "POSTGRES_USER"),
        postgres_password=_required_value(environ, "POSTGRES_PASSWORD"),
    )


def build_mssql_jdbc_url(config: RuntimeConfig) -> str:
    encrypt = str(config.mssql_encrypt).lower()
    trust = str(config.mssql_trust_server_certificate).lower()
    return (
        f"jdbc:sqlserver://{config.mssql_host}:{config.mssql_port};"
        f"databaseName={config.mssql_database};"
        f"encrypt={encrypt};trustServerCertificate={trust};"
        "applicationName=de-portfolio-phase04"
    )


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-key", required=True, choices=tuple(SOURCE_SPECS))
    parser.add_argument("--run-id", required=True)
    return parser


def _clean_text(column):
    from pyspark.sql import functions as functions

    text = functions.trim(column.cast("string"))
    return functions.when(
        column.isNull() | functions.lower(text).isin("", "null"), None
    ).otherwise(text)


def transform_source(dataframe, source_key: str):
    from pyspark.sql import functions as functions
    from pyspark.sql.types import DecimalType, StringType

    spec = get_source_spec(source_key)
    raw_order_id = _clean_text(functions.col("raw_order_id"))
    raw_order_date = _clean_text(functions.col("raw_order_date"))
    raw_order_status = _clean_text(functions.col("raw_order_status"))
    raw_buyer_name = _clean_text(functions.col("raw_buyer_name"))
    raw_total_amount = _clean_text(functions.col("raw_total_amount"))

    order_date = functions.coalesce(
        functions.to_timestamp(raw_order_date, "yyyy-MM-dd HH:mm:ss.SSS"),
        functions.to_timestamp(raw_order_date, "yyyy-MM-dd HH:mm:ss"),
        functions.to_timestamp(raw_order_date, "yyyy-MM-dd HH:mm"),
        functions.to_timestamp(raw_order_date, "yyyy-MM-dd"),
        functions.to_timestamp(raw_order_date, "yyyy-MM-dd'T'HH:mm:ss.SSS"),
        functions.to_timestamp(raw_order_date, "dd/MM/yyyy HH:mm:ss"),
        functions.to_timestamp(raw_order_date, "dd/MM/yyyy"),
        functions.to_timestamp(raw_order_date, "d/M/yyyy"),
        functions.to_timestamp(raw_order_date, "dd MMM yyyy HH:mm"),
        functions.to_timestamp(raw_order_date, "M/d/yyyy H:mm:ss"),
    )
    total_amount = raw_total_amount.cast(DecimalType(18, 2))
    buyer_name = (
        raw_buyer_name.cast(StringType())
        if spec.has_buyer
        else functions.lit(None).cast(StringType())
    )

    return dataframe.select(
        raw_order_id.cast(StringType()).alias("order_id"),
        order_date.alias("order_date"),
        raw_order_status.cast(StringType()).alias("order_status"),
        buyer_name.alias("buyer_name"),
        total_amount.alias("total_amount"),
        functions.lit(spec.platform).cast(StringType()).alias("platform"),
        functions.when(
            raw_order_date.isNotNull() & order_date.isNull(), 1
        ).otherwise(0).alias("order_date_conversion_failed"),
        functions.when(
            raw_total_amount.isNotNull() & total_amount.isNull(), 1
        ).otherwise(0).alias("total_amount_conversion_failed"),
    )


def calculate_metrics(transformed) -> dict[str, int]:
    from pyspark.sql import functions as functions

    row = transformed.agg(
        functions.count(functions.lit(1)).alias("source_count"),
        functions.sum("order_date_conversion_failed").alias(
            "order_date_conversion_failures"
        ),
        functions.sum("total_amount_conversion_failed").alias(
            "total_amount_conversion_failures"
        ),
    ).first()
    return {
        "source_count": int(row["source_count"] or 0),
        "order_date_conversion_failures": int(
            row["order_date_conversion_failures"] or 0
        ),
        "total_amount_conversion_failures": int(
            row["total_amount_conversion_failures"] or 0
        ),
    }


def _postgres_connection(config: RuntimeConfig):
    import psycopg2

    return psycopg2.connect(
        host="postgres",
        port=5432,
        dbname="ecom_dw",
        user=config.postgres_user,
        password=config.postgres_password,
        connect_timeout=10,
    )


def reset_source_load_state(config: RuntimeConfig, source_key: str) -> None:
    from psycopg2 import sql

    spec = get_source_spec(source_key)
    schema_name, table_name = spec.load_table.split(".", maxsplit=1)
    connection = _postgres_connection(config)
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("TRUNCATE TABLE {}.{}").format(
                        sql.Identifier(schema_name), sql.Identifier(table_name)
                    )
                )
                cursor.execute(
                    "DELETE FROM stg_edw.phase04_load_metrics WHERE source_key = %s",
                    (source_key,),
                )
    finally:
        connection.close()


def write_load(dataframe, config: RuntimeConfig, source_key: str) -> None:
    spec = get_source_spec(source_key)
    (
        dataframe.select(*CANONICAL_COLUMNS)
        .write.mode("append")
        .format("jdbc")
        .option("url", "jdbc:postgresql://postgres:5432/ecom_dw")
        .option("driver", "org.postgresql.Driver")
        .option("dbtable", spec.load_table)
        .option("user", config.postgres_user)
        .option("password", config.postgres_password)
        .option("batchsize", "10000")
        .option("numPartitions", "1")
        .save()
    )


def record_metrics(
    config: RuntimeConfig,
    source_key: str,
    run_id: str,
    metrics: Mapping[str, int],
) -> int:
    from psycopg2 import sql

    spec = get_source_spec(source_key)
    schema_name, table_name = spec.load_table.split(".", maxsplit=1)
    connection = _postgres_connection(config)
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("SELECT count(*) FROM {}.{}").format(
                        sql.Identifier(schema_name), sql.Identifier(table_name)
                    )
                )
                load_count = int(cursor.fetchone()[0])
                if load_count != metrics["source_count"]:
                    raise RuntimeError(
                        "Source/load reconciliation failed for " + source_key
                    )
                cursor.execute(
                    """
                    INSERT INTO stg_edw.phase04_load_metrics (
                        source_key,
                        dag_run_id,
                        source_count,
                        load_count,
                        order_date_conversion_failures,
                        total_amount_conversion_failures
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source_key) DO UPDATE SET
                        dag_run_id = EXCLUDED.dag_run_id,
                        source_count = EXCLUDED.source_count,
                        load_count = EXCLUDED.load_count,
                        order_date_conversion_failures =
                            EXCLUDED.order_date_conversion_failures,
                        total_amount_conversion_failures =
                            EXCLUDED.total_amount_conversion_failures
                    """,
                    (
                        source_key,
                        run_id,
                        metrics["source_count"],
                        load_count,
                        metrics["order_date_conversion_failures"],
                        metrics["total_amount_conversion_failures"],
                    ),
                )
    finally:
        connection.close()
    return load_count


def read_source(spark, config: RuntimeConfig, source_key: str):
    spec = get_source_spec(source_key)
    return (
        spark.read.format("jdbc")
        .option("url", build_mssql_jdbc_url(config))
        .option("driver", "com.microsoft.sqlserver.jdbc.SQLServerDriver")
        .option("query", spec.query)
        .option("user", config.mssql_user)
        .option("password", config.mssql_password)
        .option("fetchsize", "1000")
        .load()
    )


def main() -> None:
    from pyspark.sql import SparkSession

    args = build_argument_parser().parse_args()
    if not args.run_id or len(args.run_id) > 250 or any(
        character in args.run_id for character in "\r\n\0"
    ):
        raise ValueError("--run-id must be nonempty, bounded, and single-line")

    config = load_runtime_config(os.environ)
    source_key = args.source_key
    reset_source_load_state(config, source_key)

    spark = (
        SparkSession.builder.appName(f"phase04_{source_key}_to_postgres_load")
        .config("spark.sql.ansi.enabled", "false")
        .config("spark.sql.legacy.timeParserPolicy", "CORRECTED")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    try:
        source = read_source(spark, config, source_key)
        transformed = transform_source(source, source_key).cache()
        metrics = calculate_metrics(transformed)
        write_load(transformed, config, source_key)
        load_count = record_metrics(config, source_key, args.run_id, metrics)
        print(
            json.dumps(
                {
                    "event": "phase04_load_complete",
                    "source_key": source_key,
                    "source_table": get_source_spec(source_key).source_table,
                    "target_table": get_source_spec(source_key).load_table,
                    "source_count": metrics["source_count"],
                    "load_count": load_count,
                    "order_date_conversion_failures": metrics[
                        "order_date_conversion_failures"
                    ],
                    "total_amount_conversion_failures": metrics[
                        "total_amount_conversion_failures"
                    ],
                },
                sort_keys=True,
            )
        )
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
