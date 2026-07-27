# Manager Portal Sales Achievement Product

## Scope

This note covers the management portal sales achievement product tables:

- `yh_doc_ads.ads_fm_glzmh_xsdc_product`
- `yh_doc_ads.ads_fm_glzmh_xsdc_product_original`

Use production ADS tables. The report is partitioned by `pt`, but the portal date filter is represented by `make_day` inside the latest relevant partition.

## Verified Overall Card Logic

For the overall sales achievement card, first filter to the portal date:

```sql
WHERE pt = '<latest_or_portal_partition>'
  AND make_day = '<portal_date>'
```

Then recompute the overall year-over-year rate from summed amounts:

```sql
(SUM(ljkhsr_bn) - SUM(ljkhsr_qntq)) / SUM(ljkhsr_qntq)
```

Do not sum or average row-level `tbzs`; it is a row-grain ratio and can be distorted by small, zero, or negative same-period denominators.

For PC portal screenshots that match `ads_fm_glzmh_xsdc_product`, use `ljkhsr_qntq` as the same-period assessment income. In the verified case below, `ljkhsr_qntq`, `last_year_accumulate_visa_caliber_income`, and `ljkhsr_qntq_zzjtss` summed to the same total.

## Verified Case: 2026-07-23

Command shape:

```powershell
python .\scripts\gateway_query.py --json sql "
SELECT
  SUM(ljkhsr_bn) AS bn,
  SUM(ljkhsr_qntq) AS qntq,
  (SUM(ljkhsr_bn)-SUM(ljkhsr_qntq))/SUM(ljkhsr_qntq) AS yoy
FROM yh_doc_ads.ads_fm_glzmh_xsdc_product
WHERE pt='20260723' AND make_day='20260723'
"
```

Verified result:

- rows: 359
- assessment income: 72.242347 yi
- same-period assessment income: 72.331704 yi
- yoy: -0.123539%, displayed as -0.1%
- month income: 6.1746 yi
- day income: 3164.08 wan

This matched the portal screenshot that displayed 72.24 yi, 6.17 yi, 0.32 yi, and -0.1%.

## Common Pitfalls

- `ads_fm_glzmh_xsdc_product_original` can produce a different same-period value. For `pt=20260723, make_day=20260723`, it returned assessment income 72.212492 yi, same-period 73.153620 yi, yoy -1.286509%.
- An older partition can produce a value close to -0.8%. For `ads_fm_glzmh_xsdc_product_original` at `pt=20260722, make_day=20260723`, the verified yoy was -0.8725%, but this did not match the portal screenshot.
- Sales amount same-period fields (`xse_qntq`) answer a different metric. For `ads_fm_glzmh_xsdc_product` at `pt=20260723, make_day=20260723`, sales amount yoy was -1.01819%, not the assessment-income yoy shown on the portal card.
- Filtering choices change the result. For `pt=20260723, make_day=20260723`, excluding all Hainan integrated-company rows changed yoy to -0.496592%, while the full portal-matching result was -0.123539%.

## Product vs Product Original

Both ADS tables are produced by separate DataWorks nodes but share the same main source table:

- `yh_doc_ads.ads_fm_glzmh_xsdc_product`: node `210002212517`.
- `yh_doc_ads.ads_fm_glzmh_xsdc_product_original`: node `210002212355`.
- Both read `yh_doc_cdm.dws_fm_mngrprtl_slschvmnt_product`.

The key executable logic difference is that `ads_fm_glzmh_xsdc_product_original` adds this filter immediately after reading the DWS product wide table:

```sql
AND is_reduced = 0
```

`ads_fm_glzmh_xsdc_product` does not have that filter. Therefore, `product` includes `is_reduced=1` rows, while `product_original` excludes them. At upstream `dws_fm_revenue_summary`, `is_reduced=1` is derived from `revenue_tag_name IN (..., 'K97', 'K98')`; in the verified 2026-07-23 case this difference is exactly the K97 amount found in the same-period processed revenue detail.

## Upstream Revenue Chain

For current-year manager-portal assessment income, the main upstream chain is:

```text
yh_doc_cdm.dws_fm_revenue_cost_policy_regional_group_special_full_migration
  -> yh_doc_cdm.dws_fm_revenue_summary
  -> yh_doc_cdm.dws_fm_revenue_daily_accumulation
  -> yh_doc_cdm.dws_fm_mngrprtl_slschvmnt_product
  -> yh_doc_ads.ads_fm_glzmh_xsdc_product
```

For `pt=20260723` and portal date `20260723`, the current 2025/2026 source-detail table used by the revenue summary is `yh_doc_cdm.dws_fm_revenue_cost_policy_regional_group_special_full_migration`, not `yh_doc_cdm.dwd_fm_revenue_cost_history_migration`; the latter is referenced for 2022 historical data in this SQL.

