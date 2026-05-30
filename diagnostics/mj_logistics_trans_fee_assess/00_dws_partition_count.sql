SELECT  pt
        ,COUNT(1) AS row_cnt
FROM    dws_mj_logistics_trans_fee_assess_dtl
WHERE   pt = '${bizdate}'
GROUP BY pt
;
