# 出库表链路速查

用于排查用户口语里的“出库表”“销售订单出库情况报表”“订单发货汇总”。这套链路是订单、出库、发票、发货产值视角，不是财务凭证/管报考核链路。

## 定位

- 主表：`yh_doc_cdm.dwd_order_shipment_split_mkt`
- DataWorks 节点：`dwd_order_shipment_split_mkt`
- 节点注释：`工建订单发货汇总(材料销售/工程施工)`
- 生产节点证据：`trace-table yh_doc_cdm.dwd_order_shipment_split_mkt`，PROD node `210002682128`，2026-06-24 验证。

## 适用场景

- 按销售订单、订单行、发票、出库单、出库行看发货状态、已发/未发数量、发货产值、调拨毛利。
- 从订单履约角度对齐发票、出库、业务员、考核组织、物料、生产工厂、客户、合伙人、WBS、商机。
- 和收入表对比时，它只能说明订单/出库/发票事实，不直接证明财务凭证是否进入 `income_amt_assess`。

## 不适用场景

- 不用它直接判断 `voucher_t`、G00/G02/K01/K99、双算、利润拆分政策是否正确。
- 不用它直接解释 `ads_fin_income_cost_detail_assess_mkt.income_amt_assess` 缺原始凭证；那类问题先读 `income-management-report-chain.md`。

## 已知主链路

```text
订单/出库/发票/SAP与营销维表
  -> DataWorks dwd_order_shipment_split_mkt
  -> yh_doc_cdm.dwd_order_shipment_split_mkt
  -> 下游订单发货、雨虹收入成本毛利、出库类报表
```

节点 SQL 很长，已验证的核心处理包括：

- CTE `all_order_summary` 汇总订单、订单行、开票凭证、出库单、出库行、业务员、考核组织、客户、物料、发货数量、已发/未发产值。
- 主加工从 `order_shipment_split_1 oss` 出发，继续关联 `vbap`、`vbrp`、`vbrk`、采购订单、合同、客户、物料、价格、组织、SAP 公司间发票关系等维表。
- 输出字段覆盖 `vbap_vbeln`、`vbap_posnr`、`vgbel`、`vgpos`、`vbrp_vbeln`、`vbrp_posnr`、`sale_income`、`sale_tax_income`、`allocation_income_profit`、`state_shipment`、`fkdat`、`new_posting_date_budat` 等订单履约字段。

## 常用排查入口

按订单和发票看出库侧事实：

```sql
SELECT vbap_vbeln, vbap_posnr, vbrp_vbeln, vbrp_posnr,
       vgbel, vgpos, state_shipment, matnr, material_nm,
       fkdat, new_posting_date_budat,
       COUNT(1) AS row_cnt,
       ROUND(SUM(COALESCE(fklmg_sum,0)),2) AS shipped_qty,
       ROUND(SUM(COALESCE(sale_income,0)),2) AS sale_income,
       ROUND(SUM(COALESCE(sale_tax_income,0)),2) AS sale_tax_income,
       ROUND(SUM(COALESCE(allocation_income_profit,0)),2) AS allocation_income_profit
FROM yh_doc_cdm.dwd_order_shipment_split_mkt
WHERE pt = MAX_PT('yh_doc_cdm.dwd_order_shipment_split_mkt')
  AND vbap_vbeln = '<sale_order>'
GROUP BY vbap_vbeln, vbap_posnr, vbrp_vbeln, vbrp_posnr,
         vgbel, vgpos, state_shipment, matnr, material_nm,
         fkdat, new_posting_date_budat
ORDER BY vbap_vbeln, vbap_posnr, vbrp_vbeln, vbrp_posnr, vgbel, vgpos;
```

和财务凭证收入表对比时，先在本表固定订单/发票/物料/出库事实，再去收入链路查 `voucher_t -> dwd_fin_voucher_link -> dws_fin_income_cost_detail_assess_base_tmp -> ADS`。不要把两套模型的金额字段直接当作同一口径。

## 待补充

- `order_shipment_split_1` 的完整上游来源还没有单独沉淀成文档；遇到出库表内部金额或拆分比例问题时，应重新 `trace-table yh_doc_cdm.dwd_order_shipment_split_mkt --save-node-code ...`，针对相关 CTE 继续补充。
- `dwd_order_shipment_split_gggs` 与 `dwd_order_shipment_split_mkt` 的关系只登记为 related table，尚未验证完整差异。