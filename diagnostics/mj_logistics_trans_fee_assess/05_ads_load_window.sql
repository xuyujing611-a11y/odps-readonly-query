SELECT  pt
        ,COUNT(*) AS row_cnt
        ,MIN(etldate) AS min_etldate
        ,MAX(etldate) AS max_etldate
FROM    ads_mj_logistics_trans_fee_assess_dtl
WHERE   pt = '${bizdate}'
GROUP BY pt
;
