import json
import tempfile
import unittest
from pathlib import Path

from report_doctor.safe_runner import build_count_sql, build_partitions_sql, run_safe_sql
from report_doctor.sql_safety import SqlSafetyError


class SafeRunnerTests(unittest.TestCase):
    def test_run_safe_sql_rejects_mutation_before_executor_is_called(self):
        calls = []

        def executor(sql, limit):
            calls.append((sql, limit))
            return []

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SqlSafetyError):
                run_safe_sql(
                    "DELETE FROM t WHERE pt = '20260527'",
                    executor,
                    audit_path=Path(tmp) / "audit.jsonl",
                )

        self.assertEqual(calls, [])

    def test_run_safe_sql_writes_audit_log_for_allowed_query(self):
        def executor(sql, limit):
            return [{"row_cnt": 3}]

        with tempfile.TemporaryDirectory() as tmp:
            audit_path = Path(tmp) / "audit.jsonl"
            rows = run_safe_sql(
                "SELECT COUNT(1) AS row_cnt FROM t WHERE pt = '20260527'",
                executor,
                audit_path=audit_path,
                limit=10,
            )
            entries = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(rows, [{"row_cnt": 3}])
        self.assertEqual(entries[0]["status"], "ok")
        self.assertEqual(entries[0]["row_count"], 1)
        self.assertEqual(entries[0]["limit"], 10)
        self.assertNotIn("ALIBABA_CLOUD_ACCESS_KEY_SECRET", json.dumps(entries[0]))

    def test_run_safe_sql_passes_optional_hints(self):
        calls = []

        def executor(sql, limit, hints=None):
            calls.append((sql, limit, hints))
            return [{"ok": 1}]

        with tempfile.TemporaryDirectory() as tmp:
            rows = run_safe_sql(
                "SELECT table_name FROM SYSTEM_CATALOG.INFORMATION_SCHEMA.tables LIMIT 1",
                executor,
                audit_path=Path(tmp) / "audit.jsonl",
                require_partition=False,
                limit=1,
                hints={"odps.namespace.schema": "true"},
            )

        self.assertEqual(rows, [{"ok": 1}])
        self.assertEqual(calls[0][2], {"odps.namespace.schema": "true"})

    def test_count_and_partition_sql_builders_validate_table_names(self):
        self.assertEqual(
            build_count_sql("dws_mj_logistics_trans_fee_assess_dtl", "20260527"),
            "SELECT COUNT(1) AS row_cnt FROM dws_mj_logistics_trans_fee_assess_dtl WHERE pt = '20260527'",
        )
        self.assertEqual(
            build_partitions_sql("project_a.table_b"),
            "SHOW PARTITIONS project_a.table_b",
        )

        with self.assertRaises(ValueError):
            build_count_sql("safe_table; DROP TABLE x", "20260527")


if __name__ == "__main__":
    unittest.main()
