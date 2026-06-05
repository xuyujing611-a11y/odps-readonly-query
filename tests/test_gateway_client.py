import json
import tempfile
import unittest
from pathlib import Path

from report_doctor.gateway_client import (
    append_evidence_log,
    build_parser,
    check_health,
    latest_partition_rows,
    payload_from_args,
)


class GatewayClientTests(unittest.TestCase):
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

        inspect_args = parser.parse_args(["inspect-table", "yh_doc_cdm.dim_matl"])
        self.assertEqual(payload_from_args(inspect_args)["action"], "inspect-table")

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

    def test_health_returns_structured_error_when_state_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = check_health(state_path=Path(tmp) / "missing_gateway_state.json")

        self.assertEqual(rows[0]["status"], "error")


if __name__ == "__main__":
    unittest.main()
