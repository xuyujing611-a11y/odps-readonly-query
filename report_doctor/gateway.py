from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .dataworks_logic import resolve_table_logic
from .safe_runner import build_count_sql, build_partitions_sql, run_safe_sql
from .safe_runner import validate_table_name


class GatewayError(ValueError):
    """Raised for malformed local gateway requests."""


_PARTITION_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(\d{8})$")
_CATALOG_HINTS = {
    "odps.namespace.schema": "true",
    "odps.sql.allow.namespace.schema": "true",
}
_CATALOG_MAX_LIMIT = 5000


def _validate_limit(value: object, *, default: int = 200) -> int:
    if value is None:
        return default
    limit = int(value)
    if limit < 1 or limit > _CATALOG_MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {_CATALOG_MAX_LIMIT}, got: {value}")
    return limit


def _split_table_ref(table: str) -> tuple[str | None, str]:
    table = validate_table_name(table.strip())
    parts = table.split(".")
    if len(parts) == 1:
        return None, parts[0]
    return parts[0], parts[1]


def _catalog_where(table_ref: str) -> str:
    catalog, table_name = _split_table_ref(table_ref)
    clauses = [f"table_name = '{table_name}'"]
    if catalog:
        clauses.insert(0, f"table_catalog = '{catalog}'")
    return " AND ".join(clauses)


def build_catalog_sql(template: str, table: str, *, limit: int = 200) -> str:
    template = template.strip().lower()
    where = _catalog_where(table)
    limit = _validate_limit(limit)

    if template in {"table", "logic"}:
        return "\n".join(
            [
                "SELECT table_catalog, table_schema, table_name, table_type, is_partitioned,",
                "       owner_name, create_time, last_modified_time, last_access_time, data_length,",
                "       table_comment, lifecycle, lifecycle_enabled, storage_tier, cluster_type,",
                "       number_buckets, view_original_text, has_primary_key, is_transactional,",
                "       is_delta_table, table_storage, table_format",
                "FROM SYSTEM_CATALOG.INFORMATION_SCHEMA.tables",
                f"WHERE {where}",
                "ORDER BY table_catalog, table_name",
                f"LIMIT {limit}",
            ]
        )

    if template == "columns":
        return "\n".join(
            [
                "SELECT table_catalog, table_schema, table_name, ordinal_position, column_name,",
                "       data_type, is_nullable, is_partition_key, is_primary_key, column_comment",
                "FROM SYSTEM_CATALOG.INFORMATION_SCHEMA.columns",
                f"WHERE {where}",
                "ORDER BY table_catalog, table_name, ordinal_position",
                f"LIMIT {limit}",
            ]
        )

    if template == "partitions":
        return "\n".join(
            [
                "SELECT table_catalog, table_schema, table_name, partition_name, create_time,",
                "       last_modified_time, last_access_time, data_length, storage_tier,",
                "       cluster_type, number_buckets, lifecycle_enabled",
                "FROM SYSTEM_CATALOG.INFORMATION_SCHEMA.partitions",
                f"WHERE {where}",
                "ORDER BY table_catalog, table_name, partition_name",
                f"LIMIT {limit}",
            ]
        )

    raise GatewayError(f"Unsupported catalog template: {template}")


def build_gateway_sql(payload: dict[str, Any]) -> str:
    action = str(payload.get("action", "")).strip().lower()
    if action == "count":
        table = str(payload.get("table", "")).strip()
        bizdate = str(payload.get("bizdate", "")).strip()
        partition_col = str(payload.get("partition_col", "pt")).strip()
        return build_count_sql(table, bizdate, partition_col=partition_col)

    if action == "partitions":
        table = str(payload.get("table", "")).strip()
        return build_partitions_sql(table)

    if action == "latest-partition":
        table = str(payload.get("table", "")).strip()
        return build_partitions_sql(table)

    if action == "catalog":
        template = str(payload.get("template", "")).strip()
        table = str(payload.get("table", "")).strip()
        limit = _validate_limit(payload.get("limit"))
        return build_catalog_sql(template, table, limit=limit)

    if action == "table-logic":
        table = str(payload.get("table", "")).strip()
        limit = _validate_limit(payload.get("limit"), default=20)
        return build_catalog_sql("logic", table, limit=limit)

    if action == "sql":
        sql = str(payload.get("sql", "")).strip()
        if not sql:
            raise GatewayError("SQL payload is empty.")
        return sql

    raise GatewayError(f"Unsupported gateway action: {action}")


def action_requires_partition(payload: dict[str, Any]) -> bool:
    action = str(payload.get("action", "")).strip().lower()
    return action not in {"partitions", "latest-partition", "catalog", "table-logic"}


def action_sql_hints(payload: dict[str, Any]) -> dict[str, str] | None:
    action = str(payload.get("action", "")).strip().lower()
    if action in {"catalog", "table-logic"}:
        return dict(_CATALOG_HINTS)
    return None


def _iter_partition_tokens(rows: list[dict[str, object]]):
    for row in rows:
        for value in row.values():
            items = value if isinstance(value, list) else [value]
            for item in items:
                yield str(item)


def extract_latest_partition(rows: list[dict[str, object]], *, partition_col: str = "pt") -> dict[str, object]:
    values: list[str] = []
    for token in _iter_partition_tokens(rows):
        match = _PARTITION_RE.fullmatch(token)
        if match and match.group(1) == partition_col:
            values.append(match.group(2))

    if not values:
        raise GatewayError(f"No {partition_col}=yyyymmdd partition found.")

    latest_value = max(values)
    return {
        "partition_col": partition_col,
        "partition_value": latest_value,
        "partition": f"{partition_col}={latest_value}",
        "partition_count": len(rows),
    }


def handle_gateway_payload(
    payload: dict[str, Any],
    executor,
    *,
    audit_path: Path,
    dataworks_client=None,
    odps_project: str | None = None,
) -> list[dict[str, object]]:
    sql = build_gateway_sql(payload)
    limit_value = payload.get("limit")
    action = str(payload.get("action", "")).strip().lower()
    if action == "latest-partition":
        limit = int(limit_value) if limit_value is not None else 10000
    elif action == "table-logic":
        limit = int(limit_value) if limit_value is not None else 20
    else:
        limit = int(limit_value) if limit_value is not None else 200

    catalog_error = None
    try:
        rows = run_safe_sql(
            sql,
            executor,
            audit_path=audit_path,
            require_partition=action_requires_partition(payload),
            limit=limit,
            hints=action_sql_hints(payload),
        )
    except Exception as exc:
        if action != "table-logic":
            raise
        rows = []
        catalog_error = str(exc)
    if action == "latest-partition":
        partition_col = str(payload.get("partition_col", "pt")).strip()
        return [extract_latest_partition(rows, partition_col=partition_col)]
    if action == "table-logic":
        table = str(payload.get("table", "")).strip()
        return resolve_table_logic(
            table,
            catalog_rows=rows,
            dataworks_client=dataworks_client,
            odps_project=odps_project,
            catalog_error=catalog_error,
        )
    return rows
