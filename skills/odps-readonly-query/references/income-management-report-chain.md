# 管报凭证到收入表链路速查

用于排查雨虹收入表、管报凭证、考核收入成本明细、双算调整、利润拆分政策等问题。这个链路是财务凭证视角，不是订单出库视角。

## 先区分两套口径

- 财务凭证/管报/考核链路：从 Hologres `voucher_t` 及其 ODPS ODS 镜像进入，经过 DWD 凭证宽表、考核底表、S/F/工程/单行分支、利润剔除和 ADS。适合查 `income_amt_assess`、`cost_amt_assess`、`vouch_type`、`adjust_type`、`data_type`、G/K 场景、双算、利润拆分政策。
- 出库/订单链路：`dwd_order_shipment_split_mkt` 是订单、发票、出库视角的 ODPS 模型，用于雨虹收入成本毛利类订单履约分析。它可以对齐订单、发票、出库数量和开票事实，但不能直接证明财务凭证链路是否应该进入考核收入表。

## 主链路

```text
Hologres voucher_t
  -> yh_doc_ods.ods_di_voucher_t_f
  -> yh_doc_cdm.dwd_fin_voucher_f_link
  -> yh_doc_cdm.dwd_fin_voucher_link
  -> yh_doc_cdm.dws_fin_income_cost_detail_assess_base_tmp
  -> yh_doc_cdm.dws_fin_income_cost_detail_assess_s
   + yh_doc_cdm.dws_fin_income_cost_detail_assess_f
   + yh_doc_cdm.dws_fin_income_cost_detail_assess_gcsg
   + yh_doc_cdm.dws_fin_income_cost_detail_assess_single
  -> yh_doc_cdm.dws_fin_income_cost_detail_assess
  -> yh_doc_cdm.dws_fin_income_cost_detail_profit_exclusion
  -> yh_doc_cdm.dws_fin_income_cost_detail_assess_mkt
  -> yh_doc_ads.ads_fin_income_cost_detail_assess_mkt
```

## 表职责

| 表 | 职责 | 排查重点 |
| --- | --- | --- |
| Hologres `voucher_t` | 管报/考核凭证事实源，包含原始 G00/RV、G 场景、K 场景及 `origin_id`/`parent_id` 关系 | 先按订单、发票、凭证号、科目、`scene_code`、`data_source`、`origin_id` 查是否有源行和派生行 |
| `ods_di_voucher_t_f` | `voucher_t` 的 ODPS ODS 镜像 | 当 Hologres 有、ODPS 下游没有时，确认是否同步到 ODS |
| `dwd_fin_voucher_f_link` | 凭证大宽表主加工层；从 `ods_di_voucher_t_f base` 出发，补 SAP、组织、物料、合同、政策等维度，生成金额、`data_type`、`adjust_type`、`zz_assess_flag`、`data_drill_pk`、`exclude_tag` 等 | 复杂逻辑集中在这里；如果 `dwd_fin_voucher_link` 没有，先看这里是否被 `exclude_tag` 标记 |
| `dwd_fin_voucher_link` | 从 `dwd_fin_voucher_f_link` 取 `exclude_tag IS NULL` 的凭证宽表 | 它基本是过滤后的入口表，不是主要业务逻辑层 |
| `dws_fin_income_cost_detail_assess_base_tmp` | 考核收入成本底表；从 `dwd_fin_voucher_link` 进来，计算 `single_line_flag`、`remove_flag`、`biz_logic_flag`、`income_cost_flag`，最后只保留 `remove_flag=1` | 判断原始凭证是否进最终表，优先查这层的四个 flag |
| `dws_fin_income_cost_detail_assess_s` | CLXS 且管报工厂 S 分支，做收入/成本配比、双算调整等 S 端逻辑 | 查 `biz_logic_flag='S'`、`single_line_flag=0`、收入/成本科目 |
| `dws_fin_income_cost_detail_assess_f` | CLXS 且管报工厂 F 分支，做 F 端收入/成本配比 | 查公司间、生产 F、G02/F 收入和原始成本承接 |
| `dws_fin_income_cost_detail_assess_gcsg` | 工程施工分支 | 查 `contr_proj_type LIKE 'GCSG%'` |
| `dws_fin_income_cost_detail_assess_single` | 单行显示分支 | 查 G91、K07/K08/K26/K33/K46/K47/K48/K99、借贷项、反补等单行逻辑 |
| `dws_fin_income_cost_detail_assess` | 汇总 S/F/GCSG/single 等分支 | 如果这里没有，ADS 一般不会再出现 |
| `dws_fin_income_cost_detail_profit_exclusion` | 在考核明细基础上处理利润剔除/利润拆分相关口径 | 判断是不是利润政策层新增/剔除 |
| `dws_fin_income_cost_detail_assess_mkt` | 面向营销收入成本明细的 DWS | ADS 的主要来源 |
| `ads_fin_income_cost_detail_assess_mkt` | 用户侧收入成本考核明细 ADS；节点注释说明业务逻辑应前置到 DWS | 通常不是根因层，先向上追 DWS/DWD |

