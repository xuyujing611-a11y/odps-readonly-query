from __future__ import annotations

import re


class SqlSafetyError(ValueError):
    """Raised when SQL is not safe for this read-only diagnostic runner."""


_MUTATING_KEYWORDS = (
    "alter",
    "create",
    "delete",
    "drop",
    "insert",
    "merge",
    "overwrite",
    "truncate",
    "update",
)
_READ_ONLY_START = re.compile(r"^\s*(select|with|show|desc|describe)\b", re.IGNORECASE | re.DOTALL)
_PARTITION_FILTER = re.compile(r"\b(pt|ds|bizdate)\s*(=|in\b|between\b)", re.IGNORECASE)


def _strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n\r]*", " ", sql)


def _strip_string_literals(sql: str) -> str:
    return re.sub(r"'(?:''|[^'])*'", "''", sql)


def _has_multiple_statements(sql: str) -> bool:
    stripped = sql.strip()
    if not stripped:
        return False
    without_one_trailing = stripped[:-1] if stripped.endswith(";") else stripped
    return ";" in without_one_trailing


def assert_read_only_sql(sql: str, *, require_partition: bool = True) -> None:
    normalized = _strip_string_literals(_strip_sql_comments(sql))
    if not normalized.strip():
        raise SqlSafetyError("SQL is empty.")

    if _has_multiple_statements(normalized):
        raise SqlSafetyError("Only one SQL statement is allowed.")

    if not _READ_ONLY_START.search(normalized):
        raise SqlSafetyError("Only SELECT/WITH/SHOW/DESC read-only SQL is allowed.")

    lowered = normalized.lower()
    for keyword in _MUTATING_KEYWORDS:
        if re.search(rf"\b{keyword}\b", lowered):
            raise SqlSafetyError(f"Mutating keyword is not allowed: {keyword}")

    starts_with_query = re.search(r"^\s*(select|with)\b", normalized, re.IGNORECASE)
    if require_partition and starts_with_query and not _PARTITION_FILTER.search(normalized):
        raise SqlSafetyError(
            "Partition filter is required for SELECT/WITH diagnostics. "
            "Add a pt/ds/bizdate filter or pass --no-require-partition for controlled small queries."
        )

