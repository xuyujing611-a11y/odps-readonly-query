import tempfile
import unittest
from pathlib import Path

from report_doctor.templates import render_sql_template


class TemplateTests(unittest.TestCase):
    def test_renders_bizdate_and_named_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            sql_path = Path(tmp) / "check.sql"
            sql_path.write_text(
                "SELECT * FROM ${table_name} WHERE pt = '${bizdate}' AND city = '${city}'",
                encoding="utf-8",
            )

            rendered = render_sql_template(
                sql_path,
                {
                    "bizdate": "20260526",
                    "table_name": "ads_table",
                    "city": "杭州",
                },
            )

        self.assertEqual(
            rendered,
            "SELECT * FROM ads_table WHERE pt = '20260526' AND city = '杭州'",
        )

    def test_reports_missing_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            sql_path = Path(tmp) / "check.sql"
            sql_path.write_text("SELECT * FROM t WHERE pt = '${bizdate}'", encoding="utf-8")

            with self.assertRaisesRegex(KeyError, "bizdate"):
                render_sql_template(sql_path, {})


if __name__ == "__main__":
    unittest.main()
