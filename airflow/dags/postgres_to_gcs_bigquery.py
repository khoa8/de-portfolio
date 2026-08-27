"""Phase 06: export the local warehouse to run-specific GCS objects and BigQuery."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pendulum

from airflow.sdk import dag, get_current_context, task


LOGGER = logging.getLogger(__name__)

DAG_ID = "postgres_to_gcs_bigquery"
POSTGRES_CONNECTION_ID = "pg_dw"
GOOGLE_CONNECTION_ID = "google_cloud_default"
DEFAULT_PROJECT_ID = "kinetic-genre-473714-d1"
DEFAULT_BUCKET = "edw_bucket_k"
DEFAULT_LOCATION = "asia-southeast1"
RUN_PREFIX_ROOT = "phase06/runs"


@dataclass(frozen=True)
class ExportSpec:
    key: str
    dataset: str
    table: str
    sql: str
    schema: tuple[tuple[str, str, str], ...]
    partition_field: str | None = None
    cluster_fields: tuple[str, ...] = ()
    total_field: str | None = None
    order_count_field: str | None = None
    platform_field: str = "platform_code"

    @property
    def object_basename(self) -> str:
        return f"{self.dataset}/{self.table}.ndjson"

    @property
    def bigquery_schema(self) -> list[dict[str, str]]:
        return [
            {"name": name, "type": field_type, "mode": mode}
            for name, field_type, mode in self.schema
        ]


TABLE_SPECS = {
    "dim_platform": ExportSpec(
        key="dim_platform",
        dataset="dw",
        table="dim_platform",
        sql="""
            SELECT
                platform_key::BIGINT AS platform_key,
                platform_code,
                platform_name
            FROM dw.dim_platform
            ORDER BY platform_key
        """,
        schema=(
            ("platform_key", "INTEGER", "REQUIRED"),
            ("platform_code", "STRING", "REQUIRED"),
            ("platform_name", "STRING", "REQUIRED"),
        ),
    ),
    "fact_orders": ExportSpec(
        key="fact_orders",
        dataset="dw",
        table="fact_orders",
        sql="""
            SELECT
                fact.platform_key::BIGINT AS platform_key,
                platform.platform_code,
                platform.platform_name,
                fact.order_nk,
                fact.customer_key,
                customer.customer_natural,
                fact.order_status,
                fact.amount,
                date_dim.full_date AS order_date,
                fact.load_dts
            FROM dw.fact_orders AS fact
            JOIN dw.dim_platform AS platform
              ON platform.platform_key = fact.platform_key
            JOIN dw.dim_customer AS customer
              ON customer.customer_key = fact.customer_key
            JOIN dw.dim_date AS date_dim
              ON date_dim.date_key = fact.date_key
            ORDER BY platform.platform_code, fact.order_nk
        """,
        schema=(
            ("platform_key", "INTEGER", "REQUIRED"),
            ("platform_code", "STRING", "REQUIRED"),
            ("platform_name", "STRING", "REQUIRED"),
            ("order_nk", "STRING", "REQUIRED"),
            ("customer_key", "INTEGER", "REQUIRED"),
            ("customer_natural", "STRING", "REQUIRED"),
            ("order_status", "STRING", "NULLABLE"),
            ("amount", "NUMERIC", "REQUIRED"),
            ("order_date", "DATE", "REQUIRED"),
            ("load_dts", "TIMESTAMP", "REQUIRED"),
        ),
        partition_field="order_date",
        cluster_fields=("platform_key",),
        total_field="amount",
    ),
    "daily_sales": ExportSpec(
        key="daily_sales",
        dataset="dm",
        table="daily_sales",
        sql="""
            SELECT
                order_date,
                platform_code,
                platform_name,
                total_sales,
                order_count
            FROM dm.mv_daily_sales
            ORDER BY order_date, platform_code
        """,
        schema=(
            ("order_date", "DATE", "REQUIRED"),
            ("platform_code", "STRING", "REQUIRED"),
            ("platform_name", "STRING", "REQUIRED"),
            ("total_sales", "NUMERIC", "REQUIRED"),
            ("order_count", "INTEGER", "REQUIRED"),
        ),
        partition_field="order_date",
        cluster_fields=("platform_name",),
        total_field="total_sales",
        order_count_field="order_count",
    ),
}


def _runtime_config() -> dict[str, str]:
    return {
        "project_id": os.getenv("GCP_PROJECT_ID", DEFAULT_PROJECT_ID),
        "bucket": os.getenv("GCS_BUCKET", DEFAULT_BUCKET),
        "location": os.getenv("BQ_LOCATION", DEFAULT_LOCATION),
    }


def _safe_run_id(run_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", run_id).strip("._-")
    if not safe:
        raise ValueError("Airflow run_id did not contain a safe object-name component")
    return safe[:180]


def _object_name(run_id: str, spec: ExportSpec) -> str:
    return f"{RUN_PREFIX_ROOT}/{_safe_run_id(run_id)}/{spec.object_basename}"


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Unsupported NDJSON value type: {type(value).__name__}")


def _empty_metrics() -> dict[str, Any]:
    return {"row_count": 0, "order_count": 0, "total": Decimal("0"), "platforms": {}}


def _update_metrics(metrics: dict[str, Any], row: dict[str, Any], spec: ExportSpec) -> None:
    metrics["row_count"] += 1
    orders = int(row.get(spec.order_count_field) or 1) if spec.order_count_field else 1
    metrics["order_count"] += orders
    if spec.total_field:
        metrics["total"] += Decimal(str(row.get(spec.total_field) or 0))

    platform = row.get(spec.platform_field)
    if platform is not None:
        platform_metrics = metrics["platforms"].setdefault(
            str(platform), {"row_count": 0, "order_count": 0, "total": Decimal("0")}
        )
        platform_metrics["row_count"] += 1
        platform_metrics["order_count"] += orders
        if spec.total_field:
            platform_metrics["total"] += Decimal(str(row.get(spec.total_field) or 0))


def _serializable_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "row_count": metrics["row_count"],
        "order_count": metrics["order_count"],
        "total": format(metrics["total"], "f"),
        "platforms": {
            platform: {
                "row_count": values["row_count"],
                "order_count": values["order_count"],
                "total": format(values["total"], "f"),
            }
            for platform, values in sorted(metrics["platforms"].items())
        },
    }


def _validate_ndjson(path: Path, spec: ExportSpec, expected: dict[str, Any]) -> dict[str, Any]:
    expected_fields = {name for name, _, _ in spec.schema}
    required_fields = {name for name, _, mode in spec.schema if mode == "REQUIRED"}
    metrics = _empty_metrics()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            row = json.loads(line)
            if set(row) != expected_fields:
                raise RuntimeError(
                    f"{spec.key} NDJSON schema mismatch at line {line_number}"
                )
            missing = sorted(name for name in required_fields if row[name] is None)
            if missing:
                raise RuntimeError(
                    f"{spec.key} has null required fields at line {line_number}: {missing}"
                )
            _update_metrics(metrics, row, spec)

    actual = _serializable_metrics(metrics)
    if actual != expected:
        raise RuntimeError(
            f"{spec.key} NDJSON metrics differ from PostgreSQL export: "
            f"expected={expected}, actual={actual}"
        )
    return actual


def _export_one(spec: ExportSpec, run_id: str, bucket_name: str) -> dict[str, Any]:
    from airflow.providers.google.cloud.hooks.gcs import GCSHook
    from airflow.providers.postgres.hooks.postgres import PostgresHook

    object_name = _object_name(run_id, spec)
    if "*" in object_name or "?" in object_name:
        raise RuntimeError("Phase 06 object names must be exact and wildcard-free")

    postgres = PostgresHook(postgres_conn_id=POSTGRES_CONNECTION_ID)
    connection = postgres.get_conn()
    temporary_path: Path | None = None
    metrics = _empty_metrics()
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".ndjson", delete=False
        ) as output:
            temporary_path = Path(output.name)
            with connection.cursor(name=f"phase06_{spec.key}") as cursor:
                cursor.itersize = 10_000
                cursor.execute(spec.sql)
                # Named psycopg2 cursors do not populate ``description`` until
                # the first fetch. The explicit export schema is the canonical
                # column order, and strict zip still rejects a SQL/schema drift.
                columns = [name for name, _, _ in spec.schema]
                for values in cursor:
                    row = dict(zip(columns, values, strict=True))
                    output.write(json.dumps(row, default=_json_default, separators=(",", ":")))
                    output.write("\n")
                    _update_metrics(metrics, row, spec)

        gcs = GCSHook(gcp_conn_id=GOOGLE_CONNECTION_ID)
        gcs.upload(
            bucket_name=bucket_name,
            object_name=object_name,
            filename=str(temporary_path),
            mime_type="application/x-ndjson",
        )
        blob = gcs.get_conn().bucket(bucket_name).get_blob(object_name)
        if blob is None:
            raise RuntimeError(f"GCS upload is not readable: {object_name}")
        return {
            "object": object_name,
            "generation": str(blob.generation),
            "size": int(blob.size),
            "metrics": _serializable_metrics(metrics),
        }
    finally:
        connection.close()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _load_canonical(manifest: dict[str, Any], spec_key: str) -> dict[str, Any]:
    from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook
    from google.cloud import bigquery

    spec = TABLE_SPECS[spec_key]
    config = manifest["config"]
    entry = manifest["exports"][spec_key]
    source_uri = f"gs://{config['bucket']}/{entry['object']}"
    if "*" in source_uri or "?" in source_uri:
        raise RuntimeError("BigQuery loads must use one exact run object")

    hook = BigQueryHook(
        gcp_conn_id=GOOGLE_CONNECTION_ID,
        location=config["location"],
        use_legacy_sql=False,
    )
    client = hook.get_client(project_id=config["project_id"], location=config["location"])
    job_config = bigquery.LoadJobConfig(
        schema=[
            bigquery.SchemaField(field["name"], field["type"], mode=field["mode"])
            for field in spec.bigquery_schema
        ],
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
        autodetect=False,
        ignore_unknown_values=False,
        max_bad_records=0,
    )
    if spec.partition_field:
        job_config.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field=spec.partition_field,
        )
    if spec.cluster_fields:
        job_config.clustering_fields = list(spec.cluster_fields)

    destination = f"{config['project_id']}.{spec.dataset}.{spec.table}"
    job_id = f"phase06_{_safe_run_id(manifest['run_id'])}_{spec.key}"[:1024]
    job = client.load_table_from_uri(
        source_uri,
        destination,
        job_config=job_config,
        job_id=job_id,
        location=config["location"],
    )
    job.result()
    LOGGER.info(
        "Loaded exact Phase 06 object into %s with WRITE_TRUNCATE; rows=%s",
        destination,
        job.output_rows,
    )
    return {"table": destination, "job_id": job.job_id, "output_rows": job.output_rows}


@dag(
    dag_id=DAG_ID,
    description="Validated PostgreSQL DW/DM export through run-specific GCS objects to BigQuery",
    schedule=None,
    start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=1)},
    tags=["phase06", "postgres", "gcs", "bigquery"],
)
def postgres_to_gcs_bigquery():
    @task
    def cloud_preflight() -> dict[str, str]:
        from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook
        from airflow.providers.google.cloud.hooks.gcs import GCSHook

        config = _runtime_config()
        gcs = GCSHook(gcp_conn_id=GOOGLE_CONNECTION_ID)
        bucket = gcs.get_conn().get_bucket(config["bucket"])
        if bucket.location.lower() != config["location"].lower():
            raise RuntimeError("GCS bucket location does not match BQ location")

        bq = BigQueryHook(
            gcp_conn_id=GOOGLE_CONNECTION_ID,
            location=config["location"],
            use_legacy_sql=False,
        ).get_client(project_id=config["project_id"], location=config["location"])
        for dataset_name in ("dw", "dm"):
            dataset = bq.get_dataset(f"{config['project_id']}.{dataset_name}")
            if dataset.location.lower() != config["location"].lower():
                raise RuntimeError(f"BigQuery dataset location mismatch: {dataset_name}")
        return config

    @task
    def export_run(config: dict[str, str]) -> dict[str, Any]:
        run_id = str(get_current_context()["run_id"])
        exports = {
            key: _export_one(spec, run_id, config["bucket"])
            for key, spec in TABLE_SPECS.items()
        }
        prefixes = {entry["object"].rsplit("/", 2)[0] for entry in exports.values()}
        if len(prefixes) != 1:
            raise RuntimeError("All Phase 06 objects must share one run-unique prefix")
        return {"run_id": run_id, "config": config, "exports": exports}

    @task
    def validate_run_objects(manifest: dict[str, Any]) -> dict[str, Any]:
        from airflow.providers.google.cloud.hooks.gcs import GCSHook

        gcs = GCSHook(gcp_conn_id=GOOGLE_CONNECTION_ID)
        for key, spec in TABLE_SPECS.items():
            entry = manifest["exports"][key]
            object_name = entry["object"]
            blob = gcs.get_conn().bucket(manifest["config"]["bucket"]).get_blob(object_name)
            if blob is None or str(blob.generation) != entry["generation"]:
                raise RuntimeError(f"GCS object generation changed before load: {object_name}")
            with tempfile.NamedTemporaryFile(suffix=".ndjson") as download:
                gcs.download(
                    bucket_name=manifest["config"]["bucket"],
                    object_name=object_name,
                    filename=download.name,
                )
                _validate_ndjson(Path(download.name), spec, entry["metrics"])
        LOGGER.info("Validated all exact run-specific GCS objects before BigQuery loads")
        return manifest

    @task
    def load_dim_platform(manifest: dict[str, Any]) -> dict[str, Any]:
        return _load_canonical(manifest, "dim_platform")

    @task
    def load_fact_orders(manifest: dict[str, Any]) -> dict[str, Any]:
        return _load_canonical(manifest, "fact_orders")

    @task
    def load_daily_sales(manifest: dict[str, Any]) -> dict[str, Any]:
        return _load_canonical(manifest, "daily_sales")

    @task
    def verify_destinations(
        manifest: dict[str, Any],
        load_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook
        from airflow.providers.postgres.hooks.postgres import PostgresHook

        if len(load_results) != 3:
            raise RuntimeError("All three canonical load jobs must complete before verification")
        config = manifest["config"]
        bq = BigQueryHook(
            gcp_conn_id=GOOGLE_CONNECTION_ID,
            location=config["location"],
            use_legacy_sql=False,
        ).get_client(project_id=config["project_id"], location=config["location"])

        for key, spec in TABLE_SPECS.items():
            table = bq.get_table(f"{config['project_id']}.{spec.dataset}.{spec.table}")
            actual_schema = [(field.name, field.field_type, field.mode) for field in table.schema]
            if actual_schema != list(spec.schema):
                raise RuntimeError(f"BigQuery schema mismatch after load: {key}")
            actual_partition = table.time_partitioning.field if table.time_partitioning else None
            if actual_partition != spec.partition_field:
                raise RuntimeError(f"BigQuery partition mismatch after load: {key}")
            if tuple(table.clustering_fields or ()) != spec.cluster_fields:
                raise RuntimeError(f"BigQuery clustering mismatch after load: {key}")

        postgres = PostgresHook(postgres_conn_id=POSTGRES_CONNECTION_ID)
        connection = postgres.get_conn()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT platform.platform_code, COUNT(*), SUM(fact.amount)
                    FROM dw.fact_orders AS fact
                    JOIN dw.dim_platform AS platform USING (platform_key)
                    GROUP BY platform.platform_code
                    ORDER BY platform.platform_code
                    """
                )
                pg_platforms = {
                    code: {"orders": count, "total": total}
                    for code, count, total in cursor.fetchall()
                }
                cursor.execute(
                    "SELECT COUNT(*), SUM(order_count), SUM(total_sales) FROM dm.mv_daily_sales"
                )
                pg_daily = cursor.fetchone()
        finally:
            connection.close()

        fact_rows = list(
            bq.query(
                f"""
                SELECT platform_code, COUNT(*) AS orders, SUM(amount) AS total
                FROM `{config['project_id']}.dw.fact_orders`
                GROUP BY platform_code
                ORDER BY platform_code
                """,
                location=config["location"],
            ).result()
        )
        bq_platforms = {
            row.platform_code: {"orders": row.orders, "total": row.total}
            for row in fact_rows
        }
        if bq_platforms != pg_platforms:
            raise RuntimeError(
                f"BigQuery fact per-platform reconciliation failed: "
                f"postgres={pg_platforms}, bigquery={bq_platforms}"
            )

        daily_row = next(
            iter(
                bq.query(
                    f"""
                    SELECT COUNT(*) AS group_count, SUM(order_count) AS orders,
                           SUM(total_sales) AS total
                    FROM `{config['project_id']}.dm.daily_sales`
                    """,
                    location=config["location"],
                ).result()
            )
        )
        bq_daily = (daily_row.group_count, daily_row.orders, daily_row.total)
        expected_daily = (pg_daily[0], pg_daily[1], pg_daily[2])
        if bq_daily != expected_daily:
            raise RuntimeError(
                f"BigQuery daily-sales reconciliation failed: "
                f"postgres={expected_daily}, bigquery={bq_daily}"
            )

        return {
            "run_id": manifest["run_id"],
            "objects": {
                key: value["object"] for key, value in manifest["exports"].items()
            },
            "fact_platforms": {
                platform: {
                    "orders": values["orders"],
                    "total": format(values["total"], "f"),
                }
                for platform, values in bq_platforms.items()
            },
            "daily": {
                "groups": bq_daily[0],
                "orders": bq_daily[1],
                "total": format(bq_daily[2], "f"),
            },
        }

    config = cloud_preflight()
    exported = export_run(config)
    validated = validate_run_objects(exported)
    loaded = [
        load_dim_platform(validated),
        load_fact_orders(validated),
        load_daily_sales(validated),
    ]
    verify_destinations(validated, loaded)


postgres_to_gcs_bigquery()
