---
name: odps-readonly-query
description: Use when querying Alibaba Cloud MaxCompute or ODPS tables, checking table row counts, partitions, report model data quality, table SQL logic, DataWorks node code or schedule, system catalog metadata, or diagnosing report data issues with the bundled odps_report_doctor read-only gateway. Requires local gateway_query.py or safe_query.py and forbids direct PyODPS, odpscmd, DataWorks write operations, SQL mutation, or asking users to paste secrets in chat.
---

# ODPS Read-Only Query

Use this skill for Alibaba Cloud MaxCompute / ODPS / DataWorks table queries, table logic lookup, scheduling lookup, metadata discovery, and report data diagnosis through the local `odps_report_doctor` tooling.

## Locate The Tool Project

Before querying, locate the downloaded `odps_report_doctor` project root. Prefer this order:

1. Use `$env:ODPS_REPORT_DOCTOR_ROOT` if it is set and contains `scripts\gateway_query.py` plus `report_doctor\`.
2. Use the current working directory if it contains `scripts\gateway_query.py` plus `report_doctor\`.
3. Search nearby workspace folders for `odps_report_doctor`.
4. If still not found, ask the user where they downloaded the project.

Run all commands from the project root. Do not assume the original author's local path.

## Required Local Setup

The project root should contain a local `.env` or `.env.enc`. Never ask the user to paste AK/SK, `.env`, `.env.enc`, or passwords into chat. If configuration is missing, tell the user to place their provided `.env` or `.env.enc` in the project root, or to copy `.env.example` to `.env` and edit it locally.

Install dependencies into the project directory, not global Python:

```powershell
python .\scripts\bootstrap_vendor.py
```

## Hard Rules

- Never run direct ad hoc PyODPS `execute_sql()` code.
- Never run `odpscmd` for this workflow.
- Never call DataWorks write/run/deploy APIs. Allowed DataWorks APIs are read-only metadata/code lookups such as `ListNodesByOutput`, `GetNode`, `GetNodeCode`, `SearchMetaTables`, and `GetMetaTableProducingTasks`.
- Refuse or rewrite any user SQL involving `INSERT`, `DELETE`, `UPDATE`, `DROP`, `ALTER`, `CREATE`, `MERGE`, `TRUNCATE`, or `OVERWRITE`. DataWorks node code may contain those words as text; do not execute it.
- Prefer an already-started local gateway for interactive work.
- If the gateway is not running or `gateway_query.py` cannot connect, stop and ask the user to start the gateway. Do not fall back to password prompts unless the user explicitly asks for one-shot mode.
- Fallback one-shot queries may execute only through `scripts\safe_query.py` or wrappers that call the same safe runner.

## Gateway Not Running

Respond with this workflow, using the actual project root path you found, then stop:

```text
本地 ODPS 只读网关还没有启动。请在 PowerShell 里运行：

cd "<odps_report_doctor project root>"
python .\scripts\start_gateway.py

输入 .env.enc 密码后保持窗口打开，然后回复“继续”，我会接着刚才的查询。
```

When the user replies `继续`, retry the original `gateway_query.py` command.

## Table Name Normalization

- If the user provides a fully qualified table such as `yh_doc_cdm.some_table`, use that exact table first.
- If the user provides only a table name and the user's workspace has known project prefixes, build likely candidates before trying anything else.
- For the original `yh_doc_*` workspace, use:
  - `ads_`, `rpt_`, report-style table -> `yh_doc_ads.<table>` first.
  - `ods_` -> `yh_doc_ods.<table>` first.
  - `dwd_`, `dws_`, `dim_`, `fact_` -> `yh_doc_cdm.<table>` first.
  - otherwise try `yh_doc_cdm.<table>`, then `yh_doc_ads.<table>`, then `yh_doc_ods.<table>`.
- Stop after the first qualified candidate returns a useful result.
- If the user corrects a typo or provides a new exact table, abandon the old candidate and query the new exact table.

## Standard Commands

Check connection:

```powershell
python .\scripts\safe_query.py test-connection
```

Start unlocked read-only gateway:

```powershell
python .\scripts\start_gateway.py
```

Show partitions:

```powershell
python .\scripts\gateway_query.py partitions <qualified_table>
```

Find latest partition:

```powershell
python .\scripts\gateway_query.py latest-partition <qualified_table>
```

For latest-partition results, use the returned `partition_value` as the `pt` value for the next command. Never infer the latest partition from the last visible row of `partitions`.

Count one partition:

```powershell
python .\scripts\gateway_query.py count <qualified_table> --bizdate 20260527
```

Resolve table logic and schedule:

```powershell
python .\scripts\gateway_query.py --json table-logic <qualified_table>
```

Controlled catalog templates:

```powershell
python .\scripts\gateway_query.py --json catalog table <qualified_table>
python .\scripts\gateway_query.py --json catalog columns <qualified_table>
python .\scripts\gateway_query.py --json catalog partitions <qualified_table> --limit 500
```

Catalog commands are the only approved way to query `SYSTEM_CATALOG.INFORMATION_SCHEMA`. Do not send arbitrary `SYSTEM_CATALOG.INFORMATION_SCHEMA` SQL through the raw `sql` command.

## Table Logic Workflow

For "查某张表的调度信息和逻辑 SQL":

1. Normalize the table using known project prefixes.
2. Run `table-logic` on the best qualified candidate.
3. Interpret the result:
   - `status: ok`: report `node_id`, `node_name`, `project_env`, `matched_output`, `connection`, `cron_express`, `node_code_length`, and a concise SQL summary.
   - `catalog_status: error` with `status: ok`: say catalog permission failed, but DataWorks read-only lookup succeeded.
   - `status: not_found`: this means both DataWorks output-name lookup and metatable producing-task lookup did not match. Do not conclude the table or node does not exist; report `candidate_outputs`, then try the next production candidate if the user did not provide an exact prefix.
4. `table-logic` automatically falls back from `ListNodesByOutput -> GetNode/GetNodeCode` to `SearchMetaTables -> GetMetaTableProducingTasks -> GetNode/GetNodeCode`.
5. Do not paste very long `node_code` unless the user asks. Save it under `outputs\` when useful and report the path.

## SQL Query Workflow

- Prefer partition-scoped queries.
- Treat `--bizdate 20260527` as `pt = '20260527'`.
- For arbitrary safe SQL, use the gateway `sql` command only for `SELECT` / `WITH` queries that pass the local safety gate and, when appropriate, include a `pt` filter.
- For report diagnostics, prefer checked-in templates:

```powershell
python .\scripts\safe_query.py run-sql .\diagnostics\<report>\<check>.sql --bizdate 20260527
python .\scripts\safe_query.py doctor <report_name> --bizdate 20260527
```

## Reporting Format

Include:

- table name and qualified candidate used
- command executed
- partition, catalog method, or DataWorks lookup method
- row count, partition, metadata, schedule, node code summary, or key result
- whether the query went through `gateway_query.py` or `safe_query.py`
- limitations, permission failures, or failed candidates
