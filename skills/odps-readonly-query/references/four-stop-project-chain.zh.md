# 四停项目信息表链路

## 已验证回款识别规则（2026-07-22）

- `dwd_fm_collection_detail` 的报表 WBS 来自 SAP `BSEG.KIDNO`；材料销售直属客户按 `WBS + 付款方` 关联 `dim_receivable_contract_migration` 补充合同。
- 共享平台的收款/认领单审批结束，不代表已经计入应收报表回款。只有有效 SAP 回款凭证以正确 WBS/合同进入 `dwd_fm_collection_detail` 后，金额才会影响 `dmbtr_hk_acc`。
- 银行流水若 `userd_amount=0`、`occupy_amount=0` 且 `balance_amount=total_amount`，则对本报表仍是未使用状态，即使关联单据为 `bill_status='END_APPROVAL'`。
- 生产案例：WBS `X-YH10260223`、合同 `YH10-ZX-2026-0225`、付款方 `0060286965`、`pt=20260721`。两笔银行流水合计 945,000 元但全部未使用，因此报表 `dmbtr_hk_acc=0`、`ar_due_amount=283,500`。其中 300,000 元 SAP 凭证被记到 WBS `X-YH10260150` / 合同 `YH10-ZX-2026-0155`，之后又全额冲销。按生产直属客户公式只读模拟，若 945,000 元有效计入目标 WBS，到期应收和应收余额都会降为 0。

## 适用范围

- 报表：`yh_doc_ads.ads_information_of_the_four_stop_project`
- 业务主题：四停项目、到期应收、未四停、集采宽限、未冲减应收票据

## 已验证生产链路

1. `yh_doc_ads.ads_information_of_the_four_stop_project` 的生产节点是 `210002417707`。
2. 该 ADS 从 `${space_name_ads}.ads_fk_siting_new` 读取到期应收四停数据；生产环境对应 `yh_doc_ads.ads_fk_siting_new`。ADS 不以 `ar_due_amount > 0` 直接重算四停状态，只在 RM09 解停或风控手工流程场景覆盖状态。
3. 上游 `yh_doc_ads.ads_fk_siting_new` 的生产节点是 `210002286563`，主要输入包括：
   - `yh_doc_ads.ads_fm_accounts_receivable_policy_final`：到期应收与账龄；
   - `yh_doc_cdm.dwi_menhu_uf_jcstgl`：集采项目名单；
   - `yh_doc_cdm.dim_sbxm`：双包拆分；
   - `yh_doc_cdm.dim_yjfx_split`：移交风险；
   - `yh_doc_cdm.dwi_mks_v_yh_no_receivable_amount`：未冲减应收票据金额。

旧湖仓的 `dfyh_ads.ads_fk_siting_new_ha`、`dfyh_dim.dim_menhu_yh_uf_jcstgl_ha`、`dfyh_dwd.dwd_mks_v_yh_no_receivable_amount_ha` 不属于当前 `yh_doc_ads.ads_information_of_the_four_stop_project` 的生产链路，不应作为新湖仓问题的实体证据。

## 四停判定关键规则

- 集采项目：按 WBS+客户命中 `dim_menhu_yh_uf_jcstgl_ha` 后，只有
  `ar_due_amount - aging_due_1m - aging_due_2m > 0.01`
  才进入“到期应收四停（集采项目）”。因此集采项目可以有到期应收，但若全部位于 1、2 月账龄，仍为未四停。
- 其他项目：排除移交风险、双包拆分、集采名单后，只有
  `ar_due_amount - NVL(no_receivable_amount, 0) > 0.01`
  才进入到期应收四停。
- 其他项目为“材料销售”时，还要求合同号非空。
- `is_due_3m_above` 来自 3 月及以上账龄求和是否非零；它是账龄说明字段，不等同于最终四停状态。
- `ar_due_amount` 是到期应收展示/输入金额，不等同于最终四停净额。判断“有到期应收却未四停”时，必须同时检查集采名单、1/2 月账龄、未冲减应收票据、双包/移交规则、项目类型和合同号。

