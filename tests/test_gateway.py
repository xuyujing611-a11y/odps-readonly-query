import tempfile
import unittest
from pathlib import Path

from report_doctor.gateway import (
    GatewayError,
    build_gateway_sql,
    extract_latest_partition,
    extract_latest_partition_from_max_pt,
    handle_gateway_payload,
)
from report_doctor.sql_safety import SqlSafetyError


class GatewayTests(unittest.TestCase):
    def test_builds_supported_gateway_sql(self):
        self.assertEqual(
            build_gateway_sql({"action": "count", "table": "yh_doc_cdm.dim_matl", "bizdate": "20250715"}),
            "SELECT COUNT(1) AS row_cnt FROM yh_doc_cdm.dim_matl WHERE pt = '20250715'",
        )
        self.assertEqual(
            build_gateway_sql({"action": "partitions", "table": "yh_doc_cdm.dim_matl"}),
            "SHOW PARTITIONS yh_doc_cdm.dim_matl",
        )
        self.assertEqual(
            build_gateway_sql({"action": "sql", "sql": "SELECT 1 AS x FROM t WHERE pt = '20250715'"}),
            "SELECT 1 AS x FROM t WHERE pt = '20250715'",
        )

    def test_builds_controlled_system_catalog_templates(self):
        table_sql = build_gateway_sql(
            {"action": "catalog", "template": "table", "table": "yh_doc_cdm.dim_matl", "limit": 20}
        )
        self.assertIn("FROM SYSTEM_CATALOG.INFORMATION_SCHEMA.tables", table_sql)
        self.assertIn("table_catalog = 'yh_doc_cdm'", table_sql)
        self.assertIn("table_name = 'dim_matl'", table_sql)
        self.assertIn("view_original_text", table_sql)
        self.assertTrue(table_sql.endswith("LIMIT 20"))

        columns_sql = build_gateway_sql(
            {"action": "catalog", "template": "columns", "table": "yh_doc_cdm.dim_matl"}
        )
        self.assertIn("FROM SYSTEM_CATALOG.INFORMATION_SCHEMA.columns", columns_sql)
        self.assertIn("ORDER BY table_catalog, table_name, ordinal_position", columns_sql)

        partitions_sql = build_gateway_sql(
            {"action": "catalog", "template": "partitions", "table": "dim_matl", "limit": 500}
        )
        self.assertIn("FROM SYSTEM_CATALOG.INFORMATION_SCHEMA.partitions", partitions_sql)
        self.assertNotIn("table_catalog =", partitions_sql)
        self.assertIn("table_name = 'dim_matl'", partitions_sql)
        self.assertTrue(partitions_sql.endswith("LIMIT 500"))

    def test_rejects_unknown_action_and_unsafe_table(self):
        with self.assertRaises(GatewayError):
            build_gateway_sql({"action": "drop", "table": "t"})

        with self.assertRaises(ValueError):
            build_gateway_sql({"action": "count", "table": "t; DROP TABLE x", "bizdate": "20250715"})

        with self.assertRaises(GatewayError):
            build_gateway_sql({"action": "catalog", "template": "tasks_history", "table": "t"})

        with self.assertRaises(ValueError):
            build_gateway_sql({"action": "catalog", "template": "table", "table": "t; DROP TABLE x"})

        with self.assertRaises(ValueError):
            build_gateway_sql({"action": "catalog", "template": "table", "table": "t", "limit": 5001})

    def test_handle_payload_rejects_mutation_before_executor(self):
        calls = []

        def executor(sql, limit):
            calls.append(sql)
            return []

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SqlSafetyError):
                handle_gateway_payload(
                    {"action": "sql", "sql": "DELETE FROM t WHERE pt = '20250715'"},
                    executor,
                    audit_path=Path(tmp) / "audit.jsonl",
                )

        self.assertEqual(calls, [])

    def test_handle_payload_executes_safe_count_and_audits(self):
        def executor(sql, limit):
            self.assertEqual(
                sql,
                "SELECT COUNT(1) AS row_cnt FROM yh_doc_cdm.dim_matl WHERE pt = '20250715'",
            )
            return [{"row_cnt": 123}]

        with tempfile.TemporaryDirectory() as tmp:
            rows = handle_gateway_payload(
                {"action": "count", "table": "yh_doc_cdm.dim_matl", "bizdate": "20250715"},
                executor,
                audit_path=Path(tmp) / "audit.jsonl",
            )

        self.assertEqual(rows, [{"row_cnt": 123}])

    def test_handle_payload_quick_count_uses_unambiguous_latest_partition(self):
        calls = []

        def executor(sql, limit, hints=None):
            calls.append((sql, limit, hints))
            if sql == "SELECT MAX_PT('yh_doc_cdm.dim_matl') AS partition_value":
                return [{"partition_value": "20260527"}]
            if sql == "SELECT COUNT(1) AS row_cnt FROM yh_doc_cdm.dim_matl WHERE pt = '20260527'":
                return [{"row_cnt": 279023}]
            self.fail(f"unexpected SQL: {sql}")

        with tempfile.TemporaryDirectory() as tmp:
            rows = handle_gateway_payload(
                {"action": "quick-count", "table": "yh_doc_cdm.dim_matl", "bizdate": "latest"},
                executor,
                audit_path=Path(tmp) / "audit.jsonl",
            )

        self.assertEqual(rows[0]["status"], "ok")
        self.assertEqual(rows[0]["partition_value"], "20260527")
        self.assertEqual(rows[0]["row_cnt"], 279023)
        self.assertEqual(rows[0]["latest_partition"]["method"], "max_pt")
        self.assertEqual(len(calls), 2)

    def test_handle_payload_quick_count_stops_on_ambiguous_latest_partition(self):
        calls = []

        def executor(sql, limit, hints=None):
            calls.append(sql)
            return [
                {"0": ["pt=20250921", "pt=20250922"]},
                {"0": ["pt=20250921", "pt=20250923"]},
            ]

        with tempfile.TemporaryDirectory() as tmp:
            rows = handle_gateway_payload(
                {
                    "action": "quick-count",
                    "table": "yh_doc_cdm.dim_matl",
                    "bizdate": "latest",
                    "method": "show-partitions",
                },
                executor,
                audit_path=Path(tmp) / "audit.jsonl",
            )

        self.assertEqual(rows[0]["status"], "ambiguous")
        self.assertIn("candidates_by_token_index", rows[0])
        self.assertEqual(calls, ["SHOW PARTITIONS yh_doc_cdm.dim_matl"])

    def test_handle_payload_inspect_table_collects_metadata_and_latest_partition(self):
        def executor(sql, limit, hints=None):
            if "INFORMATION_SCHEMA.tables" in sql:
                return [{"table_name": "dim_matl", "is_partitioned": True}]
            if "INFORMATION_SCHEMA.columns" in sql:
                return [
                    {"column_name": "matl_cd", "is_partition_key": False},
                    {"column_name": "pt", "is_partition_key": True},
                ]
            if "INFORMATION_SCHEMA.partitions" in sql:
                return [{"partition_name": "pt=20260527"}]
            if sql == "SELECT MAX_PT('yh_doc_cdm.dim_matl') AS partition_value":
                return [{"partition_value": "20260527"}]
            self.fail(f"unexpected SQL: {sql}")

        with tempfile.TemporaryDirectory() as tmp:
            rows = handle_gateway_payload(
                {"action": "inspect-table", "table": "yh_doc_cdm.dim_matl"},
                executor,
                audit_path=Path(tmp) / "audit.jsonl",
            )

        result = rows[0]
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["partition_keys"], ["pt"])
        self.assertEqual(result["latest_partition"]["partition_value"], "20260527")
        self.assertEqual(result["catalog_columns_status"], "ok")

    def test_builds_sample_field_profile_and_compare_sql(self):
        self.assertEqual(
            build_gateway_sql(
                {
                    "action": "sample",
                    "table": "yh_doc_cdm.dim_matl",
                    "bizdate": "20260527",
                    "limit": 10,
                }
            ),
            "SELECT * FROM yh_doc_cdm.dim_matl WHERE pt = '20260527' LIMIT 10",
        )
        self.assertEqual(
            build_gateway_sql(
                {
                    "action": "field-profile",
                    "table": "yh_doc_cdm.dim_matl",
                    "field": "matl_type_cd",
                    "bizdate": "20260527",
                    "limit": 20,
                }
            ),
            (
                "SELECT matl_type_cd AS value, COUNT(1) AS row_cnt "
                "FROM yh_doc_cdm.dim_matl WHERE pt = '20260527' "
                "GROUP BY matl_type_cd ORDER BY row_cnt DESC LIMIT 20"
            ),
        )
        compare_sql = build_gateway_sql(
            {
                "action": "compare-tables",
                "left_table": "yh_doc_ads.ads_a",
                "right_table": "yh_doc_cdm.dws_a",
                "key": "order_code",
                "metric": "amount",
                "bizdate": "20260527",
                "limit": 50,
            }
        )
        self.assertIn("FULL OUTER JOIN", compare_sql)
        self.assertIn("left_amount", compare_sql)
        self.assertIn("right_amount", compare_sql)

    def test_handle_payload_table_logic_uses_dataworks_when_catalog_has_no_view_sql(self):
        sql_calls = []

        class FakeDataWorks:
            project_env = "PROD"

            def find_nodes_by_outputs(self, outputs):
                return [
                    {
                        "Output": "yh_doc_cdm.dim_matl",
                        "NodeList": [{"NodeId": 123, "NodeName": "load_dim_matl"}],
                    }
                ]

            def get_node(self, node_id):
                return {"NodeId": node_id, "NodeName": "load_dim_matl", "CronExpress": "00 00 00 * * ?"}

            def get_node_code(self, node_id):
                return "insert overwrite table yh_doc_cdm.dim_matl select * from src;"

        def executor(sql, limit, hints=None):
            sql_calls.append((sql, limit, hints))
            return [{"table_type": "MANAGED_TABLE", "view_original_text": None}]

        with tempfile.TemporaryDirectory() as tmp:
            rows = handle_gateway_payload(
                {"action": "table-logic", "table": "yh_doc_cdm.dim_matl", "limit": 20},
                executor,
                audit_path=Path(tmp) / "audit.jsonl",
                dataworks_client=FakeDataWorks(),
                odps_project="yh_doc_cdm",
            )

        self.assertIn("FROM SYSTEM_CATALOG.INFORMATION_SCHEMA.tables", sql_calls[0][0])
        self.assertEqual(rows[0]["source"], "dataworks_openapi")
        self.assertEqual(rows[0]["node_id"], 123)
        self.assertIn("insert overwrite table", rows[0]["node_code"])
        self.assertEqual(rows[0]["catalog_status"], "ok")
        self.assertIsNone(rows[0]["catalog_error"])

    def test_handle_payload_table_logic_uses_dataworks_when_catalog_fails(self):
        class FakeDataWorks:
            project_env = "PROD"

            def find_nodes_by_outputs(self, outputs):
                return [
                    {
                        "Output": "yh_doc_cdm.dim_matl",
                        "NodeList": [{"NodeId": 123, "NodeName": "load_dim_matl"}],
                    }
                ]

            def get_node(self, node_id):
                return {"NodeId": node_id, "NodeName": "load_dim_matl", "CronExpress": "00 00 00 * * ?"}

            def get_node_code(self, node_id):
                return "insert overwrite table yh_doc_cdm.dim_matl select * from src;"

        def executor(sql, limit, hints=None):
            raise RuntimeError("Authorization Failed on SYSTEM_CATALOG.INFORMATION_SCHEMA.tables")

        with tempfile.TemporaryDirectory() as tmp:
            rows = handle_gateway_payload(
                {"action": "table-logic", "table": "yh_doc_cdm.dim_matl", "limit": 20},
                executor,
                audit_path=Path(tmp) / "audit.jsonl",
                dataworks_client=FakeDataWorks(),
                odps_project="yh_doc_cdm",
            )

        self.assertEqual(rows[0]["source"], "dataworks_openapi")
        self.assertEqual(rows[0]["node_id"], 123)
        self.assertEqual(rows[0]["catalog_status"], "error")
        self.assertIn("Authorization Failed", rows[0]["catalog_error"])

    def test_handle_payload_executes_catalog_with_namespace_hints(self):
        calls = []

        def executor(sql, limit, hints=None):
            calls.append((sql, limit, hints))
            return [{"table_name": "dim_matl", "view_original_text": None}]

        with tempfile.TemporaryDirectory() as tmp:
            rows = handle_gateway_payload(
                {"action": "catalog", "template": "table", "table": "yh_doc_cdm.dim_matl", "limit": 20},
                executor,
                audit_path=Path(tmp) / "audit.jsonl",
            )

        self.assertEqual(rows, [{"table_name": "dim_matl", "view_original_text": None}])
        self.assertEqual(calls[0][1], 20)
        self.assertEqual(
            calls[0][2],
            {
                "odps.namespace.schema": "true",
                "odps.sql.allow.namespace.schema": "true",
            },
        )


    def test_extract_latest_partition_from_max_pt_accepts_plain_or_named_values(self):
        latest = extract_latest_partition_from_max_pt([{"partition_value": "pt=20260527"}])
        self.assertEqual(latest["partition_value"], "20260527")
        self.assertEqual(latest["method"], "max_pt")

        latest = extract_latest_partition_from_max_pt([{"partition_value": "20260528"}])
        self.assertEqual(latest["partition_value"], "20260528")

    def test_quick_count_falls_back_to_show_partitions_when_max_pt_fails(self):
        calls = []

        def executor(sql, limit, hints=None):
            calls.append(sql)
            if sql == "SELECT MAX_PT('yh_doc_cdm.dim_matl') AS partition_value":
                raise RuntimeError("MAX_PT unavailable")
            if sql == "SHOW PARTITIONS yh_doc_cdm.dim_matl":
                return [{"0": "pt=20260527"}]
            if sql == "SELECT COUNT(1) AS row_cnt FROM yh_doc_cdm.dim_matl WHERE pt = '20260527'":
                return [{"row_cnt": 123}]
            self.fail(f"unexpected SQL: {sql}")

        with tempfile.TemporaryDirectory() as tmp:
            rows = handle_gateway_payload(
                {"action": "quick-count", "table": "yh_doc_cdm.dim_matl", "bizdate": "latest"},
                executor,
                audit_path=Path(tmp) / "audit.jsonl",
            )

        self.assertEqual(rows[0]["row_cnt"], 123)
        self.assertEqual(rows[0]["latest_partition"]["method"], "show_partitions")
        self.assertEqual(rows[0]["latest_partition"]["fallback_from"], "max_pt")
        self.assertEqual(calls[0], "SELECT MAX_PT('yh_doc_cdm.dim_matl') AS partition_value")
        self.assertEqual(calls[1], "SHOW PARTITIONS yh_doc_cdm.dim_matl")

    def test_extract_latest_partition_reports_ambiguous_duplicate_partition_tokens(self):
        rows = [
            {"0": ["pt=20250921", "pt=20250922"]},
            {"0": ["pt=20250921", "pt=20250923"]},
        ]

        latest = extract_latest_partition(rows)

        self.assertEqual(latest["status"], "ambiguous")
        self.assertEqual(latest["partition_col"], "pt")
        self.assertEqual(latest["partition_count"], 2)
        self.assertEqual(
            latest["candidates_by_token_index"],
            [
                {"token_index": 0, "partition_value": "20250921", "partition": "pt=20250921"},
                {"token_index": 1, "partition_value": "20250923", "partition": "pt=20250923"},
            ],
        )
        self.assertIn("ambiguous", latest["message"])
        self.assertNotIn("partition_value", latest)

    def test_extract_latest_partition_can_use_explicit_token_index(self):
        rows = [
            {"0": ["pt=20241129", "pt=20250715"]},
            {"0": ["pt=20241129", "pt=20260527"]},
            {"0": ["pt=20241129", "pt=20251231"]},
        ]

        latest = extract_latest_partition(rows, token_index=1)

        self.assertEqual(
            latest,
            {
                "partition_col": "pt",
                "partition_value": "20260527",
                "partition": "pt=20260527",
                "partition_count": 3,
                "token_index": 1,
            },
        )

    def test_handle_payload_returns_latest_partition_without_guessing_from_limit(self):
        def executor(sql, limit):
            self.assertEqual(sql, "SHOW PARTITIONS yh_doc_cdm.dim_matl")
            self.assertEqual(limit, 10000)
            return [
                {"0": ["pt=20241129", "pt=20250715"]},
                {"0": ["pt=20241129", "pt=20260527"]},
            ]

        with tempfile.TemporaryDirectory() as tmp:
            rows = handle_gateway_payload(
                {
                    "action": "latest-partition",
                    "table": "yh_doc_cdm.dim_matl",
                    "token_index": 1,
                    "method": "show-partitions",
                },
                executor,
                audit_path=Path(tmp) / "audit.jsonl",
            )

        self.assertEqual(rows[0]["partition_value"], "20260527")


if __name__ == "__main__":
    unittest.main()
