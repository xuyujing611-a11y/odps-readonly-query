# Error Handling

Use this reference when a command fails, returns ambiguous data, or exposes schema uncertainty.

## Gateway Unavailable

If `gateway_query.py` cannot connect:

1. Do not ask for `.env.enc` or password.
2. Ask the human to run `python .\scripts\start_gateway.py`.
3. Retry the original command after the user confirms the gateway is running.

## Unauthorized Gateway

If a gateway request returns `401 unauthorized`, the token in `gateway_state.json` may not match the running process.

Ask the human to restart `start_gateway.py`, then retry.

## Partition Ambiguity

If output contains `status: ambiguous`:

1. Report the ambiguity.
2. Run or request `inspect-table` / `catalog columns`.
3. Do not invent a column such as `pt2`.
4. Use `--token-index` only after metadata or the human confirms the correct token position.

## Catalog Permission Failure

If `SYSTEM_CATALOG.INFORMATION_SCHEMA` fails:

1. Report catalog permission failure.
2. Continue with `trace-table` when lineage or DataWorks node logic is needed.
3. Use `sample` to infer available fields when safe and partition-scoped.

## Field Not Found

If a query says a column cannot be resolved:

1. Stop using that field.
2. Run `inspect-table` or `sample`.
3. Retry with only confirmed fields.

## Empty Result

If a query returns no rows:

1. Verify table name and production prefix.
2. Verify partition date.
3. Check whether the key exists in upstream tables.
4. Report `not_found`, not a business conclusion.

## Multiple DataWorks Nodes

If `trace-table` returns multiple candidates:

1. Do not assume equal node names mean equal logic.
2. Check `node_role`, `node_id`, `project_id`, `connection`, `file_type`, and `matched_output`.
3. Prefer an exact qualified-output match and the producer role appropriate for the target table. Treat `hologres_sync` as downstream synchronization unless the user is specifically investigating Hologres loading.
4. Rerun with `--node-id <id> --require-single-node`; optionally add `--project-id`, `--connection`, `--file-type`, or `--matched-output`.
5. If selection still resolves to zero or multiple candidates, report `ambiguous`. Do not switch to a similarly named `_da`, dev, legacy, or unqualified table.

Example:

```powershell
python .\scripts\gateway_query.py --json trace-table yh_doc_ads.example `
  --node-id 210000000000 `
  --project-id 121893 `
  --connection yh_doc_ads `
  --require-single-node `
  --save-node-code outputs\node_code `
  --compact-node-code
```

## Legacy Namespace Warning

References to `dfyh_*`, `_da`, or another legacy namespace inside a verified current producer may be legitimate upstream dependencies. They are a warning to inspect, not automatic proof of a wrong node. However, never use a legacy node as a substitute merely because the current node code was not saved or is unavailable.