## 排查模板

1. 在 ADS 最新生产分区按 WBS 聚合 `count(1)`、`collect_set(status)`、`collect_set(siting_type_ys_flag)`、`sum(ar_due_amount)`、`collect_set(is_due_3m_above)`，先排除重复行。
2. 核对项目类型、合同号、客户、组织公司、`zjcxm`。注意：展示字段 `zjcxm` 不能替代 `dim_menhu_yh_uf_jcstgl_ha` 的 WBS+客户名单匹配。
3. 从应收政策明细按 WBS+客户+快照聚合 `ar_due_amount`、`aging_due_1m`、`aging_due_2m` 和 3 月以上账龄。
4. 查询集采名单的 WBS+客户精确匹配。
5. 对组织公司 `50091518` 等生产 SQL适用场景，查询未冲减应收票据金额并复算净额。
6. 输出每个分支的布尔列；无法读取规则表时，结论应标记为 `ambiguous`，不能用展示字段猜测名单命中。

## 权限注意事项

应优先查询 `yh_doc_ads` / `yh_doc_cdm` 新湖仓表。只有用户明确排查旧湖仓任务时，才使用 `dfyh_*` 表。

## 已验证口径：应收政策明细中的工程存货

`ads_fm_accounts_receivable_policy_final.engineering_inventory_ap` 是“工程存货（剔除预收）”，不是从库存实物明细直接取数。生产链路为：

`ads_fm_accounts_receivable_policy_final`
<- `dwd_fm_accounts_receivable_policy_final`
<- `dwd_fm_accounts_receivable_policy_init`
<- `dwd_fm_accounts_receivable_cooperate`
<- `dwd_fm_accounts_receivable_due_summary`
<- 工程施工收入成本链路。

在 `dwd_fm_accounts_receivable_due_summary` 中，只有 `contract_class_cd='30'` 且 `cust_type='ZSKH'` 的工程施工直属客户项目才取工程存货：

- `forecast_revenue_pjtd = ei.forecast_revenue_pjtd`
- `revenue_visa_pjtd = ei.revenue_visa_pjtd`
- `engineering_inventory = max(forecast_revenue_pjtd - revenue_visa_pjtd, 0)`
- `engineering_inventory_negative = forecast_revenue_pjtd - revenue_visa_pjtd`

下游 ADS 再计算：

- `engineering_inventory_ap = max(engineering_inventory - advance_payment, 0)`（生产 SQL 还带有 collection_ratio 判负保护）
- `dmbtr_ar_ei = dmbtr_ar + engineering_inventory_ap`

工程施工收入来源分两块相加：

- 新口径：`dwd_fin_income_cost_detail_assess_excl_policy` <- `dws_fin_income_cost_detail_profit_exclusion` <- `dws_fin_income_cost_detail_assess` <- `dws_fin_income_cost_detail_assess_gcsg` <- `dws_fin_income_cost_detail_assess_base_tmp` <- `dwd_fin_voucher_link` <- `dwd_fin_voucher_f_link`。
- 旧初始口径：`dwi_di_wbs_balance_t_f`，`year='2023'`、`contract_data_type='GCSG-ZS-KH'`。

案例验证：2026-07-20 查 `pt=20260719`、WBS `QG-PPQ20070`、客户 `0072112335`，ADS `engineering_inventory_ap=9414.122304238637`。拆解为新口径测算收入 `9414.104158766390515717`、旧初始测算收入 `0.008145472247279563`、旧初始签证收入 `-0.01`，合计 `forecast_revenue_pjtd=9414.11230423863779528`、`revenue_visa_pjtd=-0.01`、`advance_payment=0`，所以工程存货为 `9414.11230423863779528 - (-0.01) = 9414.12230423863779528`。