Production filters at the policy-detail layer include:

```sql
pt='20260723'
AND assessment_group_cd_zx='51026719'
AND CASE
      WHEN assessment_org_cd_zx = '50091274' AND assessment_dep_cd = '50081702' THEN 1
      WHEN assessment_org_cd_zx = '51027084' AND assessment_dep_cd IN ('51027428','51027526','51027525') THEN 1
      ELSE 0
    END = 0
```

Verified source-detail YTD result:

- 2026 YTD through `20260723`: 74.714773 yi
- 2025 same period through `20250723`: 72.005390 yi
- source-detail yoy: 3.762750%

Verified daily-accumulation result:

- `dws_fm_revenue_daily_accumulation`, `pt=20260723`, `make_day=20260723`, `is_tb=0`: 74.714773 yi
- same table, `make_day=20250723`, `is_tb=0`: 72.016676 yi
- daily-accumulation yoy: 3.746490%

These upstream full-source values do not match the portal card directly because `ads_fm_glzmh_xsdc_product` later applies manager-portal organization and department scope. The portal card should still be reconciled from the final ADS table unless the task explicitly asks for upstream full-source revenue.

## Same-Period Processed Revenue Detail

`yh_doc_ads.ads_fm_revence_cost_new_assessment_details` is the ADS table commented as `manager portal same-period processed revenue detail` (`管理者门户-同期处理收入明细表`). The table name is spelled `revence` in production. It is partitioned by `pt`, has business date `calday`, year `kh_year`, base assessment income `dmbtr_dy`, and latest same-period organization fields such as `assessment_group_cd_zx`.

For `pt=20260723`, using latest same-period organization:

```sql
WHERE pt='20260723'
  AND kh_year='2025'
  AND calday>='20250101'
  AND calday<='20250723'
  AND assessment_group_cd_zx='51026719'
```

Verified result:

- same-period processed revenue detail: 72.005390 yi
- original `assessment_group_cd='51026719'` portion: 71.782579 yi
- original `assessment_group_cd='50099044'` remapped into latest construction group: 0.222811 yi
- exclusion-rule check for `assessment_org_cd_zx='50091274' AND assessment_dep_cd='50081702'` and `assessment_org_cd_zx='51027084' AND assessment_dep_cd IN ('51027428','51027526','51027525')`: no rows under the latest-group filter above

For the same partition and latest organization filter, the detail table's 2026 YTD through `20260723` is 74.714773 yi, so the detail-table-only yoy is 3.762750%. This is not the portal overall card yoy, because the final card uses `ads_fm_glzmh_xsdc_product` after later manager-portal product scope handling.

Comparison for `pt=20260723, make_day=20260723`:

```text
ads_fin_income_cost_detail_assess_mkt, grp_cd='51026719'          71.757847 yi
ads_fm_revence_cost_new_assessment_details, latest org           72.005390 yi
ads_fm_glzmh_xsdc_product, SUM(ljkhsr_qntq)                      72.331704 yi
```

Thus this processed detail table explains the income-table to latest-organization step, but it is still 0.326314 yi below the final portal product same-period total.

Detailed reconciliation from `ads_fm_revence_cost_new_assessment_details` to the final portal product table at company grain:

- Most normal companies match exactly after grouping by organization company code. Examples: Jiangsu `50091261`, Zhejiang `50091262`, Guangdong `50091275`, Hainan construction `51027084`, and Industrial Building System `50086666` all had equal `revence` and final-portal same-period totals.
- The largest positive bridge is that `revence` rows with `assessment_org_cd_zx IS NULL` total -4.279973 yi. The final portal table has no null-organization bucket, so this contributes +4.279973 yi when moving from `revence` to portal.
- The final portal table adds an HGDQ/other organization bucket totaling -2.500583 yi, mainly `assessment_dep_cd='GSB'` / other at -2.474440 yi and `assessment_dep_cd='51017352'` / China Construction Eighth Engineering business group at -0.029118 yi, offset by Green Land partner business department +0.002975 yi.
- The final portal table excludes `revence`-only organizations totaling about 1.453076 yi. Main examples are Repair Company `51080197` 0.976634 yi, Building Rubber Business Unit `50110586` 0.181364 yi, Sports Flooring Business Unit `51060073` 0.109806 yi, South China Marketing Business Unit `51052656` 0.085583 yi, and Market Technology Enablement Center `51037858` 0.064211 yi.

Therefore:

```text
revence latest-org same-period detail                         72.005390 yi
remove null-org negative bucket effect                        +4.279973 yi
add final portal HGDQ/other bucket                            -2.500583 yi
drop revence-only organization scope                          -1.453076 yi
final portal product same-period                              72.331704 yi
```

