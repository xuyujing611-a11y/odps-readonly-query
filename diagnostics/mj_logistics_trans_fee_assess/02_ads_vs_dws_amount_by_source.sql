SELECT  COALESCE(dws.source_type, ads.source_type) AS source_type
        ,dws.row_cnt AS dws_row_cnt
        ,ads.row_cnt AS ads_row_cnt
        ,ads.row_cnt - dws.row_cnt AS diff_row_cnt
        ,dws.fin_fee_tax AS dws_fin_fee_tax
        ,ads.fin_fee_tax AS ads_fin_fee_tax
        ,ads.fin_fee_tax - dws.fin_fee_tax AS diff_fin_fee_tax
        ,dws.biz_fee_tax AS dws_biz_fee_tax
        ,ads.biz_fee_tax AS ads_biz_fee_tax
        ,ads.biz_fee_tax - dws.biz_fee_tax AS diff_biz_fee_tax
FROM
(
    SELECT  source_type
            ,COUNT(*) AS row_cnt
            ,SUM(NVL(assess_vouch_amt_with_tax,0)) AS fin_fee_tax
            ,SUM(NVL(biz_assess_fee_tax,0)) AS biz_fee_tax
    FROM    dws_mj_logistics_trans_fee_assess_dtl
    WHERE   pt = '${bizdate}'
    GROUP BY source_type
) dws
FULL OUTER JOIN
(
    SELECT  source_type
            ,COUNT(*) AS row_cnt
            ,SUM(NVL(assess_vouch_amt_with_tax,0)) AS fin_fee_tax
            ,SUM(NVL(biz_assess_fee_tax,0)) AS biz_fee_tax
    FROM    ads_mj_logistics_trans_fee_assess_dtl
    WHERE   pt = '${bizdate}'
    GROUP BY source_type
) ads
ON dws.source_type = ads.source_type
;
