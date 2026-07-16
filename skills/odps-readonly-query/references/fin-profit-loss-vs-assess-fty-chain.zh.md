# 损益年累计表 vs 工厂考核收入明细表

## 适用范围

用于比较：

- `yh_doc_ads.ads_fin_income_cost_detail_assess_fty`
- `yh_doc_ads.ads_fin_profit_loss_year`

这两张表不是简单的上下游关系，也不是天然同粒度的源表/目标表。

## 已验证链路

`ads_fin_income_cost_detail_assess_fty`：

- 生产节点：`210002018739`
- 直接来源：`yh_doc_cdm.dws_fin_income_cost_detail_assess`
- ADS 层硬过滤包括 `manage_fty in ('F')`、`grp_cd='20000007'`，并剔除 `6401940400`、`6402010400`、`6051950100`、`6051010400` 及其 `G/K` 版本等科目。

`ads_fin_profit_loss_year`：

- 生产节点：`210001895029`
- 直接来源：`yh_doc_cdm.dws_fin_profit_loss_year`
- `dws_fin_profit_loss_year` 基于 `yh_doc_cdm.dws_fin_profit_loss_month` 做年累计窗口汇总。
- 月度损益数据来自 `yh_doc_cdm.dws_fin_profit_loss_month_mid`。

供应链考核口径的主营业务收入，通过 `dim_fin_profit_loss_report_item_rela` 将 `主营业务收入` 映射到 `K6001` 和 `[G]?6001` 规则，并包含：

- `zz_assess_flag='Y'`
- 凭证类型不在 `G91,K90,K91,K92,K93,K94,K95,G05,K22,G15,G54,G55`
- `LENGTH(manage_fty) <= 5`
- `SUBSTR(manage_fty,-1,1) <> 'S'`

## 层级重复风险

`ads_fin_profit_loss_year` 同一张表里存了多个组织层级。只过滤 `org_cd` 时，可能同时命中公司行和上卷行。

已验证例子：`pt=20260702`、`acctnt_year=2026`、`org_cd=50018478`、`report_name='供应链-损益表'`、`cali_name='考核'`、`report_index='主营业务收入'`、`assess_type='考核'`：

- 一行 `comp_cd=50018478`。
- 一行 `comp_cd IS NULL`。
- 两行各期间金额相同。
- 只按 `org_cd=50018478` 汇总会把损益金额翻倍。

做公司层级对比时，应同时约束 `comp_cd='50018478'`，或明确约束到目标层级。

## 已验证案例：50018478

在 `pt=20260702`、`acctnt_year=2026` 下：

- FTY 表按 `comp_cd=50018478`、1-7 期汇总 `income_amt_assess`：`393,170,837.87`。
- 损益表只按 `org_cd=50018478` 汇总会命中两个层级行：`814,159,595.14`。
- 损益表按 `org_cd=50018478 AND comp_cd=50018478` 汇总：`407,079,797.57`。
- 修正层级后，差异从约 `420,988,757.27` 缩小为 `13,908,959.70`。

如果业务口径中的“行政组织”指 `comp_cd`，则两边都应按 `comp_cd` 比较，不能用 `org_cd` 代替。

已验证的 `comp_cd=50018478` 公司层级比较：

- 损益表在 `comp_cd=50018478` 下每期只有 1 行，不存在层级重复。
- 6 期累计：FTY `389,938,724.76`，损益表 `403,958,614.86`，差异 `14,019,890.10`。
- 7 期累计：FTY `393,170,837.87`，损益表 `407,079,797.57`，差异 `13,908,959.70`。
- FTY 金额能完全对上其 DWS 来源在 ADS 硬过滤下的金额：`manage_fty='F'`、`grp_cd='20000007'`、非剔除科目，行数 `48,892`，金额 `393,170,837.87`。
- 损益表金额能完全对上会计余额分支：`dws_fin_account_balance_single_org.period_debt_crdt_trans_amt` 加上 `K6001`、`[G]?6001` 报表规则，1-7 期年累计与 ADS 损益表一致，残差为 0。
- 损益表 1-7 期公司层级来源构成：`6001/YH25F = 429,181,912.14`，`G6001/YH25F = 75,470,901.47`，`K6001/F = -97,573,016.04`，合计 `407,079,797.57`。

