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

Before querying on this machine, use the canonical tool root first:

```powershell
cd "D:\my projects\ai_yunwei\odps-readonly-query"
```

That directory must contain `scripts\gateway_query.py` and `report_doctor\`. The Codex skill entry `D:\Codex\.codex\skills\odps-readonly-query` is only a junction to this skill document, not the tool project root.

Fallback order when the canonical path is unavailable:

1. `$env:ODPS_REPORT_DOCTOR_ROOT` if it contains `scripts\gateway_query.py` and `report_doctor\`.
2. The current working directory if it contains those paths.
3. Nearby folders named `odps-readonly-query`.
4. Ask the user for the path only if discovery fails.

Run commands from the project root. Do not start by probing the current workspace when the canonical D: path exists.

## Local Gateway Proxy Rule

The gateway listens on localhost. If shell proxy variables such as `http_proxy`, `https_proxy`, or `all_proxy` are set, localhost requests can return proxy `502` errors unless bypassed. The current gateway client disables proxies for its own localhost HTTP calls. If an older client is in use or health returns `HTTP Error 502: Bad Gateway`, retry with:

```powershell
$env:NO_PROXY='127.0.0.1,localhost'; $env:no_proxy='127.0.0.1,localhost'; python .\scripts\gateway_query.py health
```

## Task Router

- Quick row count or latest partition: use `quick-count --bizdate latest` or `latest-partition`; these default to `MAX_PT` and avoid parsing multi-token `SHOW PARTITIONS` rows. See `references/query-recipes.md`.
- Schema, partition keys, or confusing `SHOW PARTITIONS`: use `inspect-table` first. See `references/error-handling.md`.
- Small data sample: use `sample`.
- Field distribution or null-like checks: use `field-profile`.
- Table logic, schedule, lineage, or upstream SQL: use `trace-table --save-node-code outputs\node_code --compact-node-code`.
- ADS vs DWS or source-vs-target discrepancy: use `compare-tables`, then drill with targeted safe SQL. See `references/workflows.md`.
- User-facing report names or aliases, including income, management-report, assessment income/cost, outbound shipment, or gross-profit reports: read `references/report-index.yaml` first; then read the matched chain document.
- Long multi-step investigation: use `--evidence-log outputs\investigations\<case>\evidence.jsonl` and keep a concise evidence trail. See `references/workflows.md`.
- Project-specific prefix defaults: see `references/project-context.md`.


## Report Knowledge Loop

Use `references/report-index.yaml` as the first stop for user-facing report names, Chinese aliases, and recurring business phrases. If an alias matches, read only the linked `reference` document before tracing more lineage.

After a complex diagnosis, update the knowledge base only for durable facts verified by `gateway_query.py` SQL, `inspect-table`, or `trace-table`. Add aliases, primary tables, lineage, and caveats to the existing report entry when possible. Create a new chain document only when the report family has a distinct perspective or repeated workflow.

Do not record one-off order behavior, guesses, temporary SQL, dev-table observations, or unverified business assumptions as facts. If useful but uncertain, mark the report entry or document section as `tentative` or `needs-verification` and include the evidence command needed to verify it.

Keep `SKILL.md` lean. Put routing metadata in `report-index.yaml`; put detailed lineage, table responsibilities, query templates, and known pitfalls in the linked reference document.
## Knowledge Base Update Gate

Before the final response for any complex diagnosis, report debugging, bug localization, root-cause analysis, impact assessment, or production model SQL recommendation:

1. Decide whether the investigation produced durable, reusable facts verified by `gateway_query.py` SQL, `inspect-table`, or `trace-table`.
2. If yes, update `references/report-index.yaml` and the matched reference document before the final response. Add a new chain document only when the report family has a distinct perspective or repeated workflow.
3. If no, explicitly record `knowledge_base_update=skipped` and the reason, such as one-off case, unverified fact, missing permission, no reusable report chain, or no new durable fact beyond existing knowledge.
4. Do not mark the task complete until this gate is satisfied.
5. In the final response, include `knowledge_base_update=updated` with updated file path(s), or `knowledge_base_update=skipped` with the skip reason.

## Production Project Defaults

For this workflow, business diagnosis defaults to production projects only. Do not rely on the gateway's default `*_dev` project and do not query `yh_doc_*_dev` unless the user explicitly asks for dev data.

- `ads_` report tables: qualify as `yh_doc_ads.<table>`.
- `dwd_`, `dws_`, `dim_`, `fact_`, and most model tables: qualify as `yh_doc_cdm.<table>`.
- `ods_` and raw ODS tables: qualify as `yh_doc_ods.<table>`.
- If the user gives an unqualified table and the first production prefix fails, use `table-logic <table>` to discover the production connection, then retry with the production-qualified table. Treat dev data as non-authoritative for root-cause answers.

## Behavior By Task Depth

Use the lightest workflow that can answer the user correctly.

**Simple lookups** include row counts, latest partition checks, small samples, one-field profiles, and direct table metadata questions. For these, run the smallest safe command, answer the verified result, and do not start lineage or root-cause work unless the result is ambiguous or the user asks why.

**Complex diagnosis** includes report differences, missing/incorrect values, data quality bugs, metric-definition questions, upstream logic checks, recurring production issues, and any request that asks for cause, impact, or fix direction. For these:

- Use an evidence log unless the investigation is only one or two commands.
- Start from the exact table/key/date/entity the user gave, then trace toward ADS, DWS, DWD, ODS, source, or DataWorks logic as far as read-only access allows.
- Every conclusion must be backed by an executed `gateway_query.py` command or SQL result. DataWorks node SQL alone explains intent; it is not proof that data matches that intent.
- When the user names a Chinese field or report label, first verify candidate physical fields with `inspect-table` or `catalog columns`. Match by exact `column_comment` before using near-synonym columns; if several candidates exist, report them and choose the exact-comment field or ask for clarification.
- For entity-level field bugs, first query a partition-level aggregate at the entity grain using `count(1)`, `count(distinct <business key>)`, `collect_set(<field>)`, and key min/max dates. Only fetch row samples after the aggregate proves which values are present.
- Drill to the finest useful grain before calling the root cause verified: order, account, material, partner, source row, unmatched bucket, partition token, or exact filter/rule.
- When upstream SQL uses rule CTEs or CASE logic, reproduce the relevant branch with a small read-only CTE for the exact entity. Output boolean columns for each candidate condition, especially `IN`/`NOT IN`, null fallback, date-window, and join-match predicates.
- Stop and mark the status as `ambiguous` or `blocked` if partition selection, schema discovery, permissions, or missing gateway state prevents verification.
- Do not over-investigate simple lookup tasks after the requested number or sample is verified.

## Verification Closure Rules

For data operations, report debugging, bug localization, business logic tracing, root-cause analysis, impact assessment, or fix recommendation:

- Never use fake data, mock rows, fabricated examples, or guessed sample values as verification evidence.
- Never close a conclusion through code reading, metadata reading, screenshots, or logical reasoning alone.
- DataWorks node SQL, repository SQL, metadata, report screenshots, and business assumptions explain intent only; they do not prove production behavior.
- Reproduce the actual production logic with read-only SQL against real tables for the exact entity, period, partition/date, account, material, order, organization, or business key supplied by the user.
- When the production logic contains joins, `CASE` branches, rule tables, fallback conditions, exchange-rate conversion, allocation, reversal, or partition/date filtering, rebuild the relevant branch in a focused read-only SQL and output intermediate columns or grouped aggregates that prove which branch fired.
- A root cause is verified only after the observed symptom, upstream source, transformation rule, and proposed fix effect are all checked with real query results.
- If real data cannot be queried because of permission, missing schema, gateway failure, or unclear business keys, mark the result as `blocked` or `ambiguous`. Do not replace missing evidence with inference.

## Production Model SQL Edit Gate

Use this gate when the user asks to modify, output, or patch production DataWorks/ODPS model SQL, especially ADS/DWS/DWD node code.

- Never use a local cached SQL file as the edit baseline. First fetch the PROD node with `trace-table <qualified_table> --save-node-code <temp_dir> --compact-node-code` and identify the returned `node_id`, `project_env`, and `node_code_path`.
- Copy or otherwise reset the working SQL file from the freshly fetched PROD node code before applying changes. If the workspace has user edits that must be preserved, stop and report the conflict instead of merging by guesswork.
- Apply only the requested semantic change. Do not reformat, reorder, normalize encoding, collapse comments, or "clean up" unrelated SQL.
- Before claiming the SQL matches production, run an allowlist diff: remove only the expected new/changed lines for the request, then compare the remaining local SQL to the freshly fetched PROD node code. The comparison must show equal line counts and zero unexpected differences.
- Read the final `INSERT`/`SELECT` column list after editing. Verify every union branch has the same field order and preserves production null handling such as `NVL(<metric>, 0) AS <metric>`, scale factors such as `/10000`, and existing aliases.
- Compile-test the edited logic with read-only `sql` statements against production tables. Rebuild only the relevant CTE branches and output representative columns; never execute the production `INSERT`, `CREATE`, `DROP`, or `OVERWRITE`.
- Delete temporary PROD node-code directories created for the comparison once verification is complete.
- In the final answer, report the `trace-table` command result, allowlist diff result such as `unexpected_diff_count=0`, read-only SQL verification status, and any remaining deployment prerequisite such as a required table schema change.

## Fragile Gateway Fallbacks

The wrapper commands are conveniences, not proof that the data cannot be queried.

- `inspect-table` defaults to a lightweight output: table metadata, columns, partition keys, and latest partition. Use `--include-partition-sample` only for explicit partition diagnostics; keep `--partition-limit` no higher than 5000. If an older client still fails because the gateway requests a limit above the current server maximum, retry with `--partition-limit 5000`; if it still fails, fall back to `table-logic`, `partitions --limit 5000`, small `sample`, and targeted `sql`.
- If `SYSTEM_CATALOG.INFORMATION_SCHEMA` returns `odps:Select` permission errors, use DataWorks `table-logic` for field names and lineage, then prove the behavior with business-table SQL.
- If an unqualified table is not found because the gateway defaulted to a `*_dev` project, do not continue in dev. Run `table-logic <table>` or use the production prefix defaults above, then retry with the qualified production table, for example `yh_doc_ads.<table>`.
- If `--evidence-log` cannot create files because the current workspace is read-only or empty, continue without it, state the limitation, and keep concise step updates in the conversation.
- Evidence logs summarize very long strings. When tracing DataWorks logic, always save full node SQL with `--save-node-code` and cite the returned `node_code_path`; do not rely on huge terminal output or a truncated evidence log for exact logic inspection.
- Gateway or terminal encoding may render Chinese values as mojibake. Do not paste mojibake back into SQL as a filter. Prefer stable codes, numeric IDs, date tokens, or the exact Chinese literals supplied by the user. If a Chinese rule type must be constrained and the rendered value is unreliable, anchor by other verified fields or first discover a stable non-Chinese key.

## ADS Rule And Join Multiplication Checks

When a report value is "several times larger" or repeated after ADS/DWD processing:

- First reproduce the user-facing aggregate at the same partition, period/month, organization, salesperson, and adjustment-type definition. Do not compare full latest partitions to filtered screenshots.
- Compare target rows and amounts with the nearest upstream source at a stable grain. Use `count(1)`, `count(distinct <business key>)`, and `sum(<amount>)`; if the target row count and amount both multiply by the same factor, suspect one-to-many joins.
- Find one duplicated business key and fetch several rows. If all business columns are identical except generated IDs such as `unique_id()`, it is a technical join duplication, not a business split.
- Read the DataWorks node only to identify candidate joins, then test each candidate table by counting matches on the exact join key/date/entity from the duplicated sample.
- For rule-table joins, compare broad join counts with exact join counts. A common bug is a fallback join that matches only `organization/department + year` while a salesperson-level code column is non-empty.
- When validating a proposed `IS NULL` fallback condition, always distinguish "left join did not match" from "matched row has NULL" by checking a non-null key from the right table. Also compare `col IS NULL` with `NVL(TRIM(col),'') = ''` so future blank-string entries are handled deliberately.
- Before recommending a fix, simulate current and proposed join semantics with grouped counts: source rows, rule matches, extra rows, affected amount, and any source rows that have no exact rule. Flag those as business-confirmation items rather than assuming they are safe.

## Step Feedback Rule

For complex diagnosis, do not wait until the final answer to show the investigation. After each meaningful step or executed command, send a short progress update to the user with:

- step number or label
- command purpose or SQL purpose
- key result and evidence status
- next step or stop reason

Keep updates concise. Do not paste huge raw rows, full DataWorks node code, secrets, `.env`, `.env.enc`, passwords, or AK/SK. For simple single-command lookups, one concise final answer is enough.

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
python .\scripts\gateway_query.py --json inspect-table <qualified_table> --partition-limit 5000
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
python .\scripts\gateway_query.py --json trace-table <qualified_table> --save-node-code outputs\node_code --compact-node-code
python .\scripts\gateway_query.py --json compare-tables <left_table> <right_table> --key <key_col> --metric <amount_col> --bizdate 20260527
```

