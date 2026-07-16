from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
_READ_ONLY_DATAWORKS_ACTIONS = {
    "batch-schedule-info",
    "schedule-graph",
    "recent-instances",
    "instance-log-summary",
    "batch-freshness-check",
}
_BEIJING_TZ = timezone(timedelta(hours=8))


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
    if action == "sql" and "require_partition" in payload:
        return bool(payload.get("require_partition"))
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
    partition_limit = _validate_limit(payload.get("partition_limit"), default=5000)
    include_partition_sample = bool(payload.get("include_partition_sample", False))
    partition_col = str(payload.get("partition_col", "pt")).strip()
    token_index = _parse_token_index(payload.get("token_index"))

    table_result = _run_catalog_template("table", table, executor, audit_path=audit_path, limit=1)
    columns_result = _run_catalog_template("columns", table, executor, audit_path=audit_path, limit=catalog_limit)
    if include_partition_sample:
        partitions_result = _run_catalog_template("partitions", table, executor, audit_path=audit_path, limit=catalog_limit)
    else:
        partitions_result = {"status": "skipped", "rows": [], "error": None}

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


def _validate_tables(value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        raise GatewayError("tables must be a non-empty list.")
    tables: list[str] = []
    for item in value[:100]:
        table = validate_table_name(str(item).strip())
        if table not in tables:
            tables.append(table)
    return tables


def _first_value(row: dict[str, Any], *keys: str) -> Any:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value is not None:
            return value
    return None


def _drop_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None and value != ""}


def _permission_status_from_error(error: str) -> str:
    text = error.lower()
    if any(token in text for token in ("permission", "privilege", "not authorized", "unauthorized", "access denied", "no privilege", "forbidden")):
        return "denied"
    return "error"


def _dataworks_unavailable_row(action: str, **kwargs: Any) -> dict[str, object]:
    return {
        "status": "unavailable",
        "source": "dataworks_openapi",
        "action": action,
        "permission_checked": False,
        "permission_status": "unverified",
        "message": "DataWorks read-only client is not configured or SDK is not installed.",
        **_drop_none(kwargs),
    }


def _dataworks_error_row(action: str, *, exc: Exception, **kwargs: Any) -> dict[str, object]:
    error = str(exc)
    return {
        "status": "unavailable",
        "source": "dataworks_openapi",
        "action": action,
        "permission_checked": True,
        "permission_status": _permission_status_from_error(error),
        "error": error if len(error) <= 500 else error[:497] + "...",
        **_drop_none(kwargs),
    }


def _parse_cron_field_values(field: object, *, min_value: int, max_value: int) -> list[int] | None:
    text = str(field or "").strip()
    if not text or text in {"?", "*"}:
        return None
    values: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        base = part
        if "/" in part:
            base, step_text = part.split("/", 1)
            step = int(step_text)
            if step < 1:
                return None
        if base == "*":
            start, end = min_value, max_value
        elif "-" in base:
            start_text, end_text = base.split("-", 1)
            start, end = int(start_text), int(end_text)
        else:
            start = end = int(base)
        if start < min_value or end > max_value or start > end:
            return None
        values.update(range(start, end + 1, step))
    return sorted(values)


def _cron_schedule_summary(cron_express: object) -> dict[str, object]:
    text = str(cron_express or "").strip()
    parts = text.split()
    if len(parts) < 3:
        return {}
    try:
        minutes = _parse_cron_field_values(parts[1], min_value=0, max_value=59)
        hours = _parse_cron_field_values(parts[2], min_value=0, max_value=23)
    except (TypeError, ValueError):
        return {"cron_parse_status": "unsupported"}
    if not minutes or not hours:
        return {"cron_parse_status": "unsupported"}
    fire_times = [f"{hour:02d}:{minute:02d}" for hour in hours for minute in minutes]
    return {
        "cron_parse_status": "ok",
        "cron_fire_times": fire_times,
        "cron_fire_count_per_day": len(fire_times),
        "cron_description": f"Daily at {', '.join(fire_times)} (parsed from raw Quartz cron hour/minute fields).",
    }


