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

## Long-Chain Bug Diagnosis

1. Restate target object and date: table, key, amount, order, material, partner, or agent.
2. Run `inspect-table` on the user-facing or ADS table.
3. Resolve exact partition and stop if partition status is ambiguous.
4. Run `trace-table` on the ADS/DWS table to inspect DataWorks node SQL and schedule.
5. Identify upstream tables from node SQL. Do not invent upstreams.
6. Use `compare-tables` for source-vs-target differences when both tables share key and metric columns.
7. Drill down with targeted partition-scoped SQL or `sample`.
8. Stop only when the root cause is tied to the finest useful grain, such as order, account, material, source row, or unmatched bucket.

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
