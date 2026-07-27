# ads_emf_werks_storage_age

## Scope

`yh_doc_ads.ads_emf_werks_storage_age` is the factory/material inventory aging table. It is produced by PROD DataWorks node `210002302945`.

## Verified Redundancy Logic

Verified on `2026-07-21` with `trace-table yh_doc_ads.ads_emf_werks_storage_age` and read-only SQL against `pt=20260720`.

The ADS model computes:

- `redundancy_cycle`: `NVL(TRIM(dwi_mdm_wljc_query.desc97), '180')`
- `redundancy_qty`: `stock_qty_z` when `storage_age > redundancy_cycle`, otherwise `0`
- `redundancy_minqty`: `redundancy_qty * material_category_nm`
- `redundancy_amt`: `redundancy_qty * price`

`dwi_mdm_wljc_query.desc97` is normalized to days according to `desc60`; blank cycle values default to `180`.

## Aging Allocation Pattern

The model first computes current stock from filtered SAP material-document movements in `yh_doc_cdm.dwi_sap_matdoc`.

For aging source rows, it uses only non-cancelled positive movements where:

- `shkzg = 'S'`
- `bwart in ('101','131','411','501','531','561')`
- or `bwart = '301' and werks <> umwrk`

The model sorts those aging source rows by `budat desc, cputm desc`, builds a running sum, and allocates the current stock quantity back to the most recent eligible source rows. Positive movements such as `309`, `644`, and `673` can affect the stock balance but are not aging source rows under the current logic.

## Case: HS-VP1813 / RY01

For `matnr='HS-VP1813'`, `werks='RY01'`, `pt='20260720'`, `month_id='202607'`:

- ADS current stock: `43,425`
- unit price from ADS stock amount: `522,837 / 43,425 = 12.04`
- material redundancy cycle: `180` days from `dwi_mdm_wljc_query`
- ADS redundancy quantity: `950`
- ADS redundancy amount: `11,438`

The `950` comes from two allocated 101 receipt rows:

| mblnr | zeile | budat | bwart | allocated qty | storage age |
|---|---:|---:|---:|---:|---:|
| 5015121634 | 0001 | 20251124 | 101 | 900 | 238 |
| 5013644756 | 0001 | 20241209 | 101 | 50 | 588 |

Both source rows are older than the 180-day cycle, so ADS marks the full `900 + 50 = 950` as redundant.

A contrast simulation that treated all positive movements as aging receipt sources allocated the `43,425` stock to movements aged 0-4 days and produced simulated redundancy `0`. Treat this as a business-rule confirmation item, not a data correction by itself.
