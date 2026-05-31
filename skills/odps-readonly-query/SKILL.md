---
name: odps-readonly-query
description: Use when querying Alibaba Cloud MaxCompute or ODPS tables, doing quick row counts or samples, resolving partitions, checking report model data quality, tracing DataWorks table logic, comparing table outputs, or diagnosing ODPS data bugs through the bundled odps_report_doctor read-only gateway. Default mode uses a human-started local gateway unlocked from .env.enc; agents must not read secrets, decrypt config files, run direct PyODPS, use odpscmd, call DataWorks write APIs, execute mutating SQL, or speculate about unverified schemas.
---

# ODPS Read-Only Query

Use this skill to query Alibaba Cloud MaxCompute / ODPS through the local `odps_report_doctor` gateway.

## Operating Model

Default to Mode B:

1. A human puts `.env.enc` in the tool project root.
2. A human starts `python .\scripts\start_gateway.py` and enters the password locally.
3. The agent uses only `python .\scripts\gateway_query.py ...` while the gateway stays open.

Do not open, read, decrypt, copy, upload, replace, or ask the user to paste `.env`, `.env.enc`, AK/SK, or passwords. If the gateway is unavailable, ask the human to start it.

## Locate The Tool Project

Before querying, locate the downloaded project root. Prefer:

1. `$env:ODPS_REPORT_DOCTOR_ROOT` if it contains `scripts\gateway_query.py` and `report_doctor\`.
2. The current working directory if it contains those paths.
3. Nearby folders named `odps-readonly-query` or `odps_report_doctor`.
4. Ask the user for the path only if discovery fails.

Run commands from the project root. Do not assume the original author's local path.

## Task Router

- Quick row count or latest partition: use `quick-count` first. See `references/query-recipes.md`.
- Schema, partition keys, or confusing `SHOW PARTITIONS`: use `inspect-table` first. See `references/error-handling.md`.
- Small data sample: use `sample`.
- Field distribution or null-like checks: use `field-profile`.
- Table logic, schedule, lineage, or upstream SQL: use `trace-table`.
- ADS vs DWS or source-vs-target discrepancy: use `compare-tables`, then drill with targeted safe SQL. See `references/workflows.md`.
- Long multi-step investigation: use `--evidence-log outputs\investigations\<case>\evidence.jsonl` and keep a concise evidence trail. See `references/workflows.md`.
- Project-specific prefix defaults: see `references/project-context.md`.

## Behavior By Task Depth

Use the lightest workflow that can answer the user correctly.

**Simple lookups** include row counts, latest partition checks, small samples, one-field profiles, and direct table metadata questions. For these, run the smallest safe command, answer the verified result, and do not start lineage or root-cause work unless the result is ambiguous or the user asks why.

**Complex diagnosis** includes report differences, missing/incorrect values, data quality bugs,口径 questions, upstream logic checks, recurring production issues, and any request that asks for cause, impact, or fix direction. For these:

- Use an evidence log unless the investigation is only one or two commands.
- Start from the exact table/key/date/entity the user gave, then trace toward ADS, DWS, DWD, ODS, source, or DataWorks logic as far as read-only access allows.
- Every conclusion must be backed by an executed `gateway_query.py` command or SQL result. DataWorks node SQL alone explains intent; it is not proof that data matches that intent.
- Drill to the finest useful grain before calling the root cause verified: order, account, material, partner, source row, unmatched bucket, partition token, or exact filter/rule.
- Stop and mark the status as `ambiguous` or `blocked` if partition selection, schema discovery, permissions, or missing gateway state prevents verification.
- Do not over-investigate simple查数 tasks after the requested number or sample is verified.

## Hard Rules

- Never run direct ad hoc PyODPS `execute_sql()` code.
- Never run `odpscmd`.
- Never call DataWorks write/run/deploy APIs.
- Refuse or rewrite SQL with `INSERT`, `DELETE`, `UPDATE`, `DROP`, `ALTER`, `CREATE`, `MERGE`, `TRUNCATE`, or `OVERWRITE`. DataWorks node code may contain those words as text; do not execute it.
- Never invent field names, partition columns, upstream tables, or business dates. Verify with `inspect-table`, `catalog columns`, `trace-table`, or sample rows first.
- Do not use `safe_query.py` in normal agent mode; it may load encrypted config directly. Use `gateway_query.py`.
- If `gateway_query.py` cannot connect, stop and ask the human to start `start_gateway.py`.

## Gateway Not Running

Respond with this workflow, using the real project root path, then stop:

```text
The local ODPS read-only gateway is not running. Please run this in PowerShell:

cd "<odps-readonly-query project root>"
python .\scripts\start_gateway.py

Enter the .env.enc password locally, keep that window open, then reply "continue".
```

When the user replies, retry the original `gateway_query.py` command.

## Standard Commands

Health:

```powershell
python .\scripts\gateway_query.py health
```

Inspect table:

```powershell
python .\scripts\gateway_query.py --json inspect-table <qualified_table>
```

Quick count:

```powershell
python .\scripts\gateway_query.py --json quick-count <qualified_table> --bizdate latest
python .\scripts\gateway_query.py --json quick-count <qualified_table> --bizdate 20260527
```

Sample and profile:

```powershell
python .\scripts\gateway_query.py --json sample <qualified_table> --bizdate 20260527 --limit 20
python .\scripts\gateway_query.py --json field-profile <qualified_table> <field> --bizdate 20260527
```

Trace and compare:

```powershell
python .\scripts\gateway_query.py --json trace-table <qualified_table>
python .\scripts\gateway_query.py --json compare-tables <left_table> <right_table> --key <key_col> --metric <amount_col> --bizdate 20260527
```

Evidence log for long investigations:

```powershell
python .\scripts\gateway_query.py --evidence-log outputs\investigations\case_001\evidence.jsonl --json quick-count <qualified_table> --bizdate latest
```

## Partition Ambiguity Rules

- A row like `["pt=20250921", "pt=20250923"]` does not prove there is a `pt2` column.
- Use `inspect-table` or `catalog columns` to verify real partition keys.
- If `latest-partition` or `quick-count --bizdate latest` returns `status: ambiguous`, report the ambiguity and do not continue as if a date was confirmed.
- Use `--token-index <n>` only after metadata or a human confirms which token position is the business partition.

## Output Contract

Always report:

- command executed
- verified result
- evidence status: `verified`, `ambiguous`, `not_found`, `permission_error`, or `blocked`
- limitations or failed candidates
- next action only when useful

Do not use nicknames, casual speculation, or "I think". Use "verified" only when a command result supports it.
