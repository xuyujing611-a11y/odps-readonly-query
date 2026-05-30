SELECT  source_type
        ,COUNT(*) AS row_cnt
        ,SUM(CASE WHEN NVL(TRIM(cust_cd),'') = '' THEN 1 ELSE 0 END) AS empty_cust_cd_cnt
        ,SUM(CASE WHEN NVL(TRIM(cust_name),'') = '' THEN 1 ELSE 0 END) AS empty_cust_name_cnt
        ,SUM(CASE WHEN NVL(TRIM(ywybm),'') = '' THEN 1 ELSE 0 END) AS empty_ywybm_cnt
        ,SUM(CASE WHEN NVL(TRIM(assessment_org_cd),'') = '' THEN 1 ELSE 0 END) AS empty_assessment_org_cd_cnt
        ,SUM(CASE WHEN NVL(TRIM(split_type),'') = '' THEN 1 ELSE 0 END) AS empty_split_type_cnt
        ,SUM(CASE WHEN income_split_rate IS NULL THEN 1 ELSE 0 END) AS null_income_split_rate_cnt
        ,SUM(CASE WHEN biz_assess_fee_tax IS NULL THEN 1 ELSE 0 END) AS null_biz_assess_fee_tax_cnt
FROM    dws_mj_logistics_trans_fee_assess_dtl
WHERE   pt = '${bizdate}'
GROUP BY source_type
ORDER BY source_type
;
