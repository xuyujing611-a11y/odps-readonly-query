# 股改公司收入成本明细与施工实时口径链路速查

用于处理 `yh_doc_ads.ads_non_share_revenue_cost_detail`、`yh_doc_cdm.dws_non_share_revenue_cost_detail` 及施工项目月中实时收入/成本口径相关问题。

## 核心链路

```text
SAP ACDOCA / billing / order dimensions
  -> yh_doc_cdm.dws_non_share_revenue_cost_detail
  -> yh_doc_ads.ads_non_share_revenue_cost_detail

yh_doc_ads.ads_fm_construction_schedule
  -> 施工项目当前月实时收入/成本/签证收入补充口径
```

## 已验证事实

- `yh_doc_ads.ads_non_share_revenue_cost_detail` 是收入成本明细表_股改公司_sap口径_ads层，按 `pt` 分区；2026-07-06 校验时最新分区为 `pt=20260705`。
- `yh_doc_cdm.dws_non_share_revenue_cost_detail` 是收入成本明细表_股改公司_sap口径，按 `pt` 分区；2026-07-06 校验时最新分区为 `pt=20260705`。
- ADS 节点 `ads_non_share_revenue_cost_detail` 为 PROD DataWorks 节点 `210003073749`，调度表达式 `00 30 04-09/6 * * ?`，从 `${space_name_cdm}.dws_non_share_revenue_cost_detail` 同分区透传。
- DWS 节点 `dws_non_share_revenue_cost_detail` 为 PROD DataWorks 节点 `210003073026`，调度表达式 `00 30 02-09/6 * * ?`。
- DWS 生产 SQL 中收入分支筛选 `SUBSTR(racct,1,4) IN ('6001','6051')`，成本分支筛选 `SUBSTR(racct,1,4) IN ('6401','6402')`。
- DWS 生产 SQL 中订单 fallback 逻辑可见 `CASE WHEN LENGTH(KDAUF) < 2 THEN SUBSTR(ZUONR,-8) ELSE KDAUF END`；如果业务材料声称施工项目订单取 `SUBSTR(ZUONR,1,11)`，需要在改造前确认差异。
- `yh_doc_ads.ads_fm_construction_schedule` 是施工信息表，按 `pt` 分区；包含 `yearmonth`、`wbs`、`vbeln`、`vkorg`、`z_income`、`cl_cost`、`f_cost`、`amt_lscb`、`qz_lj`、`sf_wg`、`plan_income`、`plan_cost` 等施工实时口径字段。
- 2026-07-06 抽查 `ads_fm_construction_schedule` 最新分区 `pt=20260705`：`yearmonth=202606` 有 36,838 个 WBS，`z_income` 汇总 270,928,280.49；`yearmonth=202607` 有 36,889 个 WBS，`z_income` 汇总为 0，`cl_cost+f_cost` 汇总 11,068,625.03，`qz_lj` 汇总 15,206,105.73。当前月实时收入不能直接取 raw `z_income`，应按累计测算收入与已过账收入差额计算。

## 方案判断

- 不建议无标识地把施工项目实时测算收入写入现有 SAP 明细表，否则会混淆凭证明细粒度和项目月度指标粒度。
- 优先在报表层或独立 ADS 聚合表补充施工实时口径：历史月份继续以 `ads_non_share_revenue_cost_detail` 的 SAP 已过账明细为准；当前月施工项目从 `ads_fm_construction_schedule` 计算实时当月收入、当月成本和签证收入。
- 如果必须落到现有 ADS 明细表，应新增来源标识、统计月份和签证收入指标字段，避免实时测算行与 SAP 凭证行重复统计。

## 排查入口

1. 先 `inspect-table` 检查三张表最新分区与字段。
2. 对 ADS/DWS 问题，先 trace `yh_doc_cdm.dws_non_share_revenue_cost_detail`，因为 ADS 只是透传。
3. 对施工项目当前月实时收入问题，查询 `yh_doc_ads.ads_fm_construction_schedule`，不要只看 ADS 的 6001/6051 过账收入。
4. 对年度累计签证收入，先确认 `qz_lj` 是月度签证收入、项目累计签证收入，还是截至月份累计值，再决定求和或取截止月/年初差额。
