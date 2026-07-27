import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from report_doctor.gateway_server import GatewayState


class GatewayServerTests(unittest.TestCase):
    def test_gateway_state_passes_sql_timeout_to_odps_executor(self):
        seen = {}

        def fake_execute_sql_to_dicts(odps, sql, *, limit=None, hints=None, timeout_seconds=None):
            seen["odps"] = odps
            seen["sql"] = sql
            seen["limit"] = limit
            seen["hints"] = hints
            seen["timeout_seconds"] = timeout_seconds
            return [{"ok": 1}]

        with tempfile.TemporaryDirectory() as tmp:
            state = GatewayState(
                odps="fake-odps",
                token="token",
                audit_path=Path(tmp) / "audit.jsonl",
                odps_project="yh_doc_cdm",
                sql_timeout_seconds=300,
            )

            with patch("report_doctor.gateway_server.execute_sql_to_dicts", fake_execute_sql_to_dicts):
                rows = state.execute(
                    "select * from t where pt = '20260527'",
                    5,
                    hints={"odps.namespace.schema": "true"},
                )

        self.assertEqual(rows, [{"ok": 1}])
        self.assertEqual(seen["odps"], "fake-odps")
        self.assertEqual(seen["sql"], "select * from t where pt = '20260527'")
        self.assertEqual(seen["limit"], 5)
        self.assertEqual(seen["hints"], {"odps.namespace.schema": "true"})
        self.assertEqual(seen["timeout_seconds"], 300)


if __name__ == "__main__":
    unittest.main()
