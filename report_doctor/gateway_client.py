from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .formatting import print_rows
from .gateway import extract_latest_partition


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = PROJECT_ROOT / "gateway_state.json"
DEFAULT_NODE_CODE_DIR = PROJECT_ROOT / "outputs" / "node_code"
LONG_EVIDENCE_VALUE_LIMIT = 2000


def load_state(path: str | Path = STATE_PATH) -> dict[str, str]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _urlopen_local(request: urllib.request.Request, *, timeout: int):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(request, timeout=timeout)


def post_query(payload: dict[str, Any], *, state_path: str | Path = STATE_PATH) -> list[dict[str, object]]:
    state = load_state(state_path)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        state["base_url"].rstrip("/") + "/query",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-ODPS-Gateway-Token": state["token"],
        },
    )
    try:
        with _urlopen_local(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gateway request failed with HTTP {exc.code}: {body_text}") from exc

    if not result.get("ok"):
        raise RuntimeError(str(result.get("error", "Gateway request failed.")))
    return result["rows"]


def check_health(*, state_path: str | Path = STATE_PATH) -> list[dict[str, object]]:
    try:
        state = load_state(state_path)
        request = urllib.request.Request(state["base_url"].rstrip("/") + "/health", method="GET")
        with _urlopen_local(request, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return [{"status": "error", "message": str(exc)}]
    return [{"status": "ok" if result.get("ok") else "error", "response": result}]


def _summarize_evidence_value(value: object) -> object:
    if isinstance(value, str) and len(value) > LONG_EVIDENCE_VALUE_LIMIT:
        return {
            "summary": "truncated_long_string",
            "length": len(value),
            "preview": value[:LONG_EVIDENCE_VALUE_LIMIT],
        }
    if isinstance(value, list):
        return [_summarize_evidence_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _summarize_evidence_value(item) for key, item in value.items()}
    return value


def append_evidence_log(path: str | Path, *, payload: dict[str, Any], rows: list[dict[str, object]]) -> None:
    evidence_path = Path(path)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
        "row_count": len(rows),
        "rows": _summarize_evidence_value(rows),
    }
    with evidence_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def _safe_filename(value: object, *, fallback: str) -> str:
    text = str(value or fallback).strip() or fallback
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in text)
    return safe[:160] or fallback


