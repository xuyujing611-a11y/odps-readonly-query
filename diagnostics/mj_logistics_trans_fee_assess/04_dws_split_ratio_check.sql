SELECT  source_type
        ,split_type
        ,COUNT(*) AS row_cnt
        ,MIN(income_split_rate) AS min_income_split_rate
        ,MAX(income_split_rate) AS max_income_split_rate
        ,SUM(CASE WHEN income_split_rate < 0 THEN 1 ELSE 0 END) AS negative_rate_cnt
        ,SUM(CASE WHEN income_split_rate > 1 THEN 1 ELSE 0 END) AS over_100_percent_rate_cnt
        ,SUM(CASE WHEN income_split_rate IS NULL THEN 1 ELSE 0 END) AS null_rate_cnt
        ,SUM(NVL(assess_vouch_amt_with_tax,0)) AS fin_fee_tax
        ,SUM(NVL(biz_assess_fee_tax,0)) AS biz_fee_tax
FROM    dws_mj_logistics_trans_fee_assess_dtl
WHERE   pt = '${bizdate}'
GROUP BY source_type, split_type
ORDER BY source_type, split_type
;