def _enrich_schedule_item(row: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(row)
    cron = _first_value(enriched, "cron_express", "CronExpress")
    if cron:
        enriched.update(_cron_schedule_summary(cron))
    return enriched


def _format_epoch_ms_beijing(value: object) -> str | None:
    if isinstance(value, bool) or value in {None, ""}:
        return None
    try:
        epoch_ms = int(value)
    except (TypeError, ValueError):
        return None
    # DataWorks instance APIs return millisecond epoch values.
    if epoch_ms < 10_000_000_000:
        return None
    return datetime.fromtimestamp(epoch_ms / 1000, _BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _enrich_instance_row(row: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(row)
    for key in (
        "Bizdate",
        "CycTime",
        "CreateTime",
        "BeginWaitResTime",
        "BeginWaitTimeTime",
        "BeginRunningTime",
        "FinishTime",
        "ModifyTime",
    ):
        formatted = _format_epoch_ms_beijing(enriched.get(key))
        if formatted:
            enriched[f"{key}_beijing"] = formatted
    begin = enriched.get("BeginRunningTime")
    finish = enriched.get("FinishTime")
    if isinstance(begin, int) and isinstance(finish, int) and finish >= begin:
        enriched["duration_seconds"] = round((finish - begin) / 1000, 3)
    return enriched


def _enrich_instance_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_enrich_instance_row(row) if isinstance(row, dict) else row for row in rows]


def _resolve_table_logic_rows(
    table: str,
    *,
    dataworks_client,
    odps_project: str | None,
) -> list[dict[str, Any]]:
    return resolve_table_logic(
        table,
        catalog_rows=[],
        dataworks_client=dataworks_client,
        odps_project=odps_project,
        catalog_error=None,
    )


def _first_node_for_table(
    table: str,
    *,
    dataworks_client,
    odps_project: str | None,
) -> dict[str, Any]:
    for row in _resolve_table_logic_rows(table, dataworks_client=dataworks_client, odps_project=odps_project):
        if isinstance(row, dict) and row.get("node_id"):
            return row
    raise GatewayError(f"No DataWorks node found for table: {table}")


def _compact_schedule_row(row: dict[str, Any], *, include_code_digest: bool) -> dict[str, object]:
    compact = {
        key: row.get(key)
        for key in (
            "table",
            "source",
            "status",
            "lookup_method",
            "project_env",
            "node_id",
            "node_name",
            "file_type",
            "project_id",
            "owner_id",
            "connection",
            "cron_express",
            "matched_output",
        )
        if row.get(key) is not None
    }
    compact.update(_cron_schedule_summary(compact.get("cron_express")))
    compact["permission_checked"] = True
    compact["permission_status"] = "ok" if row.get("status") == "ok" else "unavailable"
    code = row.get("node_code")
    if include_code_digest and isinstance(code, str):
        compact["node_code_length"] = len(code)
        compact["node_code_preview"] = code[:1200]
    return compact


def _handle_batch_schedule_info(
    payload: dict[str, Any],
    *,
    dataworks_client,
    odps_project: str | None,
) -> list[dict[str, object]]:
    tables = _validate_tables(payload.get("tables"))
    include_latest_instances = bool(payload.get("include_latest_instances", True))
    include_code_digest = bool(payload.get("include_code_digest", False))
    bizdate = str(payload.get("bizdate") or "").strip() or None
    if dataworks_client is None:
        return [_dataworks_unavailable_row("batch_schedule_info", table=table) for table in tables]

    rows: list[dict[str, object]] = []
    for table in tables:
        try:
            logic_rows = _resolve_table_logic_rows(table, dataworks_client=dataworks_client, odps_project=odps_project)
            for row in logic_rows:
                if not isinstance(row, dict):
                    continue
                compact = _compact_schedule_row(row, include_code_digest=include_code_digest)
                node_id = _first_value(row, "node_id", "NodeId")
                project_id = _first_value(row, "project_id", "ProjectId")
                if include_latest_instances and node_id and project_id and hasattr(dataworks_client, "list_instances"):
                    try:
                        compact["latest_instances"] = _enrich_instance_rows(
                            dataworks_client.list_instances(
                                node_id=int(node_id),
                                project_id=int(project_id),
                                bizdate=bizdate,
                                page_size=3,
                            )
                        )
                    except Exception as exc:
                        compact["latest_instances"] = [_dataworks_error_row("recent_instances", node_id=int(node_id), exc=exc)]
                rows.append(compact)
        except Exception as exc:
            rows.append(_dataworks_error_row("batch_schedule_info", table=table, exc=exc))
    return rows


def _normalize_graph_direction(value: object) -> str:
    direction = str(value or "both").strip().lower()
    if direction not in {"parents", "children", "both"}:
        raise GatewayError("direction must be parents, children, or both.")
    return direction


def _handle_schedule_graph(
    payload: dict[str, Any],
    *,
    dataworks_client,
    odps_project: str | None,
) -> list[dict[str, object]]:
    if dataworks_client is None:
        return [_dataworks_unavailable_row("schedule_graph")]
    direction = _normalize_graph_direction(payload.get("direction"))
    depth = max(1, min(int(payload.get("depth") or 1), 3))
    table = str(payload.get("table") or "").strip()
    node_id = payload.get("node_id")
    try:
        root_row = _first_node_for_table(validate_table_name(table), dataworks_client=dataworks_client, odps_project=odps_project) if table and node_id in {None, ""} else {}
        root_node_id = int(node_id or root_row["node_id"])
        parents = dataworks_client.get_node_parents(root_node_id) if direction in {"parents", "both"} else []
        children = dataworks_client.get_node_children(root_node_id) if direction in {"children", "both"} else []
        return [
            {
                "status": "ok",
                "source": "dataworks_openapi",
                "action": "schedule_graph",
                "permission_checked": True,
                "permission_status": "ok",
                "table": table,
                "root_node_id": root_node_id,
                "direction": direction,
                "depth": depth,
                "parents": [_enrich_schedule_item(row) for row in parents],
                "children": [_enrich_schedule_item(row) for row in children],
            }
        ]
    except Exception as exc:
        return [_dataworks_error_row("schedule_graph", table=table, node_id=node_id, exc=exc)]


def _handle_recent_instances(
    payload: dict[str, Any],
    *,
    dataworks_client,
    odps_project: str | None,
) -> list[dict[str, object]]:
    if dataworks_client is None:
        return [_dataworks_unavailable_row("recent_instances")]
    table = str(payload.get("table") or "").strip()
    node_id = payload.get("node_id")
    try:
        root_row = _first_node_for_table(validate_table_name(table), dataworks_client=dataworks_client, odps_project=odps_project) if table and node_id in {None, ""} else {}
        resolved_node_id = int(node_id or root_row["node_id"])
        detail = dataworks_client.get_node(resolved_node_id)
        project_id = _first_value(detail, "ProjectId", "project_id") or _first_value(root_row, "project_id", "ProjectId")
        rows = dataworks_client.list_instances(
            node_id=resolved_node_id,
            node_name=str(payload.get("node_name") or "") or None,
            project_id=int(project_id) if project_id else None,
            bizdate=str(payload.get("bizdate") or "") or None,
            begin_bizdate=str(payload.get("begin_bizdate") or "") or None,
            end_bizdate=str(payload.get("end_bizdate") or "") or None,
            status=str(payload.get("status") or "") or None,
            page_size=max(1, min(int(payload.get("limit") or 20), 100)),
        )
        rows = _enrich_instance_rows(rows)
        for row in rows:
            row.setdefault("permission_checked", True)
            row.setdefault("permission_status", "ok")
        return rows
    except Exception as exc:
        return [_dataworks_error_row("recent_instances", table=table, node_id=node_id, exc=exc)]


def _instance_log_error_keywords(log_text: str) -> list[str]:
    lowered = log_text.lower()
    return [
        keyword
        for keyword in ("error", "exception", "failed", "timeout", "killed", "no privilege", "access denied")
        if keyword in lowered
    ]


def _compact_instance_log(log_text: str, *, max_chars: int) -> dict[str, object]:
    lines = log_text.splitlines()
    error_keywords = _instance_log_error_keywords(log_text)
    important = _important_log_lines(lines, include_runtime_markers=not error_keywords)
    if not important:
        important = _non_noise_log_lines(lines[:80])
    excerpt = "\n".join(important)
    if len(excerpt) > max_chars:
        excerpt = excerpt[: max_chars - 3].rstrip() + "..."
    return {
        "log_excerpt": excerpt,
        "log_excerpt_policy": "filtered_noise_removed",
        "log_excerpt_line_count": excerpt.count("\n") + 1 if excerpt else 0,
        "log_filtered_line_count": max(0, len(lines) - len(important)),
        "error_keywords": error_keywords,
        "odps_job_ids": _extract_unique_matches(log_text, r"\b(?:job|instance|task)\s*id[:=]\s*([0-9A-Za-z_:-]+)", limit=20),
        "odps_instance_ids": _extract_unique_matches(log_text, r"\b(?:SKYNET_TASKID|TASKID)=?[:=]\s*([0-9]+)", limit=10),
    }


def _important_log_lines(lines: list[str], *, include_runtime_markers: bool) -> list[str]:
    important: list[str] = []
    for index, line in enumerate(lines):
        lowered = line.lower()
        if _is_noisy_log_line(line):
            continue
        if any(token in lowered for token in ("error", "exception", "failed", "timeout", "killed", "no privilege", "access denied")):
            important.extend(_log_window(lines, index, before=2, after=4))
            continue
        if include_runtime_markers and any(
            token in lowered
            for token in (
                "current task status",
                "summary",
                "job id",
                "instance id",
                "task id",
                "cost",
                "duration",
                "finished",
                "success",
            )
        ):
            important.append(line)
    return _dedupe_preserve_order(_non_noise_log_lines(important))[:120]


def _log_window(lines: list[str], index: int, *, before: int, after: int) -> list[str]:
    start = max(0, index - before)
    end = min(len(lines), index + after + 1)
    return lines[start:end]


def _non_noise_log_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if line.strip() and not _is_noisy_log_line(line)]


def _is_noisy_log_line(line: str) -> bool:
    text = line.strip()
    lowered = text.lower()
    if not text:
        return True
    if text.startswith("SKYNET_") or text.startswith("ALISA_") or text.startswith("SCHE_"):
        return True
    if any(
        token in lowered
        for token in (
            "full command",
            "list of passing environment",
            "/opt/taobao/tbdpapp/odpswrapper/odpswrapper.py",
            "current working dir",
            "-------------------------",
            " create table ",
            " insert overwrite ",
            " set odps.",
        )
    ):
        return True
    return False


def _dedupe_preserve_order(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for line in lines:
        key = line.strip()
        if key and key not in seen:
            seen.add(key)
            deduped.append(line)
    return deduped


def _extract_unique_matches(text: str, pattern: str, *, limit: int) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        value = match.group(1)
        if value not in seen:
            seen.add(value)
            values.append(value)
        if len(values) >= limit:
            break
    return values


def _handle_instance_log_summary(payload: dict[str, Any], *, dataworks_client) -> list[dict[str, object]]:
    if dataworks_client is None:
        return [_dataworks_unavailable_row("instance_log_summary", instance_id=payload.get("instance_id"))]
    instance_id = int(payload.get("instance_id"))
    try:
        log_text = dataworks_client.get_instance_log(instance_id)
        max_chars = max(300, min(int(payload.get("max_log_chars") or 3000), 12000))
        log_summary = _compact_instance_log(log_text, max_chars=max_chars)
        return [
            {
                "status": "ok",
                "source": "dataworks_openapi",
                "action": "instance_log_summary",
                "permission_checked": True,
                "permission_status": "ok",
                "instance_id": instance_id,
                "log_length": len(log_text),
                **log_summary,
            }
        ]
    except Exception as exc:
        return [_dataworks_error_row("instance_log_summary", instance_id=instance_id, exc=exc)]


def _handle_batch_freshness_check(
    payload: dict[str, Any],
    executor,
    *,
    audit_path: Path,
    dataworks_client,
    odps_project: str | None,
) -> list[dict[str, object]]:
    tables = _validate_tables(payload.get("tables"))
    expected_bizdate = str(payload.get("expected_bizdate") or "").strip()
    include_counts = bool(payload.get("include_counts", True))
    schedule_rows = _handle_batch_schedule_info(
        {"tables": tables, "include_latest_instances": True, "bizdate": expected_bizdate},
        dataworks_client=dataworks_client,
        odps_project=odps_project,
    )
    schedule_by_table = {str(row.get("table")): row for row in schedule_rows if isinstance(row, dict)}
    rows: list[dict[str, object]] = []
    for table in tables:
        row: dict[str, object] = {
            "status": "unknown",
            "action": "batch_freshness_check",
            "table": table,
            "expected_bizdate": expected_bizdate,
            "schedule": schedule_by_table.get(table),
        }
        try:
            latest = _resolve_latest_partition(table, executor, audit_path=audit_path, partition_col="pt")
            row["latest_partition"] = latest.get("partition_value")
            row["freshness_status"] = "fresh" if not expected_bizdate or latest.get("partition_value") == expected_bizdate else "stale"
            row["status"] = row["freshness_status"]
            if include_counts:
                count_bizdate = str(expected_bizdate or latest.get("partition_value") or "")
                if count_bizdate:
                    count_rows = _run_sql(
                        build_count_sql(table, count_bizdate),
                        executor,
                        audit_path=audit_path,
                        require_partition=True,
                        limit=1,
                    )
                    row["row_cnt"] = count_rows[0].get("row_cnt") if count_rows else None
        except Exception as exc:
            row.update(_dataworks_error_row("batch_freshness_check", table=table, exc=exc))
        rows.append(row)
    return rows


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
    if action == "batch-schedule-info":
        return _handle_batch_schedule_info(payload, dataworks_client=dataworks_client, odps_project=odps_project)
    if action == "schedule-graph":
        return _handle_schedule_graph(payload, dataworks_client=dataworks_client, odps_project=odps_project)
    if action == "recent-instances":
        return _handle_recent_instances(payload, dataworks_client=dataworks_client, odps_project=odps_project)
    if action == "instance-log-summary":
        return _handle_instance_log_summary(payload, dataworks_client=dataworks_client)
    if action == "batch-freshness-check":
        return _handle_batch_freshness_check(
            payload,
            executor,
            audit_path=audit_path,
            dataworks_client=dataworks_client,
            odps_project=odps_project,
        )

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
        max_nodes = int(payload.get("max_nodes") or limit)
        if max_nodes < 1 or max_nodes > 100:
            raise GatewayError("max_nodes must be between 1 and 100.")
        return resolve_table_logic(
            table,
            catalog_rows=rows,
            dataworks_client=dataworks_client,
            odps_project=odps_project,
            catalog_error=catalog_error,
            max_nodes=max_nodes,
            node_id=int(payload["node_id"]) if payload.get("node_id") is not None else None,
            project_id=int(payload["project_id"]) if payload.get("project_id") is not None else None,
            connection=str(payload["connection"]) if payload.get("connection") else None,
            file_type=int(payload["file_type"]) if payload.get("file_type") is not None else None,
            matched_output=str(payload["matched_output"]) if payload.get("matched_output") else None,
            require_single_node=bool(payload.get("require_single_node", False)),
        )
    return rows