Evidence log for long investigations:

```powershell
python .\scripts\gateway_query.py --evidence-log outputs\investigations\case_001\evidence.jsonl --json quick-count <qualified_table> --bizdate latest
```

Controlled small SQL without a partition filter:

```powershell
python .\scripts\gateway_query.py --json sql --no-require-partition "SELECT 1 AS ok" --limit 1
```

## Partition Ambiguity Rules

- Default latest resolution uses MaxCompute `MAX_PT('<qualified_table>')`, not `SHOW PARTITIONS`. Agents should prefer `quick-count --bizdate latest` or `latest-partition` without `--method show-partitions`.
- A row like `["pt=20250921", "pt=20250923"]` from `SHOW PARTITIONS` does not prove there is a `pt2` column.
- Use `SHOW PARTITIONS` only for explicit partition diagnostics. For latest values, avoid manual parsing unless `MAX_PT` fails.
- Use `inspect-table` or `catalog columns` to verify real partition keys.
- If fallback `SHOW PARTITIONS` returns `status: ambiguous`, report the ambiguity and do not continue as if a date was confirmed.
- Use `--method show-partitions --token-index <n>` only after metadata or a human confirms which token position is the business partition.

## Output Contract

Always report:

- command executed
- verified result
- evidence status: `verified`, `ambiguous`, `not_found`, `permission_error`, or `blocked`
- limitations or failed candidates
- knowledge base update: `knowledge_base_update=updated` with file path(s), or `knowledge_base_update=skipped` with reason
- next action only when useful

For complex diagnosis, the final answer should summarize the step-by-step evidence already reported during the process; it must not be the first time the user sees the investigation results.

Do not use nicknames, casual speculation, or "I think". Use "verified" only when a command result supports it.
