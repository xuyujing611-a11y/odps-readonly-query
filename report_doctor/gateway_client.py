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


def load_state(path: str | Path = STATE_PATH) -> dict[str, str]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


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
        with urllib.request.urlopen(request, timeout=120) as response:
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
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return [{"status": "error", "message": str(exc)}]
    return [{"status": "ok" if result.get("ok") else "error", "response": result}]


def append_evidence_log(path: str | Path, *, payload: dict[str, Any], rows: list[dict[str, object]]) -> None:
    evidence_path = Path(path)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
        "row_count": len(rows),
        "rows": rows,
    }
    with evidence_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


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
    inspect_table.add_argument("--partition-limit", type=int, default=10000)

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

    trace_table = subparsers.add_parser("trace-table", help="Alias for table-logic; resolve lineage and DataWorks node SQL")
    trace_table.add_argument("table")
    trace_table.add_argument("--limit", type=int, default=20)

    sql = subparsers.add_parser("sql", help="Run a safe read-only SQL string")
    sql.add_argument("sql")
    sql.add_argument("--limit", type=int, default=200)
    return parser


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
        }
    return {"action": "sql", "sql": args.sql, "limit": args.limit}


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

    if args.evidence_log:
        append_evidence_log(args.evidence_log, payload=payload, rows=rows)
    print_rows(rows, json_output=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