def save_node_code_rows(
    rows: list[dict[str, object]],
    *,
    output_dir: str | Path,
    compact: bool,
) -> list[dict[str, object]]:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    saved_rows: list[dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            saved_rows.append(row)
            continue
        new_row = dict(row)
        code = new_row.get("node_code")
        if isinstance(code, str) and code:
            table = _safe_filename(new_row.get("table"), fallback="table")
            node = _safe_filename(new_row.get("node_name") or new_row.get("node_id"), fallback=f"node_{index}")
            project_id = _safe_filename(new_row.get("project_id"), fallback="unknown")
            node_id = _safe_filename(new_row.get("node_id"), fallback=f"unknown_{index}")
            file_type = _safe_filename(new_row.get("file_type"), fallback="unknown")
            path = target_dir / f"{table}__p{project_id}__n{node_id}__ft{file_type}__{node}.sql"
            path.write_text(code, encoding="utf-8")
            new_row["node_code_path"] = str(path)
            new_row["node_code_length"] = len(code)
            new_row.setdefault("node_code_preview", code[:1200])
            if compact:
                new_row.pop("node_code", None)
        saved_rows.append(new_row)
    return saved_rows


def latest_partition_rows(
    table: str,
    *,
    partition_col: str = "pt",
    limit: int = 10000,
    token_index: int | None = None,
    fetcher=None,
) -> list[dict[str, object]]:
    fetch = fetcher or (lambda payload: post_query(payload))
    rows = fetch({"action": "partitions", "table": table, "limit": limit})
    return [extract_latest_partition(rows, partition_col=partition_col, token_index=token_index)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query the local ODPS read-only gateway")
    parser.add_argument("--state", default=str(STATE_PATH), help="Path to gateway state JSON")
    parser.add_argument("--json", action="store_true", help="Print rows as JSON")
    parser.add_argument("--evidence-log", help="Append command payload and rows to a local JSONL evidence log")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("health", help="Check local gateway health without reading encrypted config")

    count = subparsers.add_parser("count", help="Count one table partition")
    count.add_argument("table")
    count.add_argument("--bizdate", required=True)
    count.add_argument("--partition-col", default="pt")

    partitions = subparsers.add_parser("partitions", help="Show table partitions")
    partitions.add_argument("table")
    partitions.add_argument("--limit", type=int, default=200)

    latest_partition = subparsers.add_parser("latest-partition", help="Return the latest yyyymmdd partition")
    latest_partition.add_argument("table")
    latest_partition.add_argument("--partition-col", default="pt")
    latest_partition.add_argument("--method", choices=["max-pt", "show-partitions"], default="max-pt")
    latest_partition.add_argument("--limit", type=int, default=10000)
    latest_partition.add_argument(
        "--token-index",
        type=int,
        help="Use a specific matching partition token position when SHOW PARTITIONS is ambiguous",
    )

    inspect_table = subparsers.add_parser("inspect-table", help="Collect table metadata, partition keys, and latest partition status")
    inspect_table.add_argument("table")
    inspect_table.add_argument("--partition-col", default="pt")
    inspect_table.add_argument("--token-index", type=int)
    inspect_table.add_argument("--catalog-limit", type=int, default=500)
    inspect_table.add_argument("--partition-limit", type=int, default=5000)
    inspect_table.add_argument("--include-partition-sample", action="store_true")

    quick_count = subparsers.add_parser("quick-count", help="Count a table partition, optionally resolving latest first")
    quick_count.add_argument("table")
    quick_count.add_argument("--bizdate", default="latest")
    quick_count.add_argument("--partition-col", default="pt")
    quick_count.add_argument("--method", choices=["max-pt", "show-partitions"], default="max-pt")
    quick_count.add_argument("--token-index", type=int)

    sample = subparsers.add_parser("sample", help="Sample rows from one table partition")
    sample.add_argument("table")
    sample.add_argument("--bizdate", required=True)
    sample.add_argument("--partition-col", default="pt")
    sample.add_argument("--limit", type=int, default=20)

    field_profile = subparsers.add_parser("field-profile", help="Count top values for one field in one partition")
    field_profile.add_argument("table")
    field_profile.add_argument("field")
    field_profile.add_argument("--bizdate", required=True)
    field_profile.add_argument("--partition-col", default="pt")
    field_profile.add_argument("--limit", type=int, default=50)

    compare_tables = subparsers.add_parser("compare-tables", help="Compare count and metric sums between two partitioned tables")
    compare_tables.add_argument("left_table")
    compare_tables.add_argument("right_table")
    compare_tables.add_argument("--key", required=True)
    compare_tables.add_argument("--metric", required=True)
    compare_tables.add_argument("--bizdate", required=True)
    compare_tables.add_argument("--partition-col", default="pt")
    compare_tables.add_argument("--limit", type=int, default=100)

    catalog = subparsers.add_parser(
        "catalog",
        help="Run controlled SYSTEM_CATALOG.INFORMATION_SCHEMA templates",
    )
    catalog.add_argument("template", choices=["table", "logic", "columns", "partitions"])
    catalog.add_argument("table")
    catalog.add_argument("--limit", type=int, default=200)

    logic = subparsers.add_parser("logic", help="Show table metadata and view SQL logic when available")
    logic.add_argument("table")
    logic.add_argument("--limit", type=int, default=20)

    table_logic = subparsers.add_parser(
        "table-logic",
        help="Resolve table logic from catalog first, then DataWorks read-only OpenAPI",
    )
    table_logic.add_argument("table")
    table_logic.add_argument("--limit", type=int, default=20)
    table_logic.add_argument("--save-node-code", nargs="?", const=str(DEFAULT_NODE_CODE_DIR))
    table_logic.add_argument("--compact-node-code", action="store_true")
    _add_node_selection_arguments(table_logic)

    trace_table = subparsers.add_parser("trace-table", help="Alias for table-logic; resolve lineage and DataWorks node SQL")
    trace_table.add_argument("table")
    trace_table.add_argument("--limit", type=int, default=20)
    trace_table.add_argument("--save-node-code", nargs="?", const=str(DEFAULT_NODE_CODE_DIR))
    trace_table.add_argument("--compact-node-code", action="store_true", default=True)
    _add_node_selection_arguments(trace_table)

    sql = subparsers.add_parser("sql", help="Run a safe read-only SQL string")
    sql.add_argument("sql")
    sql.add_argument("--limit", type=int, default=200)
    sql.add_argument("--no-require-partition", action="store_true", help="Allow SELECT/WITH without pt/ds/bizdate for controlled small queries")
    return parser


def _add_node_selection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-nodes", type=int, help="Maximum candidate nodes to return after filtering")
    parser.add_argument("--node-id", type=int, help="Return only this DataWorks node id")
    parser.add_argument("--project-id", type=int, help="Return only nodes from this DataWorks project id")
    parser.add_argument("--connection", help="Return only nodes whose connection matches exactly")
    parser.add_argument("--file-type", type=int, help="Return only nodes with this DataWorks file type")
    parser.add_argument("--matched-output", help="Return only nodes matched through this exact output name")
    parser.add_argument(
        "--require-single-node",
        action="store_true",
        help="Fail unless node selection resolves to exactly one candidate",
    )


def payload_from_args(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "health":
        return {"action": "health"}
    if args.command == "count":
        return {
            "action": "count",
            "table": args.table,
            "bizdate": args.bizdate,
            "partition_col": args.partition_col,
            "limit": 1,
        }
    if args.command == "partitions":
        return {"action": "partitions", "table": args.table, "limit": args.limit}
    if args.command == "latest-partition":
        return {
            "action": "latest-partition",
            "table": args.table,
            "partition_col": args.partition_col,
            "limit": args.limit,
            "token_index": args.token_index,
            "method": args.method,
        }
    if args.command == "inspect-table":
        return {
            "action": "inspect-table",
            "table": args.table,
            "partition_col": args.partition_col,
            "token_index": args.token_index,
            "catalog_limit": args.catalog_limit,
            "partition_limit": args.partition_limit,
            "include_partition_sample": args.include_partition_sample,
        }
    if args.command == "quick-count":
        return {
            "action": "quick-count",
            "table": args.table,
            "bizdate": args.bizdate,
            "partition_col": args.partition_col,
            "limit": 1,
            "token_index": args.token_index,
            "method": args.method,
        }
    if args.command == "sample":
        return {
            "action": "sample",
            "table": args.table,
            "bizdate": args.bizdate,
            "partition_col": args.partition_col,
            "limit": args.limit,
        }
    if args.command == "field-profile":
        return {
            "action": "field-profile",
            "table": args.table,
            "field": args.field,
            "bizdate": args.bizdate,
            "partition_col": args.partition_col,
            "limit": args.limit,
        }
    if args.command == "compare-tables":
        return {
            "action": "compare-tables",
            "left_table": args.left_table,
            "right_table": args.right_table,
            "key": args.key,
            "metric": args.metric,
            "bizdate": args.bizdate,
            "partition_col": args.partition_col,
            "limit": args.limit,
        }
    if args.command == "catalog":
        return {
            "action": "catalog",
            "template": args.template,
            "table": args.table,
            "limit": args.limit,
        }
    if args.command == "logic":
        return {
            "action": "catalog",
            "template": "logic",
            "table": args.table,
            "limit": 20,
        }
    if args.command in {"table-logic", "trace-table"}:
        return {
            "action": "table-logic",
            "table": args.table,
            "limit": args.limit,
            "max_nodes": args.max_nodes if args.max_nodes is not None else args.limit,
            "node_id": args.node_id,
            "project_id": args.project_id,
            "connection": args.connection,
            "file_type": args.file_type,
            "matched_output": args.matched_output,
            "require_single_node": args.require_single_node,
        }
    return {
        "action": "sql",
        "sql": args.sql,
        "limit": args.limit,
        "require_partition": not args.no_require_partition,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = payload_from_args(args)

    try:
        if args.command == "health":
            rows = check_health(state_path=args.state)
        elif args.command == "latest-partition":
            try:
                rows = post_query(payload, state_path=args.state)
            except RuntimeError as exc:
                if "Unsupported gateway action: latest-partition" not in str(exc):
                    raise
                rows = latest_partition_rows(
                    args.table,
                    partition_col=args.partition_col,
                    limit=args.limit,
                    token_index=args.token_index,
                    fetcher=lambda fallback_payload: post_query(fallback_payload, state_path=args.state),
                )
        else:
            rows = post_query(payload, state_path=args.state)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.command in {"table-logic", "trace-table"} and getattr(args, "save_node_code", None):
        rows = save_node_code_rows(
            rows,
            output_dir=args.save_node_code,
            compact=bool(getattr(args, "compact_node_code", False)),
        )

    if args.evidence_log:
        append_evidence_log(args.evidence_log, payload=payload, rows=rows)
    print_rows(rows, json_output=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
