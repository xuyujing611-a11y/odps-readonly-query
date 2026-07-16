# 渠道商产值表链路

用于排查用户口语里的“渠道商产值表”、`dwd_fm_distributor_detail_hxzzu_migration`、渠道商资产产值初始明细表。

## 主表

- `yh_doc_cdm.dwd_fm_distributor_detail_hxzzu_migration`：最终渠道商产值表，表注释为“渠道商产值表”。
- `yh_doc_cdm.dwd_fm_distributor_detail_initial_migration`：初始明细，表注释为“渠道商资产产值初始明细表”。

## 核心逻辑

- 最终表读取初始明细 `dwd_fm_distributor_detail_initial_migration`，再按客户合并关系、组织、集团维度汇总资产、产值、回款等指标。
- 初始明细从 `dwi_erm_yh_contract_main` 取合同，基础过滤是 `contract_status = '19'` 且 `contract_sort_2 IN ('GH','ZH','GK','ZK')`。
- 最终展示框架合同只保留 `GK/ZK`。生产 SQL 先用 `tmp_main.COL1 = 1` 取客户、合同类型、业务员维度的最新合同，再在 `tmp_main_final` 用 `rn = 1` 取客户、组织维度的最新合同。
- 合同客户信息来自 `dwi_erm_yh_client_info`；授权信息来自 `dwi_erm_yh_contract_framework` 和 `dwi_erm_yh_framework_auth_area`；产值来自 `dwd_order_shipment_split` 和 `dws_mks_order_shipment_split_multiple`；回款来自 `dwd_fm_collection_detail_policy_final`。

## 排查模板

1. 查最终表最新分区是否有合同和客户：

```sql
SELECT COUNT(1), MAX(info_client_name), MAX(b_contract_start_date), MAX(z_contract_end_date)
FROM yh_doc_cdm.dwd_fm_distributor_detail_hxzzu_migration
WHERE pt = '<pt>'
  AND contract_code = '<contract_code>';
```

2. 查初始明细是否已经缺失：

```sql
SELECT COUNT(1), MAX(info_client_name), MAX(contract_start_date), MAX(contract_end_date)
FROM yh_doc_cdm.dwd_fm_distributor_detail_initial_migration
WHERE pt = '<pt>'
  AND contract_code = '<contract_code>';
```

3. 查合同源表是否满足基础规则：

```sql
SELECT contract_code, contract_sort_2, contract_status, contract_start_date,
       contract_end_date, executor_code, executor_unit_code, create_time, etl_date
FROM yh_doc_cdm.dwi_erm_yh_contract_main
WHERE pt = '<pt>'
  AND contract_code = '<contract_code>';
```

4. 对同一客户、组织按生产排序复算 `rn`，验证重跑后会保留哪份合同：

```sql
WITH src AS (
  SELECT cm.contract_code, ci.info_client_encode, ci.info_client_name,
         cm.contract_sort_2, cm.contract_status, cm.contract_start_date,
         cm.contract_end_date, cm.executor_code, cm.executor_unit_code,
         cm.create_time, cp.assessment_org_cd, cp.assessment_org_nm
  FROM yh_doc_cdm.dwi_erm_yh_contract_main cm
  LEFT JOIN yh_doc_cdm.dwi_erm_yh_client_info ci
    ON cm.id = ci.contract_id AND ci.pt = '<pt>'
  LEFT JOIN yh_doc_cdm.dim_company_prd_migration cp
    ON cm.executor_unit_code = cp.unit_code AND cp.pt = '<pt>' AND cp.days = '<pt>'
  WHERE cm.pt = '<pt>'
    AND ci.info_client_encode = '<customer_code>'
    AND cm.contract_status = '19'
    AND cm.contract_sort_2 IN ('GK','ZK')
),
ranked AS (
  SELECT src.*,
         ROW_NUMBER() OVER (
           PARTITION BY info_client_encode, assessment_org_cd
           ORDER BY create_time DESC, contract_start_date DESC, contract_end_date DESC
         ) AS final_rn
  FROM src
)
SELECT *
FROM ranked
ORDER BY final_rn, create_time DESC;
```

## 已验证案例

- `pt=20260715`，客户 `72091116`（宜昌富祥劳务服务有限公司），合同 `YG01-GK-2026-0252`。
- 当前合同源表中该合同存在，`contract_status='19'`，`contract_sort_2='GK'`，客户和组织可补齐，按当前源表复算会排 `final_rn=1`。
- 但 `dwd_fm_distributor_detail_initial_migration` 和 `dwd_fm_distributor_detail_hxzzu_migration` 在该分区仍保留旧合同 `6JGK190109`。
- 细因是刷新时序：下游初始明细最后修改时间 `2026-07-16 07:31:03`，最终表最后修改时间 `2026-07-16 07:40:59`；合同源表 `dwi_erm_yh_contract_main` 最后修改时间 `2026-07-16 12:31:55`，目标合同源表 `etl_date=2026-07-16 12:31:47`。下游加工早于包含新合同的源表刷新。