Row examples:

- `revence` repair-company row not present in final portal scope: `assessment_org_cd_zx='51080197'`, customer `0072113439`, order `G0230097`, `calday='20250102'`, amount 28.7050 wan.
- `revence` null-organization negative row: customer `0060384895`, order `B0240059`, `calday='20250106'`, `assessment_org_cd_zx IS NULL`, amount -147.9277 wan.

## K97 Exclusion Handling

Use `revenue_tag_name`, not voucher type fields, to identify K97 in the manager-portal same-period processed revenue detail and upstream policy-detail models. In the verified `pt=20260723` case, `fkart='K97'` returned no rows in `ads_fm_revence_cost_new_assessment_details`, while `revenue_tag_name='K97'` returned the expected rows.

For `pt=20260723`, latest organization filter `assessment_group_cd_zx='51026719'`:

| scope | period | total yi | K97 yi | K97 rows |
| --- | --- | ---: | ---: | ---: |
| `ads_fm_revence_cost_new_assessment_details` | `kh_year='2025'`, `calday` 20250101-20250723 | 72.005390 | -0.821916 | 7,480 |
| `ads_fm_revence_cost_new_assessment_details` | `kh_year='2026'`, `calday` 20260101-20260723 | 74.703531 | 0.029854 | 278 |

This K97 amount explains the latest `product` vs `product_original` totals for the overall card:

```text
ads_fm_glzmh_xsdc_product current income            72.242347 yi
minus 2026 K97                                      -0.029854 yi
= ads_fm_glzmh_xsdc_product_original current income 72.212492 yi

ads_fm_glzmh_xsdc_product same-period income        72.331704 yi
minus 2025 K97                                      +0.821916 yi
= ads_fm_glzmh_xsdc_product_original same-period    73.153620 yi
```

The same 2025 K97 amount also appears in `yh_doc_cdm.dws_fm_mngrprtl_slschvmnt_product` as `is_reduced=1` for `pt=20260723, make_day=20260723`:

| `is_reduced` | rows | same-period assessment income yi |
| ---: | ---: | ---: |
| 0 | 998 | 72.838591 |
| 1 | 318 | -0.821916 |

The model chain loses exact K97 identity downstream:

- `yh_doc_cdm.dws_fm_revenue_cost_policy_regional_group_special_full_migration` still has `revenue_tag_name`.
- `yh_doc_cdm.dws_fm_revenue_summary` reads that table and converts `revenue_tag_name IN (..., 'K97', 'K98')` to `is_reduced=1`.
- `yh_doc_cdm.dws_fm_revenue_daily_accumulation` and `yh_doc_cdm.dws_fm_mngrprtl_slschvmnt_product` keep only `is_reduced`.
- `yh_doc_ads.ads_fm_glzmh_xsdc_product` does not expose `revenue_tag_name` or `is_reduced`; its `ljkhsr_qntq` is selected from the aggregated DWS same-period assessment income field.

Therefore, final ADS `ads_fm_glzmh_xsdc_product` cannot precisely exclude only K97 after the fact. Filtering `is_reduced=1` downstream is not generally safe, because `is_reduced=1` also represents K98 and other income/profit reduction tags in the revenue summary logic. For a manager-portal-only change, the recommended model touchpoint is `yh_doc_cdm.dws_fm_revenue_summary`, in the CTE that reads `yh_doc_cdm.dws_fm_revenue_cost_policy_regional_group_special_full_migration`, before `revenue_tag_name` is collapsed to `is_reduced`.

If the business requirement is only to change the portal same-period metric, avoid a global `revenue_tag_name <> 'K97'` filter that would also change current-year metrics and other downstream consumers. Prefer adding a manager-portal K97-excluded same-period metric, or applying the K97 exclusion in a manager-portal-specific branch before the daily accumulation/product ADS aggregation.

If the requirement is specifically to keep `ads_fm_glzmh_xsdc_product` current-year values unchanged while changing only same-period fields to `is_reduced=0`, do not add `AND is_reduced=0` to the DWS source `WHERE`; that would make current-year metrics follow the `product_original` policy too. Instead:

1. In the `fm_glzmh_xsdc_product` CTE reading `yh_doc_cdm.dws_fm_mngrprtl_slschvmnt_product`, add `is_reduced` to the selected fields.
2. In `fm_glzmh_xsdc_product_a`, change the relevant same-period revenue/profit aggregations from plain `SUM(last_year_...)` to conditional sums, for example:

```sql
SUM(CASE WHEN t.is_reduced = 0 THEN last_year_accumulate_assessment_income ELSE 0 END) AS lysm_yrccmlt_ssssmntncm
```