这个公司层级差异不是 ADS 汇总错误，而是 FTY 当前使用的是配比后的考核收入明细口径，损益表使用的是会计科目发生额经报表规则映射后的口径。

## 已验证的修正方向

如果业务要求 `ads_fin_income_cost_detail_assess_fty` 的考核收入必须等于损益表主营业务收入，且以损益表为准，修正应回到共同凭证明细层，而不是把已经汇总好的损益表金额反向分摊到 FTY 明细行。

`dim_fin_profit_loss_report_item_rela` 不是共同数据上游。它是非分区的静态报表规则表，`trace-table` 没有找到 DataWorks 产出节点；catalog 显示该表有 `262` 行，`etl_time` 从 `20240823 18:35:12` 到 `20250924 16:25:25`。对供应链主营业务收入，它只提供 `K6001` 和 `[G]?6001` 两条发生额规则，`calc_sign=1`。

真正共同的数据上游是 `yh_doc_cdm.dwd_fin_voucher_link`：

- 损益表链路：`dwd_fin_voucher_link` -> `dws_fin_account_balance_single_org` -> `dws_fin_profit_loss_month_mid` -> `dws_fin_profit_loss_month` -> `dws_fin_profit_loss_year` -> `ads_fin_profit_loss_year`。
- FTY 链路：`dwd_fin_voucher_link` -> `dws_fin_income_cost_detail_assess_base_tmp` -> `dws_fin_income_cost_detail_assess_f` -> `dws_fin_income_cost_detail_assess` -> `ads_fin_income_cost_detail_assess_fty`。

已验证的正确策略，基于 `pt=20260702`、`acctnt_year=2026`：

1. 使用 `yh_doc_cdm.dws_fin_income_cost_detail_assess_base_tmp`，这是 FTY 分支使用的共同凭证明细临时层。
2. 关联 `yh_doc_cdm.dim_fin_profit_loss_report_item_rela`，沿用损益表主营业务收入规则：
   - `report_name='供应链-损益表'`
   - `target_index='主营业务收入'`
   - `target_index_type='发生额'`
   - `is_assess_calc='TRUE'`
3. 套用损益表供应链考核过滤：
   - `zz_assess_flag='Y'`
   - `NVL(vouch_type,'') NOT IN ('G91','K90','K91','K92','K93','K94','K95','G05','K22','G15','G54','G55')`
   - `LENGTH(NVL(manage_fty,'')) <= 5`
   - `SUBSTR(NVL(manage_fty,''),-1,1) <> 'S'`
4. 使用 `-assess_vouch_amt * calc_sign` 作为 FTY 的 `income_amt_assess`。
5. 保留制造集团范围 `grp_cd='20000007'`。
6. 下游 ADS 继续 `SUM(income_amt_assess)`，不需要公司期间级别的反向分摊。

只读验证结果：

- `comp_cd=50018478`，2026 年 1-7 期，`-assess_vouch_amt * calc_sign` 与损益表月发生额完全一致，合计 `407,079,797.57`，`max_abs_diff=0`。
- 制造集团全公司，2026 年 1-7 期，`188` 个公司-期间、`27` 个公司，`base_tmp` 月发生额合计 `6,799,075,844.02`，损益表月发生额合计 `6,799,075,844.02`，`max_abs_diff=0`，`nonzero_diff_cnt=0`。
- 匹配到的 staging 行全部为 `grp_cd='20000007'`。

不推荐的兜底方案：把已完成汇总的损益表公司期间金额按 FTY 原明细收入占比分摊，数学上也能对齐，但当共同凭证明细层可用时，这不是语义最干净的修正方式。只有共同 staging 行无法支撑目标明细粒度时，才考虑这个兜底方案。

实现注意：`gross_profit_amt`、`gross_profit_rate` 等依赖字段必须使用修正后的 `income_amt_assess` 重新计算。
