# 总单与资产差异汇总表（工程施工）链路速查

用于排查 `yh_doc_ads.ads_asset_statement_diff_summary_gcsg`（对账单总单与资产汇总差异核对_工程施工）中对账单总单值、资产汇总值、差异值不一致的问题。该报表是核对视角，ADS 主要承接 DWS 结果并筛选展示指标，根因通常在 DWS 的对账单侧清洗或资产侧聚合逻辑。

## 主链路

```text
yh_doc_cdm.dwd_mks_account_statement_consolidation_gcsg   -- 对账单总单侧
  + yh_doc_cdm.dwd_mks_asset_detail_merge_for_account_statement -- 资产流水侧
  + yh_doc_ods.ods_mks_yh_asset_account_all_withdrawal_f        -- 资金退出类型补充
  + 其他认款/调账/转移/抵债 ODS 或 DWI 来源
  -> yh_doc_cdm.dws_asset_statement_diff_summary_gcsg
  -> yh_doc_ads.ads_asset_statement_diff_summary_gcsg
```

## 表职责

| 表 | 职责 | 排查重点 |
| --- | --- | --- |
| `yh_doc_ads.ads_asset_statement_diff_summary_gcsg` | 用户侧 ADS 差异表；从 DWS 读取并筛选展示回款金额、管理费、垫资、税金、资料保证金、发货金额、应收金额等指标 | 先按 `pt`、`agent_code`、`project_wbs_num`、`diff_metric_type_name` 复现用户看到的差异；不要把全量最新分区和页面筛选混比 |
| `yh_doc_cdm.dws_asset_statement_diff_summary_gcsg` | 差异计算主层；对账单侧来自 `dwd_mks_account_statement_consolidation_gcsg`，资产侧在 `asset_detail`/`asset_sum` 中聚合 | 大多数指标口径和 join 逻辑在这里；先 trace PROD node，不要基于本地缓存改 SQL |
| `yh_doc_cdm.dwd_mks_account_statement_consolidation_gcsg` | 工程施工对账单总单侧来源 | 查 `deadline`、`account_id`、`agent_code`、`project_wbs_num` 和各 factor 字段 |
| `yh_doc_cdm.dwd_mks_asset_detail_merge_for_account_statement` | 资产流水集合表，作为 DWS `asset1` 来源 | 表内不含 `flow_type`/`whether_advance`；资金退出相关分类需要从 withdrawal ODS join 补充 |
| `yh_doc_ods.ods_mks_yh_asset_account_all_withdrawal_f` | 资金退出申请表，DWS `withdrawl` CTE 来源 | 字段 `flow_type` 表示流程类型（`1` 为改造后），字段 `whether_advance` 注释为“是否垫资款” |

## 已验证坑点：旧流程垫资识别

DWS `withdrawl` CTE 的退款类型分类会影响 `asset_detail.type_of_subscription`，随后影响 `asset_sum.advance_asset` 和 `collection_asset`。已验证：

- `flow_type = '1'` 是改造后数据，继续按 `refund_type` 识别 `20=工程款`、`21=工程垫资款`、`22=项目质保金`。
- `flow_type <> '1'` 或 `flow_type IS NULL` 的旧流程数据，存在 `refund_type='0'` 但 `whether_advance='1'` 的资金退出记录；如果只用 `refund_type`，这类记录不会命中 `工程垫资款`，会导致资产侧垫资漏抵或回款/垫资分类错误。
- 推荐最小修复点是在 `withdrawl` CTE 内把派生后的 `refund_type` 统一修正：改造后按 `refund_type`；旧流程优先按 `whether_advance`；`whether_advance` 空时回退旧 `refund_type` 映射。这样后续 `type_of_subscription`、`advance_asset`、`collection_asset` 继续沿用原有分支，改动面小。

推荐派生逻辑形态：

