# 四停项目信息表链路

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
