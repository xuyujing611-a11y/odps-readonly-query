SELECT  dws.row_cnt AS dws_row_cnt
        ,ads.row_cnt AS ads_row_cnt
        ,ads.row_cnt - dws.row_cnt AS diff_cnt
FROM
(
    SELECT COUNT(*) AS row_cnt
    FROM   dws_mj_logistics_trans_fee_assess_dtl
    WHERE  pt = '${bizdate}'
) dws
CROSS JOIN
(
    SELECT COUNT(*) AS row_cnt
    FROM   ads_mj_logistics_trans_fee_assess_dtl
    WHERE  pt = '${bizdate}'
) ads
;