## 快速排查顺序

1. 从 ADS 复现问题：按 `sale_num`、`sale_invoice_num`、`vouch_type`、`subj_cd`、`data_type`、`adjust_type`、`manage_fty`、`org_cd` 聚合 `income_amt_assess`、`cost_amt_assess`。
2. 向上对比 `dws_fin_income_cost_detail_assess_mkt`、`dws_fin_income_cost_detail_profit_exclusion`、`dws_fin_income_cost_detail_assess`。如果三层结果一致，ADS 不是根因。
3. 查 `dws_fin_income_cost_detail_assess_base_tmp`：看 `vouch_type`、`subj_cd`、`manage_fty`、`biz_logic_flag`、`single_line_flag`、`remove_flag`、`income_cost_flag`、`data_type`、`adjust_type`。
4. 查 `dwd_fin_voucher_link`：确认进入考核底表前的凭证行是否存在，注意此表已经过滤 `exclude_tag IS NULL`。
5. 查 `dwd_fin_voucher_f_link`：如果 `dwd_fin_voucher_link` 没有，检查是否在 F link 层被 `exclude_tag` 标记，或补维/政策逻辑导致字段变化。
6. 查 `ods_di_voucher_t_f` 和 Hologres `voucher_t`：确认源凭证、G/K 派生凭证、`origin_id`、`parent_id`、`scene_code`、`data_source`。
7. 如果问题是 G/K 场景生成，回到 Hologres 查询 skill 的代码仓库流程，查 `runtime\codeup\di-sql` 或 mapper 中的场景 SQL，并用 Hologres 实表验证。

## 常用定位 SQL 模板

ADS/DWS 聚合：

```sql
SELECT sale_invoice_num, vouch_type, subj_cd, data_type, adjust_type,
       manage_fty, org_cd, grp_cd,
       COUNT(1) AS row_cnt,
       ROUND(SUM(COALESCE(income_amt_assess,0)),2) AS income_amt,
       ROUND(SUM(COALESCE(cost_amt_assess,0)),2) AS cost_amt
FROM yh_doc_ads.ads_fin_income_cost_detail_assess_mkt
WHERE pt = MAX_PT('yh_doc_ads.ads_fin_income_cost_detail_assess_mkt')
  AND sale_num = '<sale_num>'
GROUP BY sale_invoice_num, vouch_type, subj_cd, data_type, adjust_type,
         manage_fty, org_cd, grp_cd
ORDER BY sale_invoice_num, vouch_type, subj_cd, manage_fty;
```

考核底表 flag：

```sql
SELECT sale_invoice_num, vouch_type, subj_cd, manage_fty,
       biz_logic_flag, single_line_flag, remove_flag, income_cost_flag,
       data_type, adjust_type, org_cd, grp_cd, vouch_num, vouch_line_proj,
       COUNT(1) AS row_cnt,
       ROUND(SUM(COALESCE(assess_vouch_amt,0)),2) AS assess_amt
FROM yh_doc_cdm.dws_fin_income_cost_detail_assess_base_tmp
WHERE pt = MAX_PT('yh_doc_cdm.dws_fin_income_cost_detail_assess_base_tmp')
  AND sale_num = '<sale_num>'
GROUP BY sale_invoice_num, vouch_type, subj_cd, manage_fty,
         biz_logic_flag, single_line_flag, remove_flag, income_cost_flag,
         data_type, adjust_type, org_cd, grp_cd, vouch_num, vouch_line_proj
ORDER BY sale_invoice_num, vouch_type, subj_cd, manage_fty, income_cost_flag, org_cd;
```

