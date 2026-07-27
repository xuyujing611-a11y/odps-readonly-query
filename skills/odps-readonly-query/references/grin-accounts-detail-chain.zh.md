# 采购暂估明细表链路

## 主表

- ADS: `yh_doc_ads.ads_grin_accounts_dtl`
- 上游入库明细: `yh_doc_ads.ads_mm_purchase_order_receipt_details`

## 生产节点

- `ads_grin_accounts_dtl`: PROD node `210002435013`
- `ads_mm_purchase_order_receipt_details`: PROD node `210002298619`

## 暂估金额口径

`ads_grin_accounts_dtl.material_no_tax_dmbtr` 是报表字段“未税暂估金额”。

物料行，也就是 `is_yzf='否'`：

```sql
(NVL(delivered_num, 0) - NVL(material_invoicing_num, 0)) * material_no_tax_unit_price_amt
```

运杂费行，也就是 `is_yzf='是'`：

```sql
ABS(yzf_yrk) - SUM(yzf_kpdmbtr) + SUM(yzf_dztzdmbtr)
```

结果表最后会把绝对值小于 `0.1` 的未税暂估金额置为 `0`。

## 屏蔽填报表

生产逻辑存在订单级屏蔽 CTE：

```sql
eliminate AS (
    SELECT ebeln_cd
    FROM yh_doc_cdm.dwi_guanyuan_caigoupb
    WHERE pt = '${bizdate}'
    GROUP BY ebeln_cd
)
```

最终落表条件：

```sql
WHERE LTRIM(ebeln_cd, '0') NOT IN (
    SELECT LTRIM(ebeln_cd, '0') FROM eliminate
)
```

`yh_doc_cdm.dwi_guanyuan_caigoupb` 表注释为“采购订单暂估屏蔽”，生产 SQL 注释为“观远采购暂估订单屏蔽填报表”。字段包括 `werks`、`ebeln_cd`、`desc`、`creator`、`editor`、`c_time`、`u_time`。该规则按采购订单号整单剔除，不按订单行、供应商或金额局部剔除。

## 上游字段

`ads_mm_purchase_order_receipt_details` 提供：

- `delivered_num`: 已交货数量
- `material_invoicing_num`: 物料开票数量
- `material_delivery_tax_amt`: 物料交货含税金额
- `material_delivery_tax_amount`: 物料交货未税金额
- `billing_voucher_cd`: 开票凭证号
- `soa_no`: 对账单
- `invoice_status`: 由 `material_invoicing_num=0` 判断，0 为未发票校验，否则已发票校验

## 已验证案例

`pt=20260720`，供应商 `70300626`，采购订单 `8930139991` 行 `20/40`：

- 上游交货未税金额是 `37.61`
- `delivered_num=10`
- `material_invoicing_num=10`
- 暂估公式结果为 `0`

`pt=20260720`，供应商 `60336720`，采购订单 `8920131758` 行 `10`：

- `delivered_num=749590`
- `material_invoicing_num=0`
- `billing_voucher_cd` 和 `soa_no` 为空
- `material_no_tax_unit_price_amt=0.009174308622046719`
- 暂估公式结果为 `6876.97`

`pt=20260721`，屏蔽表 `dwi_guanyuan_caigoupb` 最新分区有 280 行、249 个采购订单。订单 `8930139991` 和 `8920131758` 均未维护在屏蔽表中。

## 排查建议

先查 `ads_grin_accounts_dtl` 的最终字段，再查 `ads_mm_purchase_order_receipt_details` 的开票数量、开票凭证和 SOA。不要只看上游 `material_delivery_tax_amount`，它是交货未税金额，不等同于最终“未税暂估金额”。

如果业务确认某个订单属于历史调账、系统 Bug、取消订单误入库、已对账但 DI 仍显示暂估等例外场景，可以核实后维护到观远采购暂估订单屏蔽填报表。维护后会按订单号整单从 `ads_grin_accounts_dtl` 剔除。
