from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .sql_safety import assert_read_only_sql


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT_PATH = PROJECT_ROOT.parent / "odps_query_audit.jsonl"
_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$")
_BIZDATE_RE = re.compile(r"^[0-9]{8}$")


def validate_table_name(table: str) -> str:
    if not _TABLE_NAME_RE.fullmatch(table):
        raise ValueError(f"Unsafe table name: {table}")
    return table


def validate_bizdate(bizdate: str) -> str:
    if not _BIZDATE_RE.fullmatch(bizdate):
        raise ValueError(f"bizdate must be yyyymmdd, got: {bizdate}")
    return bizdate


def build_count_sql(table: str, bizdate: str, *, partition_col: str = "pt") -> str:
    table = validate_table_name(table)
    partition_col = validate_table_name(partition_col)
    bizdate = validate_bizdate(bizdate)
    return f"SELECT COUNT(1) AS row_cnt FROM {table} WHERE {partition_col} = '{bizdate}'"


def build_partitions_sql(table: str) -> str:
    return f"SHOW PARTITIONS {validate_table_name(table)}"


def _preview(sql: str) -> str:
    compact = " ".join(sql.split())
    return compact[:500]


def append_audit_log(
    *,
    audit_path: Path,
    sql: str,
    status: str,
    row_count: int | None = None,
    limit: int | None = None,
    error: str | None = None,
) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "sql_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
        "sql_preview": _preview(sql),
        "row_count": row_count,
        "limit": limit,
        "error": error,
    }
    line = json.dumps(entry, ensure_ascii=False, default=str)
    try:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("a", encoding="utf-8") as file:
            file.write(line + "\n")
    except PermissionError:
        env = {
            **os.environ,
            "CODEX_ODPS_AUDIT_PATH": str(audit_path),
            "CODEX_ODPS_AUDIT_LINE": line,
        }
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "$path = $env:CODEX_ODPS_AUDIT_PATH; "
                    "$line = $env:CODEX_ODPS_AUDIT_LINE; "
                    "$dir = Split-Path -Parent $path; "
                    "if (-not (Test-Path -LiteralPath $dir)) { "
                    "New-Item -ItemType Directory -Force -Path $dir | Out-Null "
                    "} "
                    "Add-Content -LiteralPath $path -Value $line -Encoding UTF8"
                ),
            ],
            env=env,
            check=True,
        )


def run_safe_sql(
    sql: str,
    executor: Callable[..., list[dict[str, object]]],
    *,
    audit_path: Path = DEFAULT_AUDIT_PATH,
    require_partition: bool = True,
    limit: int | None = None,
    hints: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    assert_read_only_sql(sql, require_partition=require_partition)
    try:
        if hints:
            rows = executor(sql, limit, hints=hints)
        else:
            rows = executor(sql, limit)
    except Exception as exc:
        append_audit_log(audit_path=audit_path, sql=sql, status="error", limit=limit, error=str(exc))
        raise

    append_audit_log(audit_path=audit_path, sql=sql, status="ok", row_count=len(rows), limit=limit)
    return rows
