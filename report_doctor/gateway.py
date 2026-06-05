from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .dataworks_logic import resolve_table_logic
from .safe_runner import build_count_sql, build_partitions_sql, run_safe_sql
from .safe_runner import validate_bizdate, validate_table_name


class GatewayError(ValueError):
    """Raised for malformed local gateway requests."""


_PARTITION_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(\d{8})$")
_CATALOG_HINTS = {
    "odps.namespace.schema": "true",
    "odps.sql.allow.namespace.schema": "true",
}
_CATALOG_MAX_LIMIT = 5000
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_limit(value: object, *, default: int = 200) -> int:
    if value is None:
        return default
    limit = int(value)
    if limit < 1 or limit > _CATALOG_MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {_CATALOG_MAX_LIMIT}, got: {value}")
    return limit


def _validate_identifier(value: str, *, label: str = "identifier") -> str:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"Unsafe {label}: {value}")
    return value


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


def build_max_pt_sql(table: str) -> str:
    table = validate_table_name(table.strip())
    return f"SELECT MAX_PT('{table}') AS partition_value"


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
        method = str(payload.get("method", "max-pt")).strip().lower()
        if method == "show-partitions":
            return build_partitions_sql(table)
        if method != "max-pt":
            raise GatewayError(f"Unsupported latest-partition method: {method}")
        return build_max_pt_sql(table)

    if action == "quick-count":
        table = str(payload.get("table", "")).strip()
        bizdate = str(payload.get("bizdate", "latest")).strip().lower()
        if bizdate == "latest":
            return build_max_pt_sql(table)
        partition_col = str(payload.get("partition_col", "pt")).strip()
        return build_count_sql(table, bizdate, partition_col=partition_col)

    if action == "sample":
        table = validate_table_name(str(payload.get("table", "")).strip())
        bizdate = validate_bizdate(str(payload.get("bizdate", "")).strip())
        partition_col = _validate_identifier(str(payload.get("partition_col", "pt")).strip(), label="partition column")
        limit = _validate_limit(payload.get("limit"), default=20)
        return f"SELECT * FROM {table} WHERE {partition_col} = '{bizdate}' LIMIT {limit}"

    if action == "field-profile":
        table = validate_table_name(str(payload.get("table", "")).strip())
        field = _validate_identifier(str(payload.get("field", "")).strip(), label="field")
        bizdate = validate_bizdate(str(payload.get("bizdate", "")).strip())
        partition_col = _validate_identifier(str(payload.get("partition_col", "pt")).strip(), label="partition column")
        limit = _validate_limit(payload.get("limit"), default=50)
        return (
            f"SELECT {field} AS value, COUNT(1) AS row_cnt "
            f"FROM {table} WHERE {partition_col} = '{bizdate}' "
            f"GROUP BY {field} ORDER BY row_cnt DESC LIMIT {limit}"
        )

    if action == "compare-tables":
        left_table = validate_table_name(str(payload.get("left_table", "")).strip())
        right_table = validate_table_name(str(payload.get("right_table", "")).strip())
        key = _validate_identifier(str(payload.get("key", "")).strip(), label="key")
        metric = _validate_identifier(str(payload.get("metric", "")).strip(), label="metric")
        bizdate = validate_bizdate(str(payload.get("bizdate", "")).strip())
        partition_col = _validate_identifier(str(payload.get("partition_col", "pt")).strip(), label="partition column")
        limit = _validate_limit(payload.get("limit"), default=100)
        return "\n".join(
            [
                "WITH left_side AS (",
                f"  SELECT {key} AS join_key, COUNT(1) AS left_cnt, SUM({metric}) AS left_amount",
                f"  FROM {left_table}",
                f"  WHERE {partition_col} = '{bizdate}'",
                f"  GROUP BY {key}",
                "), right_side AS (",
                f"  SELECT {key} AS join_key, COUNT(1) AS right_cnt, SUM({metric}) AS right_amount",
                f"  FROM {right_table}",
                f"  WHERE {partition_col} = '{bizdate}'",
                f"  GROUP BY {key}",
                ")",
                "SELECT COALESCE(left_side.join_key, right_side.join_key) AS join_key,",
                "       left_cnt, right_cnt, left_amount, right_amount,",
                "       NVL(left_cnt, 0) - NVL(right_cnt, 0) AS cnt_diff,",
                "       NVL(left_amount, 0) - NVL(right_amount, 0) AS amount_diff",
                "FROM left_side",
                "FULL OUTER JOIN right_side ON left_side.join_key = right_side.join_key",
                "WHERE NVL(left_cnt, 0) <> NVL(right_cnt, 0)",
                "   OR NVL(left_amount, 0) <> NVL(right_amount, 0)",
                f"LIMIT {limit}",
            ]
        )

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


