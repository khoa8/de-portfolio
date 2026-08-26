from __future__ import annotations

import unittest

from spark import spark_mssql_to_postgres as job


class Phase04ConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = {
            "MSSQL_HOST": "sql_server.internal",
            "MSSQL_PORT": "1433",
            "MSSQL_DATABASE": "EDW_Tech",
            "MSSQL_USER": "test-user",
            "MSSQL_PASSWORD": "test-password",
            "MSSQL_ENCRYPT": "true",
            "MSSQL_TRUST_SERVER_CERTIFICATE": "false",
            "POSTGRES_USER": "test-pg-user",
            "POSTGRES_PASSWORD": "test-pg-password",
        }

    def test_source_allowlist_and_mappings(self) -> None:
        self.assertEqual(tuple(job.SOURCE_SPECS), ("lazada", "shopee", "tiki"))
        self.assertEqual(
            job.SOURCE_SPECS["lazada"].source_table,
            "ecom.E01LazadaOrders",
        )
        self.assertEqual(
            job.SOURCE_SPECS["shopee"].source_table,
            "ecom.E01ShopeeOrders",
        )
        self.assertEqual(
            job.SOURCE_SPECS["tiki"].source_table,
            "ecom.E01TikiOrders",
        )
        self.assertIn("CAST(NULL AS nvarchar(4000))", job.SOURCE_SPECS["tiki"].query)

    def test_unknown_source_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            job.get_source_spec("arbitrary.table")

    def test_missing_secret_reports_only_key_name(self) -> None:
        del self.environment["MSSQL_PASSWORD"]
        with self.assertRaisesRegex(ValueError, "MSSQL_PASSWORD"):
            job.load_runtime_config(self.environment)

    def test_invalid_host_port_and_tls_values_are_rejected(self) -> None:
        for key, value in (
            ("MSSQL_HOST", "unsafe;property=true"),
            ("MSSQL_PORT", "not-a-port"),
            ("MSSQL_ENCRYPT", "sometimes"),
        ):
            with self.subTest(key=key):
                invalid = dict(self.environment)
                invalid[key] = value
                with self.assertRaises(ValueError):
                    job.load_runtime_config(invalid)

    def test_jdbc_url_has_no_credentials(self) -> None:
        config = job.load_runtime_config(self.environment)
        jdbc_url = job.build_mssql_jdbc_url(config)
        self.assertIn("databaseName=EDW_Tech", jdbc_url)
        self.assertIn("encrypt=true", jdbc_url)
        self.assertIn("trustServerCertificate=false", jdbc_url)
        self.assertNotIn(self.environment["MSSQL_USER"], jdbc_url)
        self.assertNotIn(self.environment["MSSQL_PASSWORD"], jdbc_url)


class Phase04TransformationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from pyspark.sql import SparkSession

        cls.spark = (
            SparkSession.builder.master("local[1]")
            .appName("phase04-transformation-tests")
            .config("spark.ui.enabled", "false")
            .config("spark.sql.ansi.enabled", "false")
            .config("spark.sql.legacy.timeParserPolicy", "CORRECTED")
            .getOrCreate()
        )
        cls.spark.sparkContext.setLogLevel("ERROR")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.spark.stop()

    def _raw_dataframe(self):
        return self.spark.createDataFrame(
            [
                ("A-1", "2025-10-01 12:30:45", "paid", "Buyer", "12.34"),
                ("A-2", "not-a-date", "new", "NULL", "not-an-amount"),
            ],
            (
                "raw_order_id string, raw_order_date string, "
                "raw_order_status string, raw_buyer_name string, "
                "raw_total_amount string"
            ),
        )

    def test_normalization_and_conversion_metrics(self) -> None:
        transformed = job.transform_source(self._raw_dataframe(), "lazada")
        self.assertEqual(tuple(transformed.columns[:6]), job.CANONICAL_COLUMNS)
        rows = transformed.orderBy("order_id").collect()
        self.assertEqual(str(rows[0].total_amount), "12.34")
        self.assertIsNotNone(rows[0].order_date)
        self.assertIsNone(rows[1].order_date)
        self.assertIsNone(rows[1].total_amount)
        self.assertIsNone(rows[1].buyer_name)
        self.assertEqual(
            job.calculate_metrics(transformed),
            {
                "source_count": 2,
                "order_date_conversion_failures": 1,
                "total_amount_conversion_failures": 1,
            },
        )

    def test_tiki_buyer_name_is_typed_string_null(self) -> None:
        transformed = job.transform_source(self._raw_dataframe(), "tiki")
        buyer_field = transformed.schema["buyer_name"]
        self.assertEqual(buyer_field.dataType.simpleString(), "string")
        self.assertTrue(all(row.buyer_name is None for row in transformed.collect()))
        self.assertTrue(all(row.platform == "tiki" for row in transformed.collect()))

    def test_live_source_date_formats_are_supported(self) -> None:
        cases = (
            ("lazada", "01 Jan 2022 03:48"),
            ("shopee", "2022-01-01 00:00"),
            ("tiki", "21/04/2023"),
            ("tiki", "7/11/2022"),
        )
        for source_key, raw_date in cases:
            with self.subTest(source_key=source_key):
                dataframe = self.spark.createDataFrame(
                    [("A-1", raw_date, "paid", "Buyer", "12.34")],
                    (
                        "raw_order_id string, raw_order_date string, "
                        "raw_order_status string, raw_buyer_name string, "
                        "raw_total_amount string"
                    ),
                )
                transformed = job.transform_source(dataframe, source_key)
                row = transformed.first()
                self.assertIsNotNone(row.order_date)
                self.assertEqual(
                    job.calculate_metrics(transformed)[
                        "order_date_conversion_failures"
                    ],
                    0,
                )


if __name__ == "__main__":
    unittest.main()
