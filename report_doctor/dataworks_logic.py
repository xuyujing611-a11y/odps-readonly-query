from __future__ import annotations

from typing import Any

from .safe_runner import validate_table_name


def candidate_outputs_for_table(table: str, *, odps_project: str | None = None) -> list[str]:
    table = validate_table_name(table)
    if "." in table:
        project, table_name = table.split(".", 1)
        candidates = [f"{project}.{table_name}", table_name]
    elif odps_project:
        candidates = [f"{validate_table_name(odps_project)}.{table}", table]
    else:
        candidates = [table]

    result: list[str] = []
    for candidate in candidates:
        if candidate not in result:
            result.append(candidate)
    return result


def _split_table(table: str, *, odps_project: str | None = None) -> tuple[str | None, str]:
    table = validate_table_name(table)
    if "." in table:
        project, table_name = table.split(".", 1)
        return project, table_name
    return odps_project, table


def _first_value(row: dict[str, Any], *keys: str) -> Any:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value is not None:
            return value
    return None


def _catalog_view_logic(table: str, catalog_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in catalog_rows:
        view_sql = _first_value(row, "view_original_text", "ViewOriginalText")
        if view_sql:
            return {
                "table": table,
                "source": "system_catalog_view",
                "status": "ok",
                "table_type": _first_value(row, "table_type", "TableType"),
                "logic_sql": str(view_sql),
            }
    return None


def _iter_nodes(output_pairs: list[dict[str, Any]]):
    for pair in output_pairs:
        output = _first_value(pair, "Output", "output")
        nodes = _first_value(pair, "NodeList", "node_list", "Nodes", "nodes") or []
        if isinstance(nodes, dict):
            nodes = [nodes]
        for node in nodes:
            yield str(output or ""), node


def _normalize_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except ValueError:
        return None


def _meta_table_matches(row: dict[str, Any], *, project: str | None, table_name: str, project_env: str | None) -> bool:
    row_table = _first_value(row, "TableName", "table_name")
    if str(row_table or "").lower() != table_name.lower():
        return False

    row_project = _first_value(row, "ProjectName", "project_name", "DatabaseName", "database_name")
    if project and str(row_project or "").lower() != project.lower():
        return False

    env_type = _normalize_int(_first_value(row, "EnvType", "env_type"))
    if project_env and project_env.upper() == "PROD" and env_type is not None and env_type != 1:
        return False
    if project_env and project_env.upper() == "DEV" and env_type is not None and env_type != 0:
        return False

    return True


def _candidate_meta_tables(
    meta_tables: list[dict[str, Any]],
    *,
    project: str | None,
    table_name: str,
    project_env: str | None,
) -> list[dict[str, Any]]:
    exact = [
        row
        for row in meta_tables
        if _meta_table_matches(row, project=project, table_name=table_name, project_env=project_env)
    ]
    if exact:
        return exact

    return [
        row
        for row in meta_tables
        if _meta_table_matches(row, project=None, table_name=table_name, project_env=project_env)
    ]


def _row_from_dataworks_node(
    *,
    table: str,
    dataworks_client,
    detail: dict[str, Any],
    node: dict[str, Any],
    node_id: int,
    code: str,
    catalog_error: str | None,
    lookup_method: str,
    matched_output: str | None = None,
    matched_table_guid: str | None = None,
    meta_table: dict[str, Any] | None = None,
    producing_task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "table": table,
        "source": "dataworks_openapi",
        "status": "ok",
        "lookup_method": lookup_method,
        "project_env": getattr(dataworks_client, "project_env", None),
        "catalog_status": "error" if catalog_error else "ok",
        "catalog_error": catalog_error,
        "node_id": int(node_id),
        "node_name": _first_value(detail, "NodeName", "node_name")
        or _first_value(node, "NodeName", "node_name")
        or _first_value(producing_task or {}, "TaskName", "task_name"),
        "file_type": _first_value(detail, "FileType", "file_type") or _first_value(node, "FileType", "file_type"),
        "project_id": _first_value(detail, "ProjectId", "project_id") or _first_value(node, "ProjectId", "project_id"),
        "owner_id": _first_value(detail, "OwnerId", "owner_id") or _first_value(node, "OwnerId", "owner_id"),
        "connection": _first_value(detail, "Connection", "connection"),
        "cron_express": _first_value(detail, "CronExpress", "cron_express"),
        "node_code": code,
        "node_code_length": len(code),
    }
    if matched_output is not None:
        row["matched_output"] = matched_output
    if matched_table_guid is not None:
        row["matched_table_guid"] = matched_table_guid
    if meta_table is not None:
        row["meta_table_project"] = _first_value(meta_table, "ProjectName", "project_name")
        row["meta_table_env_type"] = _first_value(meta_table, "EnvType", "env_type")
    if producing_task is not None:
        row["producing_task_id"] = _first_value(producing_task, "TaskId", "task_id")
        row["producing_task_name"] = _first_value(producing_task, "TaskName", "task_name")
    return row


def _resolve_from_producing_tasks(
    table: str,
    *,
    dataworks_client,
    odps_project: str | None,
    max_nodes: int,
    catalog_error: str | None,
) -> list[dict[str, Any]]:
    project, table_name = _split_table(table, odps_project=odps_project)
    meta_tables = dataworks_client.search_meta_tables(table_name)
    candidates = _candidate_meta_tables(
        meta_tables,
        project=project,
        table_name=table_name,
        project_env=getattr(dataworks_client, "project_env", None),
    )
    rows: list[dict[str, Any]] = []

    for meta_table in candidates:
        if len(rows) >= max_nodes:
            break
        table_guid = _first_value(meta_table, "TableGuid", "table_guid")
        if not table_guid:
            continue
        tasks = dataworks_client.get_meta_table_producing_tasks(str(table_guid), table_name=table_name)
        for task in tasks:
            if len(rows) >= max_nodes:
                break
            node_id = _normalize_int(_first_value(task, "TaskId", "task_id", "NodeId", "node_id"))
            if node_id is None:
                continue
            detail = dataworks_client.get_node(node_id)
            code = dataworks_client.get_node_code(node_id)
            rows.append(
                _row_from_dataworks_node(
                    table=table,
                    dataworks_client=dataworks_client,
                    detail=detail,
                    node={},
                    node_id=node_id,
                    code=code,
                    catalog_error=catalog_error,
                    lookup_method="meta_table_producing_tasks",
                    matched_table_guid=str(table_guid),
                    meta_table=meta_table,
                    producing_task=task,
                )
            )

    return rows


def resolve_table_logic(
    table: str,
    *,
    catalog_rows: list[dict[str, Any]],
    dataworks_client,
    odps_project: str | None,
    max_nodes: int = 5,
    catalog_error: str | None = None,
) -> list[dict[str, Any]]:
    table = validate_table_name(table)
    view_logic = _catalog_view_logic(table, catalog_rows)
    if view_logic:
        return [view_logic]

    if dataworks_client is None:
        return [
            {
                "table": table,
                "source": "dataworks_openapi",
                "status": "unavailable",
                "catalog_status": "error" if catalog_error else "ok",
                "catalog_error": catalog_error,
                "message": "DataWorks read-only client is not configured or SDK is not installed.",
            }
        ]

    outputs = candidate_outputs_for_table(table, odps_project=odps_project)
    output_pairs = dataworks_client.find_nodes_by_outputs(outputs)
    rows: list[dict[str, Any]] = []

    for output, node in _iter_nodes(output_pairs):
        if len(rows) >= max_nodes:
            break
        node_id = _first_value(node, "NodeId", "node_id")
        if node_id is None:
            continue
        detail = dataworks_client.get_node(int(node_id))
        code = dataworks_client.get_node_code(int(node_id))
        rows.append(
            _row_from_dataworks_node(
                table=table,
                dataworks_client=dataworks_client,
                detail=detail,
                node=node,
                node_id=int(node_id),
                code=code,
                catalog_error=catalog_error,
                lookup_method="nodes_by_output",
                matched_output=output,
            )
        )

    if rows:
        return rows

    rows = _resolve_from_producing_tasks(
        table,
        dataworks_client=dataworks_client,
        odps_project=odps_project,
        max_nodes=max_nodes,
        catalog_error=catalog_error,
    )
    if rows:
        return rows

    return [
        {
            "table": table,
            "source": "dataworks_openapi",
            "status": "not_found",
            "project_env": getattr(dataworks_client, "project_env", None),
            "catalog_status": "error" if catalog_error else "ok",
            "catalog_error": catalog_error,
            "candidate_outputs": outputs,
            "lookup_methods": ["nodes_by_output", "meta_table_producing_tasks"],
            "message": "No DataWorks node was found by table output or metatable producing tasks.",
        }
    ]
