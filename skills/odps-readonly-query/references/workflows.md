# Workflows

Use this reference for long-chain diagnosis, lineage tracing, and bug localization.

## Evidence Discipline

For multi-step work, append command results to a local evidence log:

```powershell
python .\scripts\gateway_query.py --evidence-log outputs\investigations\<case>\evidence.jsonl --json <command>
```

Keep final answers grounded in that evidence:

- `verified`: supported by a command result.
- `ambiguous`: tool returned ambiguous status or multiple valid candidates.
- `not_found`: lookup ran and returned no useful match.
- `permission_error`: catalog or DataWorks read failed because of permissions.
- `blocked`: gateway or required human input is missing.

## Depth Policy

Match effort to the question.

- Simple查数: answer after the smallest safe verified command, such as `quick-count`, `sample`, `field-profile`, or `inspect-table`. Do not trace upstream just because a table has lineage.
- Diagnostic question: continue until the cause is tied to the finest useful grain that read-only access can prove: exact filter, partition, source row, unmatched key, order, account, material, partner, or amount bucket.
- Business口径 question: verify both the SQL logic and at least one data result. Node code can describe the rule, but a query must confirm how current data behaves.
- Bug定位: prove the failing row or missing row at each important layer before naming the broken layer.

## SQL Verification Rule

Every non-trivial conclusion must cite an executed command or SQL result.

- Prefer gateway commands first: `inspect-table`, `trace-table`, `compare-tables`, `sample`, `field-profile`, and partition-scoped `sql`.
- Keep SQL partition-scoped whenever the table is partitioned.
- For "missing data" claims, run both positive and negative checks where practical: target table not found, upstream/source found, then the filter or join that drops it.
- For "amount/count difference" claims, verify aggregate totals and then drill into representative keys.
- If a conclusion comes only from reading DataWorks node SQL, label it `not verified` until a data query confirms it.

## Bottom Table And Source Row Rule

When the user asks "why" or "定位bug", do not stop at the first plausible DWS/ADS explanation.

1. Start from the exact object the user gave: table, order, partner, material, account, date, or metric.
2. Resolve the actual partition and schema.
3. Read the table logic with `trace-table`.
4. Extract upstream tables from the node SQL; do not invent names.
5. Query each relevant layer only as far as needed to prove where the value appears, changes, disappears, or duplicates.
6. Stop at the bottom-most useful evidence available through read-only access, such as ODS/source row, exact join miss, filter condition, partition mismatch, or unmatched bucket.

## Long-Chain Bug Diagnosis

1. Restate target object and date: table, key, amount, order, material, partner, or agent.
2. Run `inspect-table` on the user-facing or ADS table.
3. Resolve exact partition and stop if partition status is ambiguous.
4. Run `trace-table` on the ADS/DWS table to inspect DataWorks node SQL and schedule.
5. Identify upstream tables from node SQL. Do not invent upstreams.
6. Use `compare-tables` for source-vs-target differences when both tables share key and metric columns.
7. Drill down with targeted partition-scoped SQL or `sample`.
8. Stop only when the root cause is tied to the finest useful grain, such as order, account, material, source row, or unmatched bucket.

## Stop Conditions

Use these labels instead of over-claiming:

- `verified`: command output proves the answer at the required depth.
- `ambiguous`: partition, schema, key mapping, or multiple candidate causes cannot be disambiguated yet.
- `not_found`: the searched row/key/table was checked and absent.
- `permission_error`: a read-only metadata, catalog, or DataWorks lookup failed because of permissions.
- `blocked`: gateway is unavailable, human password entry is needed, or a required local file is missing.

When blocked before bottom-table proof, report the deepest verified layer and the exact next command or human action that would continue the investigation.

## ADS vs DWS Difference

Start with aggregate comparison:

```powershell
python .\scripts\gateway_query.py --json compare-tables <ads_table> <dws_table> --key <key_col> --metric <amount_col> --bizdate 20260527
```

Then inspect the largest `amount_diff` or `cnt_diff` rows with targeted SQL.

## Table Logic And Schedule

Use:

```powershell
python .\scripts\gateway_query.py --json trace-table <qualified_table>
```

If catalog fails but DataWorks succeeds, report both facts: catalog permission failed, DataWorks read-only lookup succeeded.

Do not paste very long `node_code` unless requested. Summarize the SQL and save evidence locally when useful.

## Final Answer Shape

Use this shape for complex diagnosis:

```text
Conclusion:
Evidence:
Commands:
Limitations:
Next step:
```

Do not use casual guesses. Use "not verified" when evidence is incomplete.
