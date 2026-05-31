# Project Context

Use this reference for the original user's ODPS naming conventions. Other teams can replace this file with their own conventions.

## Production Prefixes

When the user gives an unqualified table name:

- `ads_` or report-style table: try `yh_doc_ads.<table>` first.
- `ods_`: try `yh_doc_ods.<table>` first.
- `dwd_`, `dws_`, `dim_`, `fact_`: try `yh_doc_cdm.<table>` first.
- Otherwise try `yh_doc_cdm.<table>`, then `yh_doc_ads.<table>`, then `yh_doc_ods.<table>`.

If the user gives a fully qualified table, use it exactly.

## Partition Convention

Business-date partitions are usually named `pt`, but this must be verified with `inspect-table` when output is confusing.

## Diagnosis Preference

When the user gives a concrete key, material, agent, order, or partner, start from that object. Do not scan whole tables first unless targeted lookups fail.

For discrepancy diagnosis, keep drilling until the answer reaches the finest useful grain: order, account, material, source row, cash flow record, or unmatched bucket.