The verified expected overall card effect for `pt=20260723, make_day=20260723`, if current-year income stays from `product` and same-period income takes the `is_reduced=0` result from `product_original`, is:

- current income: 72.242347 yi
- same-period income: 73.153620 yi
- yoy: -1.245698%

## Income Table Model Cross-Check

The policy-detail layer above is itself sourced from the finance assessment income table model:

```text
yh_doc_cdm.dwd_fin_voucher_f_link
  -> yh_doc_cdm.dwd_fin_voucher_link
  -> yh_doc_cdm.dws_fin_income_cost_detail_assess_base_tmp
  -> yh_doc_cdm.dws_fin_income_cost_detail_assess
  -> yh_doc_cdm.dws_fin_income_cost_detail_profit_exclusion
  -> yh_doc_cdm.dws_fin_income_cost_detail_assess_mkt
  -> yh_doc_cdm.dws_fm_revenue_cost_policy_regional_group_special_full_migration
```

For `pt=20260723`, YTD through `20260723` vs same period through `20250723`, using the income-table model's direct group filter `grp_cd='51026719'`:

| layer | 2026 YTD yi | 2025 same-period yi | yoy |
| --- | ---: | ---: | ---: |
| `dwd_fin_voucher_f_link`, income subjects, `-SUM(assess_vouch_amt)` | 136.139575 | 136.172522 | -0.024195% |
| `dwd_fin_voucher_link`, income subjects, `-SUM(assess_vouch_amt)` | 136.139575 | 136.172522 | -0.024195% |
| `dws_fin_income_cost_detail_assess_base_tmp`, `income_cost_flag='income'`, `remove_flag=1`, `-SUM(assess_vouch_amt)` | 72.214232 | 72.561468 | -0.478541% |
| `dws_fin_income_cost_detail_assess`, `SUM(income_amt_assess)` | 72.214232 | 72.584414 | -0.510002% |
| `dws_fin_income_cost_detail_profit_exclusion`, `SUM(income_amt_assess)` | 72.214232 | 71.762498 | 0.629484% |
| `dws_fin_income_cost_detail_assess_mkt`, `SUM(income_amt_assess)` | 72.242347 | 71.757847 | 0.675187% |
| `ads_fin_income_cost_detail_assess_mkt`, `SUM(income_amt_assess)` | 72.242347 | 71.757847 | 0.675187% |

The direct income-table MKT layer matches the portal ADS current-year amount (`72.242347 yi`) but not the portal ADS same-period amount (`72.331704 yi`). The same-period gap is introduced after the MKT layer by the manager-portal revenue policy and organization remapping logic, including old-organization mapping and sand-powder-to-construction transfer rules in `dws_fm_revenue_cost_policy_regional_group_special_full_migration`.

For the 2025 same-period side of `pt=20260723, make_day=20260723`, the gap from `ads_fin_income_cost_detail_assess_mkt` to the portal product ADS is:

```text
ads_fin_income_cost_detail_assess_mkt, grp_cd='51026719'          71.757847 yi
policy detail, assessment_group_cd_zx='51026719'                  72.005390 yi
dws_fm_revenue_daily_accumulation, make_day='20250723'            72.016676 yi
ads_fm_glzmh_xsdc_product, make_day='20260723', SUM(ljkhsr_qntq)  72.331704 yi
```

Main differences:

- `ads_fin_income_cost_detail_assess_mkt` -> policy detail: `+0.247543 yi`.
  - Raw `assessment_group_cd='51026719'` contributes `71.782579 yi`, which is `+0.024732 yi` over the direct MKT `grp_cd='51026719'` amount.
  - Raw `assessment_group_cd='50099044'` (涂料砂粉科技集团) contributes `+0.222811 yi` after `assessment_group_cd_zx='51026719'`, mainly mapped to 工建海南公司 (`0.222716 yi`) and a small 澄迈工厂 amount (`0.000095 yi`).
- Policy detail -> final portal product ADS: `+0.326314 yi`.
  - Policy rows with `assessment_org_cd_zx IS NULL` total `-4.279973 yi`; final ADS maps only part of this to `assessment_org_cd='HGDQ'` / `其它`, total `-2.500583 yi`, net uplift `+1.779390 yi`.
  - Final ADS scope drops policy-only organizations totaling `-1.453076 yi`, mainly 修缮公司 `0.976634 yi`, 建筑橡胶事业部 `0.181364 yi`, 运动地坪事业部 `0.109806 yi`, 华南营销事业部 `0.085583 yi`, 市场技术赋能中心 `0.064211 yi`, 市场中心 `0.011870 yi`, plus small items.

Therefore the same-period difference versus `ads_fin_income_cost_detail_assess_mkt` is not a single source-table amount error. It is mostly manager-portal organization remapping plus final ADS display-scope handling.