def _partition_tokens_by_row(rows: list[dict[str, object]], *, partition_col: str) -> list[list[str]]:
    rows_tokens: list[list[str]] = []
    for row in rows:
        row_tokens: list[str] = []
        for value in row.values():
            items = value if isinstance(value, list) else [value]
            for item in items:
                token = str(item)
                match = _PARTITION_RE.fullmatch(token)
                if match and match.group(1) == partition_col:
                    row_tokens.append(match.group(2))
        if row_tokens:
            rows_tokens.append(row_tokens)
    return rows_tokens


def _latest_from_values(values: list[str], *, partition_col: str, partition_count: int) -> dict[str, object]:
    if not values:
        raise GatewayError(f"No {partition_col}=yyyymmdd partition found.")

    latest_value = max(values)
    return {
        "partition_col": partition_col,
        "partition_value": latest_value,
        "partition": f"{partition_col}={latest_value}",
        "partition_count": partition_count,
    }


def extract_latest_partition_from_max_pt(
    rows: list[dict[str, object]],
    *,
    partition_col: str = "pt",
) -> dict[str, object]:
    values: list[str] = []
    for row in rows:
        for raw_value in row.values():
            if raw_value is None:
                continue
            value = str(raw_value).strip()
            token_match = _PARTITION_RE.fullmatch(value)
            if token_match:
                if token_match.group(1) == partition_col:
                    values.append(token_match.group(2))
                continue
            if re.fullmatch(r"\d{8}", value):
                values.append(value)
    result = _latest_from_values(values, partition_col=partition_col, partition_count=len(rows))
    result["method"] = "max_pt"
    return result


def _ambiguous_latest_partition(
    rows_tokens: list[list[str]],
    *,
    partition_col: str,
    partition_count: int,
) -> dict[str, object]:
    max_width = max(len(tokens) for tokens in rows_tokens)
    candidates: list[dict[str, object]] = []
    for token_index in range(max_width):
        values = [tokens[token_index] for tokens in rows_tokens if token_index < len(tokens)]
        if not values:
            continue
        latest_value = max(values)
        candidates.append(
            {
                "token_index": token_index,
                "partition_value": latest_value,
                "partition": f"{partition_col}={latest_value}",
            }
        )

    return {
        "status": "ambiguous",
        "partition_col": partition_col,
        "partition_count": partition_count,
        "candidates_by_token_index": candidates,
        "message": (
            f"SHOW PARTITIONS returned ambiguous multiple {partition_col}=yyyymmdd tokens per row; "
            "latest-partition will not guess which token is queryable. Use catalog columns/partitions "
            "to verify the real partition key, or rerun with --token-index after human confirmation."
        ),
    }


