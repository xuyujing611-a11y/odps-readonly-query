import unittest

from report_doctor.sql_safety import SqlSafetyError, assert_read_only_sql


class SqlSafetyTests(unittest.TestCase):
    def test_allows_select_and_with_queries(self):
        assert_read_only_sql("SELECT COUNT(*) FROM some_table WHERE pt = '20260526'")
        assert_read_only_sql(
            "WITH t AS (SELECT * FROM some_table WHERE pt = '20260526') SELECT * FROM t"
        )

    def test_rejects_mutating_keywords(self):
        for sql in [
            "INSERT OVERWRITE TABLE t SELECT 1",
            "DELETE FROM t WHERE pt = '20260526'",
            "DROP TABLE t",
            "ALTER TABLE t ADD COLUMNS x STRING",
        ]:
            with self.subTest(sql=sql):
                with self.assertRaises(SqlSafetyError):
                    assert_read_only_sql(sql)

    def test_rejects_multiple_statements(self):
        with self.assertRaises(SqlSafetyError):
            assert_read_only_sql("SELECT 1; SELECT 2")

    def test_requires_partition_or_explicit_override(self):
        with self.assertRaises(SqlSafetyError):
            assert_read_only_sql("SELECT * FROM big_table")

        assert_read_only_sql("SELECT * FROM big_table", require_partition=False)


if __name__ == "__main__":
    unittest.main()
