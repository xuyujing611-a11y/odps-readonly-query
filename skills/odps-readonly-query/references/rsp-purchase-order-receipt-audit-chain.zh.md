# RSP 采购订单收货稽核链路

状态：verified
验证日期：2026-07-20
生产分区样本：`pt=20260719`

## 视角与主粒度

以 `yh_doc_cdm.dwi_rsp_purchase_order_line` 的有效采购订单行为主粒度。稳定行标识为 `id`，协同域业务键为 `order_number + row_num`。采购订单头按 `order_number` 关联。

## 稳定关联规则

- SAP 采购订单号：优先采购订单行 `source_document_number`，为空时回退采购订单头同名字段。已验证两者同时存在时没有冲突。
- SAP 键标准化：采购订单号补齐 10 位，行项目补齐 6 位。
- RSP 交货明细：`dwi_rsp_delivery_detail` 按 `order_number + row_num` 聚合 `delivery_quantity` 后关联。
- RSP 入库明细：`dwi_rsp_inventory_detail` 按 `order_number + row_num` 聚合 `quantity_received` 后关联。
- OMS：`dwi_otwb_oms_order.id = dwi_otwb_oms_order_detail.order_id`；头和明细均排除逻辑删除数据，订单状态 `C` 不计入总量，`P/F/R` 计为完成；采购订单通过标准化 SAP 单号关联 OMS 头 `related_no`，行项目关联 OMS 明细 `sap_line_no`。
- 库存域采购收货：`dwi_rsp_inventory_inventory_execute_task.source_document_number + source_document_line_number` 对应 RSP `order_number + row_num`；仅统计 `transaction_type_code='purchaseReceipt' AND status='success'`。

## SAP 数量规则

- 外采发货使用 `dwi_sap_ztmm0140a`：排除 `loekz` 非空记录，校验 `lfimg` 为数值后按 `ebeln + ebelp` 汇总。
- 公司间发货使用 EKET `wamng`，收货使用 EKET `wemng`。该口径已经业务确认，生产对账也支持 `wamng-wemng` 与 RSP 在途数量的对应关系。
- ZTMM0140A PROD 节点为 `210003284839`，上游是 `yh_doc_ods.ods_s4_ztmm0140a`。

## 关键陷阱

1. 飞书原需求把公司间发货和收货都写成 EKET `wemng`，会使差额恒为 0。
2. SAP 行项目补齐为 5 位会大量漏匹配；当前链路应统一为 6 位。
3. RSP 交货、入库、ZTMM 和库存动账均可能一对多，必须先聚合再连接主表。
4. OMS 明细没有 RSP `order_number`、`row_num` 或状态字段；状态来自 OMS 订单头。
5. OMS 没有字面值 `completed`，且 `be_completed` 在已匹配样本中不可用于完成判断；已确认用订单头状态 `P/F/R` 判断完成。
6. `warehouseTransferIn` 样本是 FR 调拨单，对采购订单行无命中；已确认采购收货只统计成功的 `purchaseReceipt`。
7. OMS 订单明细也存在 `be_delete=1` 的逻辑删除记录，头和明细必须同时过滤删除状态。
8. MaxCompute `GETDATE()` 的返回类型是 `DATETIME`；若目标刷新时间字段定义为 `TIMESTAMP`，最终 SELECT 必须使用 `CAST(GETDATE() AS TIMESTAMP)`，否则 INSERT 会报 ODPS-0130071 类型不兼容。

## 验证入口

本次证据位于需求工作区 `evidence/purchase_*.jsonl`。复核时优先运行：

- `trace-table yh_doc_cdm.dwi_sap_ztmm0140a`
- `trace-table yh_doc_cdm.dwi_rsp_inventory_inventory_execute_task`
- 对共同分区重跑关联基数与候选状态 SQL，禁止只依据节点代码下结论。

## 已验证模型结果