```sql
CASE
    WHEN NVL(TRIM(flow_type),'') = '1' THEN CASE WHEN refund_type = '20' THEN '工程款' ELSE CASE WHEN refund_type = '21' THEN '工程垫资款' ELSE CASE WHEN refund_type = '22' THEN '项目质保金' ELSE refund_type END END END
    WHEN NVL(TRIM(whether_advance),'') = '1' THEN '工程垫资款'
    WHEN NVL(TRIM(whether_advance),'') = '0' THEN '工程款'
    ELSE CASE WHEN refund_type = '20' THEN '工程款' ELSE CASE WHEN refund_type = '21' THEN '工程垫资款' ELSE CASE WHEN refund_type = '22' THEN '项目质保金' ELSE refund_type END END END
 END AS refund_type
```

## 是否垫资款字段可用性

全表统计可能夸大 `whether_advance` 空值风险，因为改造后数据按 `refund_type` 判断，很多 `flow_type='1'` 行 `whether_advance` 为空属于正常现象。排查本报表时应先限定到 DWS 实际使用的资产分支，例如工程施工、`现款 + 资金退出`、`contract_2_code IN ('GS','ZS')`。

2026-06-25 对 `pt=20260624` 的只读验证结论：

- `ods_mks_yh_asset_account_all_withdrawal_f` 存在 `flow_type` 和 `whether_advance` 字段。
- 在 DWS 实际相关的工程施工 `现款 + 资金退出` 资产行中，旧流程 564 行里 563 行 `whether_advance` 非空，1 行为空（金额 -50000）。该字段对本报表关键旧流程分支基本可用，但不是全表全场景无缺口。
- 若发现 `flow_type` 旧流程且 `whether_advance` 为空，不能擅自判为垫资，应回退原逻辑或标记业务确认。

## 快速排查顺序

1. ADS 复现：限定 `pt`、`agent_code`、`asset_account`、`project_wbs_num`、`diff_metric_type_name`，确认页面分区/日期和最新分区是否一致。
2. DWS 复现：查同一 `pt` 的 `dws_asset_statement_diff_summary_gcsg`，确认 ADS 是否只是筛选展示层。
3. 资产侧聚合：重建 DWS `asset_detail`/`asset_sum` 中相关分支，输出当前分类、建议分类、金额差异。
4. 字段可用性：不要只看 withdrawal 全表空值率；按实际报表分支统计 `flow_type`、`whether_advance`、`refund_type`、资产行数和金额。
5. 修复验证：用只读 SQL 同时输出 current 与 proposed 金额；不要执行生产 `INSERT OVERWRITE`。

## 常用验证 SQL 模板

字段和值域核查：

```sql
SELECT flow_type, whether_advance, refund_type,
       COUNT(1) AS cnt,
       SUM(COALESCE(refund_amount,0)) AS refund_amount
FROM yh_doc_ods.ods_mks_yh_asset_account_all_withdrawal_f
WHERE pt = '<bizdate>'
  AND withdrawal_status = 2
  AND is_deleted = 0
GROUP BY flow_type, whether_advance, refund_type
ORDER BY flow_type, refund_type, whether_advance;
```

报表相关分支的字段可用性核查应基于 DWS 实际 join 后的资产行，不要只用 withdrawal 全表统计。

## 证据记录

- `trace-table yh_doc_ads.ads_asset_statement_diff_summary_gcsg`：2026-06-25 验证 PROD ADS node `210002653565`，ADS 从 `yh_doc_cdm.dws_asset_statement_diff_summary_gcsg` 取数并筛选展示指标。
- `trace-table yh_doc_cdm.dws_asset_statement_diff_summary_gcsg`：2026-06-25 验证 PROD DWS node `210002653528`，`withdrawl` CTE 来源为 `ods_mks_yh_asset_account_all_withdrawal_f`。
- `inspect-table yh_doc_ods.ods_mks_yh_asset_account_all_withdrawal_f`：2026-06-25 验证存在 `whether_advance`（是否垫资款）和 `flow_type`（流程类型 1-改造后）。
- 只读 SQL：2026-06-25 对 `pt=20260624` 复算，合伙人 `72114575` 的 `DL-G0230527` 当前资产垫资为 `12097.08`，按建议逻辑为 `0`；对 `pt=20260623` 同一项目复算结果一致。