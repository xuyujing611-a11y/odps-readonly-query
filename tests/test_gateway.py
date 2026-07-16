import tempfile
import unittest
from pathlib import Path

from report_doctor.gateway import (
    GatewayError,
    action_requires_partition,
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

    def test_sql_payload_can_disable_partition_requirement(self):
        self.assertFalse(action_requires_partition({"action": "sql", "require_partition": False}))
        self.assertTrue(action_requires_partition({"action": "sql", "require_partition": True}))
        self.assertTrue(action_requires_partition({"action": "sql"}))

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
        sql_calls = []

        def executor(sql, limit, hints=None):
            sql_calls.append(sql)
            if "INFORMATION_SCHEMA.tables" in sql:
                return [{"table_name": "dim_matl", "is_partitioned": True}]
            if "INFORMATION_SCHEMA.columns" in sql:
                return [
                    {"column_name": "matl_cd", "is_partition_key": False},
                    {"column_name": "pt", "is_partition_key": True},
                ]
            if "INFORMATION_SCHEMA.partitions" in sql:
                self.fail("inspect-table should skip partition sample by default")
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
        self.assertEqual(result["catalog_partitions_status"], "skipped")
        self.assertFalse(any("INFORMATION_SCHEMA.partitions" in sql for sql in sql_calls))

    def test_handle_payload_inspect_table_can_include_partition_sample(self):
        def executor(sql, limit, hints=None):
            if "INFORMATION_SCHEMA.tables" in sql:
                return [{"table_name": "dim_matl", "is_partitioned": True}]
            if "INFORMATION_SCHEMA.columns" in sql:
                return [{"column_name": "pt", "is_partition_key": True}]
            if "INFORMATION_SCHEMA.partitions" in sql:
                return [{"partition_name": "pt=20260527"}]
            if sql == "SELECT MAX_PT('yh_doc_cdm.dim_matl') AS partition_value":
                return [{"partition_value": "20260527"}]
            self.fail(f"unexpected SQL: {sql}")

        with tempfile.TemporaryDirectory() as tmp:
            rows = handle_gateway_payload(
                {
                    "action": "inspect-table",
                    "table": "yh_doc_cdm.dim_matl",
                    "include_partition_sample": True,
                },
                executor,
                audit_path=Path(tmp) / "audit.jsonl",
            )

        self.assertEqual(rows[0]["catalog_partitions_status"], "ok")
        self.assertEqual(rows[0]["catalog_partitions_sample"], [{"partition_name": "pt=20260527"}])

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

    def test_table_logic_ranks_producer_and_can_select_exact_node(self):
        class FakeDataWorks:
            project_env = "PROD"

            def find_nodes_by_outputs(self, outputs):
                return [
                    {
                        "Output": "yh_doc_ads.ads_information_of_the_four_stop_project",
                        "NodeList": [
                            {"NodeId": 210001378722},
                            {"NodeId": 210002417707},
                        ],
                    }
                ]

            def get_node(self, node_id):
                if node_id == 210002417707:
                    return {
                        "NodeId": node_id,
                        "NodeName": "ads_information_of_the_four_stop_project",
                        "ProjectId": 121893,
                        "FileType": 10,
                        "Connection": "yh_doc_ads",
                    }
                return {
                    "NodeId": node_id,
                    "NodeName": "ads_information_of_the_four_stop_project",
                    "ProjectId": 77681,
                    "FileType": 1095,
                    "Connection": "data_holo",
                }

            def get_node_code(self, node_id):
                return f"select {node_id}"

        def executor(sql, limit, hints=None):
            return []

        with tempfile.TemporaryDirectory() as tmp:
            rows = handle_gateway_payload(
                {
                    "action": "table-logic",
                    "table": "yh_doc_ads.ads_information_of_the_four_stop_project",
                    "limit": 20,
                    "max_nodes": 20,
                },
                executor,
                audit_path=Path(tmp) / "audit.jsonl",
                dataworks_client=FakeDataWorks(),
                odps_project="yh_doc_ads",
            )
            exact = handle_gateway_payload(
                {
                    "action": "table-logic",
                    "table": "yh_doc_ads.ads_information_of_the_four_stop_project",
                    "node_id": 210002417707,
                    "require_single_node": True,
                },
                executor,
                audit_path=Path(tmp) / "audit.jsonl",
                dataworks_client=FakeDataWorks(),
                odps_project="yh_doc_ads",
            )

        self.assertEqual([row["node_id"] for row in rows], [210002417707, 210001378722])
        self.assertEqual(rows[0]["node_role"], "maxcompute_producer")
        self.assertIsNone(rows[0]["selection_warning"])
        self.assertEqual(rows[1]["node_role"], "hologres_sync")
        self.assertIn("not the MaxCompute producer", rows[1]["selection_warning"])
        self.assertEqual([row["node_id"] for row in exact], [210002417707])
        self.assertEqual(exact[0]["candidate_count"], 1)

    def test_table_logic_require_single_node_rejects_ambiguous_candidates(self):
        class FakeDataWorks:
            project_env = "PROD"

            def find_nodes_by_outputs(self, outputs):
                return [{"Output": "yh_doc_ads.target", "NodeList": [{"NodeId": 1}, {"NodeId": 2}]}]

            def get_node(self, node_id):
                return {"NodeId": node_id, "NodeName": "target", "ProjectId": node_id, "FileType": 10}

            def get_node_code(self, node_id):
                return f"select {node_id}"

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "resolved to 2 candidates"):
                handle_gateway_payload(
                    {
                        "action": "table-logic",
                        "table": "yh_doc_ads.target",
                        "require_single_node": True,
                    },
                    lambda sql, limit, hints=None: [],
                    audit_path=Path(tmp) / "audit.jsonl",
                    dataworks_client=FakeDataWorks(),
                    odps_project="yh_doc_ads",
                )

    def test_table_logic_limit_is_applied_to_node_candidates(self):
        class FakeDataWorks:
            project_env = "PROD"

            def find_nodes_by_outputs(self, outputs):
                return [{"Output": "yh_doc_ads.target", "NodeList": [{"NodeId": 1}, {"NodeId": 2}]}]

            def get_node(self, node_id):
                return {"NodeId": node_id, "NodeName": "target", "ProjectId": node_id, "FileType": 10}

            def get_node_code(self, node_id):
                return f"select {node_id}"

        with tempfile.TemporaryDirectory() as tmp:
            rows = handle_gateway_payload(
                {"action": "table-logic", "table": "yh_doc_ads.target", "limit": 1},
                lambda sql, limit, hints=None: [],
                audit_path=Path(tmp) / "audit.jsonl",
                dataworks_client=FakeDataWorks(),
                odps_project="yh_doc_ads",
            )

        self.assertEqual(len(rows), 1)

    def test_handle_payload_read_only_schedule_actions_use_dataworks_only(self):
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

            def search_meta_tables(self, keyword):
                return []

            def get_node(self, node_id):
                return {
                    "NodeId": node_id,
                    "NodeName": "load_dim_matl",
                    "ProjectId": 999,
                    "OwnerId": "owner_a",
                    "CronExpress": "00 30 04-07/4 * * ?",
                }

            def get_node_code(self, node_id):
                return "insert overwrite table yh_doc_cdm.dim_matl select * from src;"

            def get_node_parents(self, node_id):
                return [{"NodeId": 122, "NodeName": "parent_node", "CronExpress": "00 30 04-07/4 * * ?"}]

            def get_node_children(self, node_id):
                return [{"NodeId": 124, "NodeName": "child_node"}]

            def list_instances(self, **kwargs):
                return [
                    {
                        "InstanceId": 88001,
                        "NodeId": kwargs["node_id"],
                        "Status": "SUCCESS",
                        "Bizdate": 1780675200000,
                        "CycTime": 1780777800000,
                        "BeginRunningTime": 1780789451000,
                        "FinishTime": 1780789467000,
                    }
                ]

            def get_instance_log(self, instance_id):
                return "\n".join(
                    [
                        "2026-06-07 07:38:07 INFO Current task status:RUNNING",
                        "2026-06-07 07:38:08 INFO Full Command ..",
                        "2026-06-07 07:38:08 INFO /opt/taobao/tbdpapp/odpswrapper/odpswrapper.py /tmp/task",
                        "2026-06-07 07:38:08 INFO SKYNET_TASKID=88001:",
                        "2026-06-07 07:38:09 INFO CREATE TABLE IF NOT EXISTS noisy_ddl",
                        "2026-06-07 07:38:10 INFO job id: 20260607abc",
                        "2026-06-07 07:38:11 INFO Current task status:SUCCESS",
                    ]
                )

        def executor(sql, limit, hints=None):
            sql_calls.append(sql)
            return []

        with tempfile.TemporaryDirectory() as tmp:
            audit_path = Path(tmp) / "audit.jsonl"
            schedule = handle_gateway_payload(
                {
                    "action": "batch-schedule-info",
                    "tables": ["yh_doc_cdm.dim_matl"],
                    "verify_permissions": True,
                },
                executor,
                audit_path=audit_path,
                dataworks_client=FakeDataWorks(),
                odps_project="yh_doc_cdm",
            )
            graph = handle_gateway_payload(
                {
                    "action": "schedule-graph",
                    "table": "yh_doc_cdm.dim_matl",
                    "direction": "both",
                    "depth": 1,
                    "verify_permissions": True,
                },
                executor,
                audit_path=audit_path,
                dataworks_client=FakeDataWorks(),
                odps_project="yh_doc_cdm",
            )
            instances = handle_gateway_payload(
                {
                    "action": "recent-instances",
                    "table": "yh_doc_cdm.dim_matl",
                    "bizdate": "20260605",
                    "verify_permissions": True,
                },
                executor,
                audit_path=audit_path,
                dataworks_client=FakeDataWorks(),
                odps_project="yh_doc_cdm",
            )
            logs = handle_gateway_payload(
                {"action": "instance-log-summary", "instance_id": 88001, "verify_permissions": True},
                executor,
                audit_path=audit_path,
                dataworks_client=FakeDataWorks(),
                odps_project="yh_doc_cdm",
            )

        self.assertEqual(sql_calls, [])
        self.assertEqual(schedule[0]["permission_status"], "ok")
        self.assertEqual(schedule[0]["cron_fire_times"], ["04:30"])
        self.assertEqual(schedule[0]["cron_fire_count_per_day"], 1)
        self.assertEqual(schedule[0]["latest_instances"][0]["InstanceId"], 88001)
        self.assertEqual(schedule[0]["latest_instances"][0]["Bizdate_beijing"], "2026-06-06 00:00:00")
        self.assertEqual(schedule[0]["latest_instances"][0]["CycTime_beijing"], "2026-06-07 04:30:00")
        self.assertEqual(schedule[0]["latest_instances"][0]["FinishTime_beijing"], "2026-06-07 07:44:27")
        self.assertEqual(schedule[0]["latest_instances"][0]["duration_seconds"], 16.0)
        self.assertEqual(graph[0]["parents"][0]["NodeId"], 122)
        self.assertEqual(graph[0]["parents"][0]["cron_fire_times"], ["04:30"])
        self.assertEqual(graph[0]["children"][0]["NodeId"], 124)
        self.assertEqual(instances[0]["permission_status"], "ok")
        self.assertEqual(instances[0]["FinishTime_beijing"], "2026-06-07 07:44:27")
        self.assertEqual(logs[0]["log_excerpt_policy"], "filtered_noise_removed")
        self.assertIn("Current task status:RUNNING", logs[0]["log_excerpt"])
        self.assertIn("job id: 20260607abc", logs[0]["log_excerpt"])
        self.assertNotIn("odpswrapper.py", logs[0]["log_excerpt"])
        self.assertNotIn("SKYNET_TASKID", logs[0]["log_excerpt"])
        self.assertNotIn("CREATE TABLE", logs[0]["log_excerpt"])
        self.assertEqual(logs[0]["odps_job_ids"], ["20260607abc"])
        self.assertEqual(logs[0]["odps_instance_ids"], ["88001"])

    def test_handle_payload_schedule_action_without_dataworks_reports_unverified_permission(self):
        def executor(sql, limit, hints=None):
            self.fail("schedule metadata action must not execute ODPS SQL without DataWorks")

        with tempfile.TemporaryDirectory() as tmp:
            rows = handle_gateway_payload(
                {"action": "batch-schedule-info", "tables": ["yh_doc_cdm.dim_matl"], "verify_permissions": True},
                executor,
                audit_path=Path(tmp) / "audit.jsonl",
                dataworks_client=None,
                odps_project="yh_doc_cdm",
            )

        self.assertEqual(rows[0]["status"], "unavailable")
        self.assertEqual(rows[0]["permission_status"], "unverified")

    def test_handle_payload_batch_freshness_combines_read_only_partition_count_and_schedule(self):
        sql_calls = []

        class FakeDataWorks:
            project_env = "PROD"

            def find_nodes_by_outputs(self, outputs):
                return [{"Output": "yh_doc_cdm.dim_matl", "NodeList": [{"NodeId": 123}]}]

            def search_meta_tables(self, keyword):
                return []

            def get_node(self, node_id):
                return {"NodeId": node_id, "ProjectId": 999, "NodeName": "load_dim_matl"}

            def get_node_code(self, node_id):
                return "select 1"

            def list_instances(self, **kwargs):
                return [{"InstanceId": 88001, "Status": "SUCCESS"}]

        def executor(sql, limit, hints=None):
            sql_calls.append(sql)
            if sql == "SELECT MAX_PT('yh_doc_cdm.dim_matl') AS partition_value":
                return [{"partition_value": "20260605"}]
            if sql == "SELECT COUNT(1) AS row_cnt FROM yh_doc_cdm.dim_matl WHERE pt = '20260605'":
                return [{"row_cnt": 99}]
            self.fail(f"unexpected SQL: {sql}")

        with tempfile.TemporaryDirectory() as tmp:
            rows = handle_gateway_payload(
                {
                    "action": "batch-freshness-check",
                    "tables": ["yh_doc_cdm.dim_matl"],
                    "expected_bizdate": "20260605",
                    "include_counts": True,
                    "verify_permissions": True,
                },
                executor,
                audit_path=Path(tmp) / "audit.jsonl",
                dataworks_client=FakeDataWorks(),
                odps_project="yh_doc_cdm",
            )

        self.assertEqual(rows[0]["status"], "fresh")
        self.assertEqual(rows[0]["row_cnt"], 99)
        self.assertEqual(rows[0]["schedule"]["permission_status"], "ok")
        self.assertEqual(len(sql_calls), 2)

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
