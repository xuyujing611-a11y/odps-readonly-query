import unittest

from report_doctor.odps_client import rows_to_dicts


class OdpsClientTests(unittest.TestCase):
    def test_rows_to_dicts_converts_key_value_pair_rows(self):
        reader = [
            [
                ("table_catalog", "yh_doc_cdm"),
                ("column_name", "etl_time"),
                ("is_partition_key", False),
            ]
        ]

        self.assertEqual(
            rows_to_dicts(reader),
            [
                {
                    "table_catalog": "yh_doc_cdm",
                    "column_name": "etl_time",
                    "is_partition_key": False,
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
