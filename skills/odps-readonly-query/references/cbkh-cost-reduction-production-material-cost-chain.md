# CBKH Cost Reduction Production Material Cost Chain

## Scope

- Primary table: `yh_doc_ads.ads_cbkh_cost_reduction_rate_production_material_cost`
- Business perspective: production cost reduction / material consumption.
- Verified partition: `pt=20260701`.

## Lineage

The ADS node `210002298495` reads production and material-consumption data from:

- `yh_doc_cdm.dws_fm_factory_expense_details`
- `yh_doc_cdm.dim_factory_migration`
- `yh_doc_cdm.dim_benchmarking_factory_splite`
- supporting material, price, inventory, and manual baseline tables.

The main `bq` CTE has two branches:

- Normal branch: product output `cl` left joins material consumption `ylhy` on month, product, and factory.
- OEM sand-powder branch: `oem_cl` joins `oem_ylhy`, where `oem_ylhy` maps source consumption factory through `dim_factory_migration.factory_cd -> company_cd`.

## Verified OEM Factory Mapping Behavior

For sand-powder group rows, `dim_factory_migration` can map an `SF*` factory to a `YH*` manufacturing company. In the OEM branch, the mapped `company_cd` becomes the output factory key used by ADS.

Verified example:

- `dim_factory_migration`, `pt=20260701`: `factory_cd=SFXY`, `company_cd=YH53`, `business_flag=sand-powder group`.
- Product `YH-B100-20`, month `202605`: source `SFXY` has consumption rows, while source `YH53` has product output.
- Reproducing the ADS OEM branch returns `output_factory_cd=YH53`, `source_consum_factory_cd=SFXY`, `product_yield=79`, and SFXY consumables such as `10105005-025` with quantity `1229.62` and cost `271.33`.

Therefore, ADS rows showing `werks_cd=YH53` for a product also produced by `SFXY` may be expected when the OEM branch attributes sand-powder consumption to the mapped manufacturing company.

## Diagnostic Query Pattern

Use the latest partition first, then compare these fields:

- ADS: `werks_cd`, `werks_nm`, `benchmarking_factory`, `product_cd`, `month`, `consumables_cd`, `current_period_finished_product_yield_num`, `current_material_consumption_num`, `actual_material_cost_amt`.
- Source: `dws_fm_factory_expense_details.factory_cd`, `index_cd`, `MENGE`, `DMBTR`.
- Mapping: `dim_factory_migration.factory_cd`, `company_cd`, `business_flag`.

When ADS shows an unexpected `YH*` factory, check whether an `SF*` source factory maps to that `YH*` company and whether the ADS row's consumption matches the `SF*` source consumption.
