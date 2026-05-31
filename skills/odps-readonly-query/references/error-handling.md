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
