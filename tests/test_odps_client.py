import unittest
from unittest.mock import patch

from report_doctor import odps_client
from report_doctor.odps_client import OdpsQueryTimeoutError, execute_sql_to_dicts, rows_to_dicts


class FakeReader:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self.rows

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeInstance:
    id = "fake_instance_id"

    def __init__(self, rows=None, wait_error=None):
        self.rows = rows or []
        self.wait_error = wait_error
        self.wait_timeout = None
        self.reader_opened = False
        self.stopped = False

    def wait_for_success(self, *, timeout=None):
        self.wait_timeout = timeout
        if self.wait_error:
            raise self.wait_error

    def open_reader(self):
        self.reader_opened = True
        return FakeReader(self.rows)

    def stop(self):
        self.stopped = True


class FakeOdps:
    def __init__(self, instance):
        self.instance = instance
        self.seen_sql = None
        self.seen_hints = None

    def run_sql(self, sql, *, hints=None):
        self.seen_sql = sql
        self.seen_hints = hints
        return self.instance


class WaitTimeoutError(Exception):
    pass


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

    def test_execute_sql_waits_with_timeout_before_opening_reader(self):
        instance = FakeInstance(rows=[[("ok", 1)], [("ok", 2)]])
        fake_odps = FakeOdps(instance)

        rows = execute_sql_to_dicts(
            fake_odps,
            "select * from t where pt = '20260527'",
            limit=1,
            hints={"odps.namespace.schema": "true"},
            timeout_seconds=300,
        )

        self.assertEqual(fake_odps.seen_sql, "select * from t where pt = '20260527'")
        self.assertEqual(fake_odps.seen_hints, {"odps.namespace.schema": "true"})
        self.assertEqual(instance.wait_timeout, 300)
        self.assertTrue(instance.reader_opened)
        self.assertEqual(rows, [{"ok": 1}])

    def test_execute_sql_timeout_stops_instance_and_does_not_open_reader(self):
        instance = FakeInstance(wait_error=WaitTimeoutError("timed out"))
        fake_odps = FakeOdps(instance)

        with patch.object(odps_client, "_is_wait_timeout_error", return_value=True):
            with self.assertRaisesRegex(OdpsQueryTimeoutError, "timed out after 300 seconds"):
                execute_sql_to_dicts(
                    fake_odps,
                    "select * from t where pt = '20260527'",
                    timeout_seconds=300,
                )

        self.assertTrue(instance.stopped)
        self.assertFalse(instance.reader_opened)


if __name__ == "__main__":
    unittest.main()
