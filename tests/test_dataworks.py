import unittest

from report_doctor.config import DataWorksSettings
from report_doctor.dataworks_client import DataWorksReadOnlyClient, normalize_response
from report_doctor.dataworks_logic import candidate_outputs_for_table, resolve_table_logic


class FakeSdk:
    def list_nodes_by_output(self, request):
        self.last_outputs = request.outputs
        return {
            "Success": True,
            "Data": [
                {
                    "Output": "yh_doc_cdm.dim_matl",
                    "NodeList": [
                        {
                            "NodeId": 123,
                            "NodeName": "load_dim_matl",
                            "FileType": "ODPS_SQL",
                            "ProjectId": 456,
                        }
                    ],
                }
            ],
        }

    def get_node(self, request):
        return {
            "Success": True,
            "Data": {
                "NodeId": request.node_id,
                "NodeName": "load_dim_matl",
                "CronExpress": "00 00 00 * * ?",
                "OwnerId": "owner",
                "Connection": "odps_prod",
                "ProjectId": 456,
                "FileType": "ODPS_SQL",
            },
        }

    def get_node_code(self, request):
        return {"Success": True, "Data": "insert overwrite table yh_doc_cdm.dim_matl select * from src;"}


class DataWorksTests(unittest.TestCase):
    def test_candidate_outputs_include_qualified_table_first(self):
        self.assertEqual(
            candidate_outputs_for_table("yh_doc_cdm.dim_matl", odps_project="default_project"),
            ["yh_doc_cdm.dim_matl", "dim_matl"],
        )
        self.assertEqual(
            candidate_outputs_for_table("dim_matl", odps_project="yh_doc_cdm"),
            ["yh_doc_cdm.dim_matl", "dim_matl"],
        )

    def test_normalize_response_accepts_to_map_objects(self):
        class Body:
            def to_map(self):
                return {"Success": True, "Data": "select 1;"}

        class Response:
            body = Body()

        self.assertEqual(normalize_response(Response()), {"Success": True, "Data": "select 1;"})

    def test_resolve_table_logic_uses_view_original_text_before_dataworks(self):
        rows = resolve_table_logic(
            "yh_doc_cdm.dim_view",
            catalog_rows=[
                {
                    "table_type": "VIEW",
                    "view_original_text": "select * from yh_doc_cdm.dim_matl",
                }
            ],
            dataworks_client=None,
            odps_project="yh_doc_cdm",
        )

        self.assertEqual(rows[0]["source"], "system_catalog_view")
        self.assertEqual(rows[0]["logic_sql"], "select * from yh_doc_cdm.dim_matl")

    def test_resolve_table_logic_fetches_dataworks_node_code(self):
        settings = DataWorksSettings(
            access_id="ak",
            secret_access_key="sk",
            region="cn-beijing",
            project_env="PROD",
            endpoint="dataworks.cn-beijing.aliyuncs.com",
            api_version="2020-05-18",
        )
        client = DataWorksReadOnlyClient(settings=settings, sdk_client=FakeSdk())

        rows = resolve_table_logic(
            "yh_doc_cdm.dim_matl",
            catalog_rows=[{"table_type": "MANAGED_TABLE", "view_original_text": None}],
            dataworks_client=client,
            odps_project="yh_doc_cdm",
        )

        self.assertEqual(rows[0]["source"], "dataworks_openapi")
        self.assertEqual(rows[0]["project_env"], "PROD")
        self.assertEqual(rows[0]["node_id"], 123)
        self.assertIn("insert overwrite table yh_doc_cdm.dim_matl", rows[0]["node_code"])

    def test_resolve_table_logic_falls_back_to_producing_tasks(self):
        class ProducingTaskSdk(FakeSdk):
            def list_nodes_by_output(self, request):
                self.last_outputs = request.outputs
                return {"Success": True, "Data": []}

            def search_meta_tables(self, request):
                self.last_keyword = request.keyword
                return {
                    "Success": True,
                    "Data": {
                        "DataEntityList": [
                            {
                                "TableName": "dws_order_shipment_split_mkt",
                                "ProjectName": "yh_doc_cdm",
                                "TableGuid": "odps.yh_doc_cdm.dws_order_shipment_split_mkt",
                                "EnvType": 1,
                            }
                        ]
                    },
                }

            def get_meta_table_producing_tasks(self, request):
                self.last_table_guid = request.table_guid
                return {
                    "Success": True,
                    "Data": [
                        {
                            "TaskId": "210002682128",
                            "TaskName": "dws_order_shipment_split_mkt",
                        }
                    ],
                }

            def get_node(self, request):
                return {
                    "Success": True,
                    "Data": {
                        "NodeId": request.node_id,
                        "NodeName": "dws_order_shipment_split_mkt",
                        "CronExpress": "00 30 04-19/4 * * ?",
                        "Connection": "yh_doc_cdm",
                        "ProjectId": 121889,
                        "FileType": 10,
                    },
                }

            def get_node_code(self, request):
                return {
                    "Success": True,
                    "Data": "insert overwrite table yh_doc_cdm.dws_order_shipment_split_mkt select * from src;",
                }

        settings = DataWorksSettings(
            access_id="ak",
            secret_access_key="sk",
            region="cn-beijing",
            project_env="PROD",
            endpoint="dataworks.cn-beijing.aliyuncs.com",
            api_version="2020-05-18",
        )
        sdk = ProducingTaskSdk()
        client = DataWorksReadOnlyClient(settings=settings, sdk_client=sdk)

        rows = resolve_table_logic(
            "yh_doc_cdm.dws_order_shipment_split_mkt",
            catalog_rows=[{"table_type": "MANAGED_TABLE", "view_original_text": None}],
            dataworks_client=client,
            odps_project="yh_doc_cdm",
        )

        self.assertEqual(rows[0]["status"], "ok")
        self.assertEqual(rows[0]["lookup_method"], "meta_table_producing_tasks")
        self.assertEqual(rows[0]["node_id"], 210002682128)
        self.assertEqual(rows[0]["matched_table_guid"], "odps.yh_doc_cdm.dws_order_shipment_split_mkt")
        self.assertEqual(sdk.last_keyword, "dws_order_shipment_split_mkt")
        self.assertIn("insert overwrite table yh_doc_cdm.dws_order_shipment_split_mkt", rows[0]["node_code"])


if __name__ == "__main__":
    unittest.main()
