import unittest

from report_doctor.gateway_client import build_parser, latest_partition_rows, payload_from_args


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


if __name__ == "__main__":
    unittest.main()