- 目标模型：`yh_doc_ads.ads_rsp_purchase_order_receipt_audit_detail`，`pt=${bizdate}` 每日全量快照；2026-07-20 已在 PROD 产出 `pt=20260719`。
- `pt=20260719` 完整只读逻辑输出 19,467 行，采购订单行 ID 也是 19,467 个，无关联放大。
- 分支为公司间 12,424、外采 6,913、未知 130；缺订单头 130，缺 SAP 单号 220。
- 成功采购收货动账覆盖 10,658 个采购订单行；OMS 覆盖 4,860 个采购订单行。
- OMS 完成不超过总量、OMS 总量拆分和 SAP 在途三个恒等式错误数均为 0。
- 上线后目标分区为 19,467 行、19,467 个唯一采购订单行 ID、重复 0；与有效采购订单行逐 ID 对账后，来源漏入目标 0、目标多出 0。
- 上线后总体状态为无差异 1,548、有差异 3,813、数据缺失 14,106；非法状态 0，八组差值与状态对应错误均为 0。
- 目标分区刷新时间为 `2026-07-20 13:48:42.541`。

## 订单头有效性风险（2026-07-21，待业务确认）

- 当前主表只过滤采购订单行 `del_flag=0` 且 `NVL(is_cancel,0)=0`；订单头仅用于补充属性，因此订单头已逻辑删除、`document_status=cancelled` 或 `document_status=issuedFailed` 的订单行仍会进入 ADS。
- `pt=20260720` 生产验证：有效采购订单行共 19,631 行；其中订单头逻辑删除 129 单/130 行、整单取消 54 单/91 行、下发失败 22 单/31 行，合计 205 单/252 行。
- 建议规则（待业务确认）：只剔除上述三类“明确无效订单头”，不要把普通“数据缺失”、缺 SAP 单号或真正缺订单头的记录一并删除。
- 复核证据：需求工作区 `evidence/missing_purchase_orders.jsonl` 中 2026-07-21 的订单头有效性分类 SQL。

## 采购订单创建日期字段来源（2026-07-21）

- 推荐字段：`yh_doc_cdm.dwi_rsp_purchase_order.create_time`，字段注释为“创建时间”，按 `order_number` 取最新订单头记录后透传到 ADS。
- 不建议用 `order_date` 替代：`pt=20260720` 验证，ADS 19,631 行中只有 6,011 行 `create_time = order_date`，13,620 行不同。
- 不建议用订单行 `dwi_rsp_purchase_order_line.create_time` 替代：该字段是行创建时间，不是订单头创建时间。
- 当前目标表 `yh_doc_ads.ads_rsp_purchase_order_receipt_audit_detail` 尚无采购订单创建日期/时间字段；如要落表，需要先加 ADS 字段，再在生产节点 `210003299139` 的订单头 CTE 与最终 SELECT 中透传。

## 外采发货删除标识风险（2026-07-21，待业务确认）

- 当前外采 SAP 发货数量取 `yh_doc_cdm.dwi_sap_ztmm0140a.lfimg`，并排除 `loekz` 非空记录；`loekz` 字段注释为“删除标识”。
- 案例 `CD2025121900000029` 对应 SAP 单 `8950418141`，ADS 判定为外采 `EXTERNAL`，两行 SAP 发货数量为空。生产源表 `ZTMM0140A` 实际有 `lfimg`：`000010=600`、`000020=800`，但两行 `loekz='X'`，因此被当前模型过滤。
- `pt=20260720` 影响面模拟：如放开该过滤，可补回当前外采缺 SAP 发货的 33 个订单 / 46 行，发货数量合计 688,538；该规则不应按单号特判，需要业务确认 `loekz='X'` 的交货数量是否仍应纳入稽核。
- 与 `yh_doc_cdm.dwi_sap_ekpo` 对比：按 `ebeln + 数字归一后的 ebelp` 匹配，`pt=20260720` 有 444,047 行删除标识一致，11,852 行为 `ZTMM0140A.loekz` 非空但 `EKPO.loekz` 为空，2,069 行为 `ZTMM0140A.loekz` 为空但 `EKPO.loekz` 非空。案例 SAP 单 `8950418141` 的两行就是 `ZTMM0140A='X'、EKPO=空`。
