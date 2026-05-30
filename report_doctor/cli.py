from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_settings
from .formatting import print_rows
from .odps_client import execute_sql_to_dicts, make_odps
from .safe_runner import DEFAULT_AUDIT_PATH, build_count_sql, build_partitions_sql, run_safe_sql
from .sql_safety import assert_read_only_sql
from .templates import render_sql_template


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTICS_ROOT = PROJECT_ROOT / "diagnostics"


def _common_options() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--env", default=str(PROJECT_ROOT / ".env"), help="Path to .env file")
    parser.add_argument("--audit-log", default=str(DEFAULT_AUDIT_PATH), help="Path to query audit JSONL log")
    parser.add_argument("--json", action="store_true", help="Print result rows as JSON")
    return parser


def _connect(env_path: str):
    return make_odps(load_settings(env_path))


def cmd_test_connection(args: argparse.Namespace) -> int:
    odps = _connect(args.env)
    rows = execute_sql_to_dicts(odps, "SELECT 1 AS ok", limit=1)
    print_rows(rows, json_output=args.json)
    return 0


def cmd_run_sql(args: argparse.Namespace) -> int:
    parameters = dict(item.split("=", 1) for item in args.param)
    if args.bizdate:
        parameters["bizdate"] = args.bizdate

    sql = render_sql_template(args.sql_file, parameters)
    odps = _connect(args.env)
    rows = run_safe_sql(
        sql,
        lambda query, limit: execute_sql_to_dicts(odps, query, limit=limit),
        audit_path=Path(args.audit_log),
        require_partition=not args.no_require_partition,
        limit=args.limit,
    )
    print_rows(rows, json_output=args.json)
    return 0


def _iter_report_sql(report_name: str) -> list[Path]:
    report_dir = DIAGNOSTICS_ROOT / report_name
    if not report_dir.exists():
        available = ", ".join(path.name for path in DIAGNOSTICS_ROOT.iterdir() if path.is_dir())
        raise FileNotFoundError(f"Unknown report '{report_name}'. Available reports: {available}")
    return sorted(report_dir.glob("*.sql"))


def cmd_doctor(args: argparse.Namespace) -> int:
    odps = _connect(args.env)
    for sql_file in _iter_report_sql(args.report):
        print(f"\n== {sql_file.name} ==")
        sql = render_sql_template(sql_file, {"bizdate": args.bizdate})
        rows = run_safe_sql(
            sql,
            lambda query, limit: execute_sql_to_dicts(odps, query, limit=limit),
            audit_path=Path(args.audit_log),
            require_partition=not args.no_require_partition,
            limit=args.limit,
        )
        print_rows(rows, json_output=args.json)
    return 0


def cmd_count(args: argparse.Namespace) -> int:
    sql = build_count_sql(args.table, args.bizdate, partition_col=args.partition_col)
    odps = _connect(args.env)
    rows = run_safe_sql(
        sql,
        lambda query, limit: execute_sql_to_dicts(odps, query, limit=limit),
        audit_path=Path(args.audit_log),
        limit=1,
    )
    print_rows(rows, json_output=args.json)
    return 0


def cmd_partitions(args: argparse.Namespace) -> int:
    sql = build_partitions_sql(args.table)
    odps = _connect(args.env)
    rows = run_safe_sql(
        sql,
        lambda query, limit: execute_sql_to_dicts(odps, query, limit=limit),
        audit_path=Path(args.audit_log),
        require_partition=False,
        limit=args.limit,
    )
    print_rows(rows, json_output=args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local MaxCompute report diagnostics")
    subparsers = parser.add_subparsers(dest="command", required=True)
    common = _common_options()

    test_connection = subparsers.add_parser(
        "test-connection",
        parents=[common],
        help="Run SELECT 1 against MaxCompute",
    )
    test_connection.set_defaults(func=cmd_test_connection)

    run_sql = subparsers.add_parser(
        "run-sql",
        parents=[common],
        help="Render and run one SQL template",
    )
    run_sql.add_argument("sql_file", help="Path to a .sql template")
    run_sql.add_argument("--bizdate", help="Value for ${bizdate}")
    run_sql.add_argument("--param", action="append", default=[], help="Extra template parameter, for example table=t")
    run_sql.add_argument("--limit", type=int, default=200, help="Max rows to print")
    run_sql.add_argument("--no-require-partition", action="store_true", help="Allow SELECT/WITH without pt/ds/bizdate")
    run_sql.set_defaults(func=cmd_run_sql)

    count = subparsers.add_parser(
        "count",
        parents=[common],
        help="Count rows for one table partition",
    )
    count.add_argument("table", help="Table name, for example dws_xxx or project.table")
    count.add_argument("--bizdate", required=True, help="Partition value, for example 20260527")
    count.add_argument("--partition-col", default="pt", help="Partition column, default: pt")
    count.set_defaults(func=cmd_count)

    partitions = subparsers.add_parser(
        "partitions",
        parents=[common],
        help="Show table partitions",
    )
    partitions.add_argument("table", help="Table name, for example dws_xxx or project.table")
    partitions.add_argument("--limit", type=int, default=200, help="Max rows to print")
    partitions.set_defaults(func=cmd_partitions)

    doctor = subparsers.add_parser(
        "doctor",
        parents=[common],
        help="Run all diagnostics for one report",
    )
    doctor.add_argument("report", help="Report diagnostic folder name")
    doctor.add_argument("--bizdate", required=True, help="Business date, for example 20260526")
    doctor.add_argument("--limit", type=int, default=200, help="Max rows to print per diagnostic")
    doctor.add_argument("--no-require-partition", action="store_true", help="Allow SELECT/WITH without pt/ds/bizdate")
    doctor.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