DWD 原始收入/成本行：

```sql
SELECT sale_invoice_num, vouch_type, subj_cd, manage_fty, grp_cd,
       data_line_type, direct_unit_bel_grp, cntpty_assess_org_grp_cd,
       assess_policy_cd, is_assess_line_flag, org_cd, master_belong_unit_code,
       vouch_num, vouch_line_proj,
       ROUND(SUM(COALESCE(assess_vouch_amt,0)),2) AS assess_amt,
       COUNT(1) AS row_cnt
FROM yh_doc_cdm.dwd_fin_voucher_link
WHERE pt = MAX_PT('yh_doc_cdm.dwd_fin_voucher_link')
  AND sale_num = '<sale_num>'
  AND subj_cd RLIKE '^(6001|6051|6401|6402|G6001|G6051|G6401|G6402|K6001|K6051|K6401|K6402)'
GROUP BY sale_invoice_num, vouch_type, subj_cd, manage_fty, grp_cd,
         data_line_type, direct_unit_bel_grp, cntpty_assess_org_grp_cd,
         assess_policy_cd, is_assess_line_flag, org_cd, master_belong_unit_code,
         vouch_num, vouch_line_proj
ORDER BY sale_invoice_num, vouch_type, subj_cd, vouch_line_proj;
```

## 关键规则

- `dwd_fin_voucher_link` 只取 `dwd_fin_voucher_f_link` 中 `exclude_tag IS NULL` 的行；因此“源头有、DWD link 没有”时，先查 F link 的 `exclude_tag`。
- `dws_fin_income_cost_detail_assess_base_tmp` 只保留 `remove_flag=1`。对是否进入最终收入表的判断，不能只看 `voucher_t` 或 `dwd_fin_voucher_link` 是否有行，还要看 `remove_flag`、`biz_logic_flag` 和 `income_cost_flag`。
- `biz_logic_flag` 主要按合同项目类型和管报工厂尾字母分流：`CLXS% + S` 进 S，`CLXS% + F` 进 F，`GCSG%` 进工程施工，其他进 others。
- `income_cost_flag` 按科目识别：`6001/6051/G6001/G6051/K6001/K6051` 是 income；`6401/6402/G6401/G6402/K6401/K6402` 是 cost；其他是 othes。
- 制造集团 `grp_cd='20000007'` 且管报工厂尾字母是 `S` 的收入/成本科目行，会在考核底表剔除逻辑中不保留。不要把这种情况直接判断为“ADS 漏数”。
- K01、G02、K99 等派生行可能替代原始 RV/G00 行进入考核明细。判断“缺原始凭证”时，必须同时看 `origin_id`/`parent_id` 和派生凭证是否承接金额。
- 双算抵消通常是更高层级抵消行，和双算调整不同；用户明确让忽略双算抵消时，不要把 K99 抵消行作为原始收入缺失的解释。

## 订单 0202459193 的复盘样例

已验证现象：

- Hologres `voucher_t` 存在原始 G00/RV 收入行：`0800001247/000003`、`0800001248/000003`，科目 `6001010100`，`manage_factory=YHO4S`，金额分别约 `75022.12`、`-75022.12`。
- `dwd_fin_voucher_link` 中对应 RV 收入行存在，字段为 `manage_fty=YHO4S`、`grp_cd=20000007`、`data_line_type=manage`、`direct_unit_bel_grp=20000007`、`is_assess_line_flag=不考核`。
- `dws_fin_income_cost_detail_assess_base_tmp` 中已经没有这两条 RV 的 `6001010100` 收入行，只剩 RV 的应收/税/库存/成本行，以及派生的 G02/K01/K99 行。
- 根因是该 RV/G00 S 收入行命中“制造集团 + 管报工厂 S + 收入/成本科目”的考核底表剔除口径；最终由 G02/F、K01 双算调整等派生口径承接，而不是在 ADS 末端丢失。

可复用判断：如果用户问“原始 G00/RV 的 S 凭证为什么没有进入收入表”，优先查 `dwd_fin_voucher_link` 是否存在，再查 `dws_fin_income_cost_detail_assess_base_tmp` 是否被 `remove_flag` 规则挡掉。不要直接从 ADS 缺 RV 推断发票凭证缺失。
