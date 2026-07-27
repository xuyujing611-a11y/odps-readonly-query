import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from report_doctor.gateway_client import (
    DEFAULT_GATEWAY_HTTP_TIMEOUT_SECONDS,
    append_evidence_log,
    build_parser,
    check_health,
    gateway_http_timeout_seconds,
    latest_partition_rows,
    payload_from_args,
    save_node_code_rows,
)


class GatewayClientTests(unittest.TestCase):
    def test_gateway_http_timeout_defaults_above_sql_timeout_and_can_be_overridden(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(gateway_http_timeout_seconds(), DEFAULT_GATEWAY_HTTP_TIMEOUT_SECONDS)

        self.assertGreaterEqual(DEFAULT_GATEWAY_HTTP_TIMEOUT_SECONDS, 330)

        with patch.dict(os.environ, {"ODPS_GATEWAY_HTTP_TIMEOUT_SECONDS": "360"}, clear=True):
            self.assertEqual(gateway_http_timeout_seconds(), 360)

    def test_gateway_http_timeout_rejects_invalid_override(self):
        with patch.dict(os.environ, {"ODPS_GATEWAY_HTTP_TIMEOUT_SECONDS": "0"}, clear=True):
            with self.assertRaisesRegex(ValueError, "ODPS_GATEWAY_HTTP_TIMEOUT_SECONDS"):
                gateway_http_timeout_seconds()

    def test_latest_partition_rows_falls_back_to_partitions_fetcher(self):
        seen_payloads = []

        def fetcher(payload):
            seen_payloads.append(payload)
            return [
                {"0": ["pt=20241129", "pt=20250715"]},
                {"0": ["pt=20241129", "pt=20260527"]},
            ]

        rows = latest_partition_rows("yh_doc_cdm.dim_matl", token_index=1, fetcher=fetcher)

        self.assertEqual(rows[0]["partition_value"], "20260527")
        self.assertEqual(seen_payloads[0]["action"], "partitions")
        self.assertEqual(seen_payloads[0]["limit"], 10000)

    def test_catalog_payloads_use_controlled_templates(self):
        parser = build_parser()

        catalog_args = parser.parse_args(["catalog", "columns", "yh_doc_cdm.dim_matl", "--limit", "50"])
        self.assertEqual(
            payload_from_args(catalog_args),
            {
                "action": "catalog",
                "template": "columns",
                "table": "yh_doc_cdm.dim_matl",
                "limit": 50,
            },
        )

        logic_args = parser.parse_args(["logic", "yh_doc_cdm.dim_matl"])
        self.assertEqual(
            payload_from_args(logic_args),
            {
                "action": "catalog",
                "template": "logic",
                "table": "yh_doc_cdm.dim_matl",
                "limit": 20,
            },
        )

        table_logic_args = parser.parse_args(["table-logic", "yh_doc_cdm.dim_matl"])
        self.assertEqual(
            payload_from_args(table_logic_args),
            {
                "action": "table-logic",
                "table": "yh_doc_cdm.dim_matl",
                "limit": 20,
                "max_nodes": 20,
                "node_id": None,
                "project_id": None,
                "connection": None,
                "file_type": None,
                "matched_output": None,
                "require_single_node": False,
            },
        )

    def test_new_diagnostic_payloads(self):
        parser = build_parser()

        health_args = parser.parse_args(["health"])
        self.assertEqual(payload_from_args(health_args), {"action": "health"})

        quick_count_args = parser.parse_args(["quick-count", "yh_doc_cdm.dim_matl", "--bizdate", "latest"])
        self.assertEqual(
            payload_from_args(quick_count_args),
            {
                "action": "quick-count",
                "table": "yh_doc_cdm.dim_matl",
                "bizdate": "latest",
                "partition_col": "pt",
                "limit": 1,
                "token_index": None,
                "method": "max-pt",
            },
        )

        sample_args = parser.parse_args(["sample", "yh_doc_cdm.dim_matl", "--bizdate", "20260527", "--limit", "5"])
        self.assertEqual(
            payload_from_args(sample_args),
            {
                "action": "sample",
                "table": "yh_doc_cdm.dim_matl",
                "bizdate": "20260527",
                "partition_col": "pt",
                "limit": 5,
            },
        )

        profile_args = parser.parse_args(
            ["field-profile", "yh_doc_cdm.dim_matl", "matl_type_cd", "--bizdate", "20260527"]
        )
        self.assertEqual(payload_from_args(profile_args)["action"], "field-profile")

        compare_args = parser.parse_args(
            [
                "compare-tables",
                "yh_doc_ads.ads_a",
                "yh_doc_cdm.dws_a",
                "--key",
                "order_code",
                "--metric",
                "amount",
                "--bizdate",
                "20260527",
            ]
        )
        self.assertEqual(payload_from_args(compare_args)["action"], "compare-tables")

        trace_args = parser.parse_args(["trace-table", "yh_doc_cdm.dim_matl"])
        self.assertEqual(payload_from_args(trace_args)["action"], "table-logic")
        self.assertTrue(trace_args.compact_node_code)

        inspect_args = parser.parse_args(["inspect-table", "yh_doc_cdm.dim_matl"])
        self.assertEqual(payload_from_args(inspect_args)["action"], "inspect-table")
        self.assertFalse(payload_from_args(inspect_args)["include_partition_sample"])

        sql_args = parser.parse_args(["sql", "--no-require-partition", "select 1"])
        self.assertEqual(
            payload_from_args(sql_args),
            {
                "action": "sql",
                "sql": "select 1",
                "limit": 200,
                "require_partition": False,
            },
        )

    def test_evidence_log_appends_payload_and_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.jsonl"
            append_evidence_log(
                path,
                payload={"action": "quick-count", "table": "yh_doc_cdm.dim_matl"},
                rows=[{"row_cnt": 1}],
            )

            entry = json.loads(path.read_text(encoding="utf-8").strip())

        self.assertEqual(entry["payload"]["action"], "quick-count")
        self.assertEqual(entry["row_count"], 1)
        self.assertEqual(entry["rows"][0]["row_cnt"], 1)

    def test_evidence_log_summarizes_long_strings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.jsonl"
            append_evidence_log(
                path,
                payload={"action": "table-logic"},
                rows=[{"node_code": "x" * 2500}],
            )

            entry = json.loads(path.read_text(encoding="utf-8").strip())

        self.assertEqual(entry["rows"][0]["node_code"]["summary"], "truncated_long_string")
        self.assertEqual(entry["rows"][0]["node_code"]["length"], 2500)

    def test_save_node_code_rows_writes_code_and_can_compact_row(self):
        code = "insert overwrite table yh_doc_cdm.dim_matl select * from src;"
        with tempfile.TemporaryDirectory() as tmp:
            rows = save_node_code_rows(
                [
                    {
                        "table": "yh_doc_cdm.dim_matl",
                        "node_id": 123,
                        "node_name": "load_dim_matl",
                        "node_code": code,
                    }
                ],
                output_dir=tmp,
                compact=True,
            )

            saved_path = Path(rows[0]["node_code_path"])
            saved_text = saved_path.read_text(encoding="utf-8")

            self.assertTrue(saved_path.name.endswith("__punknown__n123__ftunknown__load_dim_matl.sql"))
            self.assertEqual(rows[0]["node_code_length"], len(code))
            self.assertNotIn("node_code", rows[0])
            self.assertIn("insert overwrite table", saved_text)

    def test_save_node_code_rows_does_not_overwrite_same_named_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = save_node_code_rows(
                [
                    {
                        "table": "yh_doc_ads.ads_information_of_the_four_stop_project",
                        "node_id": 210002417707,
                        "project_id": 121893,
                        "file_type": 10,
                        "node_name": "ads_information_of_the_four_stop_project",
                        "node_code": "select 'maxcompute';",
                    },
                    {
                        "table": "yh_doc_ads.ads_information_of_the_four_stop_project",
                        "node_id": 210001378722,
                        "project_id": 77681,
                        "file_type": 1095,
                        "node_name": "ads_information_of_the_four_stop_project",
                        "node_code": "select 'hologres';",
                    },
                ],
                output_dir=tmp,
                compact=True,
            )

            paths = [Path(row["node_code_path"]) for row in rows]

            self.assertEqual(len(set(paths)), 2)
            self.assertTrue(all(path.exists() for path in paths))
            self.assertIn("__n210002417707__", paths[0].name)
            self.assertIn("__n210001378722__", paths[1].name)
            self.assertEqual(paths[0].read_text(encoding="utf-8"), "select 'maxcompute';")
            self.assertEqual(paths[1].read_text(encoding="utf-8"), "select 'hologres';")

    def test_trace_table_payload_supports_exact_node_selection(self):
        args = build_parser().parse_args(
            [
                "trace-table",
                "yh_doc_ads.ads_information_of_the_four_stop_project",
                "--node-id",
                "210002417707",
                "--project-id",
                "121893",
                "--connection",
                "yh_doc_ads",
                "--file-type",
                "10",
                "--matched-output",
                "yh_doc_ads.ads_information_of_the_four_stop_project",
                "--max-nodes",
                "1",
                "--require-single-node",
            ]
        )

        payload = payload_from_args(args)

        self.assertEqual(payload["node_id"], 210002417707)
        self.assertEqual(payload["project_id"], 121893)
        self.assertEqual(payload["connection"], "yh_doc_ads")
        self.assertEqual(payload["file_type"], 10)
        self.assertEqual(payload["max_nodes"], 1)
        self.assertTrue(payload["require_single_node"])

    def test_health_returns_structured_error_when_state_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = check_health(state_path=Path(tmp) / "missing_gateway_state.json")

        self.assertEqual(rows[0]["status"], "error")


if __name__ == "__main__":
    unittest.main()
