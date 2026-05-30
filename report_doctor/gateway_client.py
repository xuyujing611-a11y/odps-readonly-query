from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
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
    subparsers = parser.add_subparsers(dest="command", required=True)

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
    latest_partition.add_argument("--limit", type=int, default=10000)
    latest_partition.add_argument(
        "--token-index",
        type=int,
        help="Use a specific matching partition token position when SHOW PARTITIONS is ambiguous",
    )

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

    sql = subparsers.add_parser("sql", help="Run a safe read-only SQL string")
    sql.add_argument("sql")
    sql.add_argument("--limit", type=int, default=200)
    return parser


def payload_from_args(args: argparse.Namespace) -> dict[str, Any]:
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
    if args.command == "table-logic":
        return {
            "action": "table-logic",
            "table": args.table,
            "limit": 20,
        }
    return {"action": "sql", "sql": args.sql, "limit": args.limit}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = payload_from_args(args)

    try:
        if args.command == "latest-partition":
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

    print_rows(rows, json_output=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))