# Query Recipes

Use these recipes after the Mode B gateway is already running.

## Quick Count

Use when the user asks for row counts, latest partition counts, or "how many rows".

1. Run:

```powershell
python .\scripts\gateway_query.py --json quick-count <qualified_table> --bizdate latest
```

2. `--bizdate latest` resolves the partition with `MAX_PT('<qualified_table>')` first. Do not parse `SHOW PARTITIONS` output for normal latest-count work.
3. If `status` is `ok`, report `partition_value`, `row_cnt`, and the `latest_partition.method`.
4. If fallback `SHOW PARTITIONS` returns `status` as `ambiguous`, stop and report `candidates_by_token_index`. Do not choose a token.
5. Use `--method show-partitions --token-index <n>` only after metadata or the human confirms the token position.
6. If the user gives an exact date, run:

```powershell
python .\scripts\gateway_query.py --json quick-count <qualified_table> --bizdate 20260527
```

## Table Inspection

Use before explaining schema or partition behavior:

```powershell
python .\scripts\gateway_query.py --json inspect-table <qualified_table>
```

Report `partition_keys`, `latest_partition.status`, and any catalog permission errors.

## Safe Sample

Use when field names are uncertain or `DESC`/catalog fails:

```powershell
python .\scripts\gateway_query.py --json sample <qualified_table> --bizdate 20260527 --limit 20
```

Use only fields that appear in sample rows, catalog columns, or DataWorks SQL.

## Field Profile

Use for top values, code distribution, and null-like diagnosis:

```powershell
python .\scripts\gateway_query.py --json field-profile <qualified_table> <field> --bizdate 20260527 --limit 50
```

Run after confirming `<field>` exists.

## Controlled Raw SQL

Use raw `sql` only when the built-in commands are insufficient:

```powershell
python .\scripts\gateway_query.py --json sql "SELECT COUNT(1) AS row_cnt FROM <table> WHERE pt = '20260527'"
```

Keep raw SQL read-only and partition-scoped.