def extract_latest_partition(
    rows: list[dict[str, object]],
    *,
    partition_col: str = "pt",
    token_index: int | None = None,
) -> dict[str, object]:
    rows_tokens = _partition_tokens_by_row(rows, partition_col=partition_col)
    if not rows_tokens:
        raise GatewayError(f"No {partition_col}=yyyymmdd partition found.")

    if token_index is not None:
        if token_index < 0:
            raise GatewayError(f"token_index must be >= 0, got: {token_index}")
        values = [tokens[token_index] for tokens in rows_tokens if token_index < len(tokens)]
        result = _latest_from_values(values, partition_col=partition_col, partition_count=len(rows))
        result["token_index"] = token_index
        return result

    if any(len(tokens) > 1 for tokens in rows_tokens):
        return _ambiguous_latest_partition(rows_tokens, partition_col=partition_col, partition_count=len(rows))

    return _latest_from_values(
        [tokens[0] for tokens in rows_tokens],
        partition_col=partition_col,
        partition_count=len(rows),
    )


def _parse_token_index(value: object) -> int | None:
    if value is None or value == "":
        return None
    token_index = int(value)
    if token_index < 0:
        raise GatewayError(f"token_index must be >= 0, got: {value}")
    return token_index


def _run_sql(
    sql: str,
    executor,
    *,
    audit_path: Path,
    require_partition: bool,
    limit: int | None,
    hints: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    return run_safe_sql(
        sql,
        executor,
        audit_path=audit_path,
        require_partition=require_partition,
        limit=limit,
        hints=hints,
    )


def _run_catalog_template(
    template: str,
    table: str,
    executor,
    *,
    audit_path: Path,
    limit: int,
) -> dict[str, object]:
    try:
        rows = _run_sql(
            build_catalog_sql(template, table, limit=limit),
            executor,
            audit_path=audit_path,
            require_partition=False,
            limit=limit,
            hints=_CATALOG_HINTS,
        )
    except Exception as exc:
        return {"status": "error", "error": str(exc), "rows": []}
    return {"status": "ok", "rows": rows}


def _truthy_catalog_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _extract_partition_keys(column_rows: list[dict[str, object]]) -> list[str]:
    keys: list[str] = []
    for row in column_rows:
        if _truthy_catalog_value(row.get("is_partition_key") or row.get("IS_PARTITION_KEY")):
            name = row.get("column_name") or row.get("COLUMN_NAME")
            if name is not None:
                keys.append(str(name))
    return keys


def _handle_inspect_table(payload: dict[str, Any], executor, *, audit_path: Path) -> list[dict[str, object]]:
    table = validate_table_name(str(payload.get("table", "")).strip())
    catalog_limit = _validate_limit(payload.get("catalog_limit"), default=500)
    partition_limit = _validate_limit(payload.get("partition_limit"), default=10000)
    partition_col = str(payload.get("partition_col", "pt")).strip()
    token_index = _parse_token_index(payload.get("token_index"))

    table_result = _run_catalog_template("table", table, executor, audit_path=audit_path, limit=1)
    columns_result = _run_catalog_template("columns", table, executor, audit_path=audit_path, limit=catalog_limit)
    partitions_result = _run_catalog_template("partitions", table, executor, audit_path=audit_path, limit=catalog_limit)

    try:
        latest_partition = _resolve_latest_partition(
            table,
            executor,
            audit_path=audit_path,
            partition_col=partition_col,
            token_index=token_index,
            partition_limit=partition_limit,
        )
    except Exception as exc:
        latest_partition = {"status": "error", "error": str(exc)}

    statuses = [table_result["status"], columns_result["status"], partitions_result["status"]]
    latest_status = latest_partition.get("status")
    latest_ok = latest_status not in {"error"}
    status = "ok" if latest_ok or any(item == "ok" for item in statuses) else "error"
    return [
        {
            "status": status,
            "table": table,
            "catalog_table_status": table_result["status"],
            "catalog_table_error": table_result.get("error"),
            "catalog_table": table_result["rows"],
            "catalog_columns_status": columns_result["status"],
            "catalog_columns_error": columns_result.get("error"),
            "partition_keys": _extract_partition_keys(columns_result["rows"]),
            "columns": columns_result["rows"],
            "catalog_partitions_status": partitions_result["status"],
            "catalog_partitions_error": partitions_result.get("error"),
            "catalog_partitions_sample": partitions_result["rows"],
            "latest_partition": latest_partition,
        }
    ]


def _resolve_latest_partition(
    table: str,
    executor,
    *,
    audit_path: Path,
    partition_col: str,
    token_index: int | None = None,
    partition_limit: int = 10000,
    method: str = "max-pt",
) -> dict[str, object]:
    if method not in {"max-pt", "show-partitions"}:
        raise GatewayError(f"Unsupported latest-partition method: {method}")

    if method == "max-pt":
        try:
            rows = _run_sql(
                build_max_pt_sql(table),
                executor,
                audit_path=audit_path,
                require_partition=False,
                limit=1,
            )
            return extract_latest_partition_from_max_pt(rows, partition_col=partition_col)
        except Exception as max_pt_exc:
            fallback_error = str(max_pt_exc)
    else:
        fallback_error = ""

    partition_rows = _run_sql(
        build_partitions_sql(table),
        executor,
        audit_path=audit_path,
        require_partition=False,
        limit=partition_limit,
    )
    latest = extract_latest_partition(
        partition_rows,
        partition_col=partition_col,
        token_index=token_index,
    )
    latest["method"] = "show_partitions"
    if fallback_error:
        latest["fallback_from"] = "max_pt"
        latest["fallback_error"] = fallback_error
    return latest


def _handle_quick_count(payload: dict[str, Any], executor, *, audit_path: Path) -> list[dict[str, object]]:
    table = validate_table_name(str(payload.get("table", "")).strip())
    partition_col = str(payload.get("partition_col", "pt")).strip()
    bizdate = str(payload.get("bizdate", "latest")).strip()
    token_index = _parse_token_index(payload.get("token_index"))
    method = str(payload.get("method", "max-pt")).strip().lower()

    latest_partition: dict[str, object] | None = None
    if bizdate.lower() == "latest":
        latest_partition = _resolve_latest_partition(
            table,
            executor,
            audit_path=audit_path,
            partition_col=partition_col,
            token_index=token_index,
            method=method,
        )
        if latest_partition.get("status") == "ambiguous":
            return [{"action": "quick-count", "table": table, **latest_partition}]
        bizdate = str(latest_partition["partition_value"])

    count_rows = _run_sql(
        build_count_sql(table, bizdate, partition_col=partition_col),
        executor,
        audit_path=audit_path,
        require_partition=True,
        limit=1,
    )
    row_cnt = count_rows[0].get("row_cnt") if count_rows else None
    return [
        {
            "status": "ok",
            "action": "quick-count",
            "table": table,
            "partition_col": partition_col,
            "partition_value": bizdate,
            "partition": f"{partition_col}={bizdate}",
            "row_cnt": row_cnt,
            "latest_partition": latest_partition,
        }
    ]


def handle_gateway_payload(
    payload: dict[str, Any],
    executor,
    *,
    audit_path: Path,
    dataworks_client=None,
    odps_project: str | None = None,
) -> list[dict[str, object]]:
    action = str(payload.get("action", "")).strip().lower()
    if action == "inspect-table":
        return _handle_inspect_table(payload, executor, audit_path=audit_path)
    if action == "quick-count":
        return _handle_quick_count(payload, executor, audit_path=audit_path)

    sql = build_gateway_sql(payload)
    limit_value = payload.get("limit")
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
        token_index = _parse_token_index(payload.get("token_index"))
        method = str(payload.get("method", "max-pt")).strip().lower()
        if method == "show-partitions":
            latest = extract_latest_partition(rows, partition_col=partition_col, token_index=token_index)
            latest["method"] = "show_partitions"
            return [latest]
        return [extract_latest_partition_from_max_pt(rows, partition_col=partition_col)]
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
