from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from .config import DataWorksSettings
from .vendor_paths import add_vendor_paths


class DataWorksClientError(RuntimeError):
    """Raised when the DataWorks read-only client cannot query metadata."""


def normalize_response(value: Any) -> dict[str, Any]:
    body = getattr(value, "body", value)
    if hasattr(body, "to_map"):
        body = body.to_map()
    if isinstance(body, dict):
        return body
    if hasattr(body, "__dict__"):
        return {key: item for key, item in vars(body).items() if not key.startswith("_")}
    return {"Data": body}


@dataclass
class DataWorksReadOnlyClient:
    settings: DataWorksSettings
    sdk_client: Any
    models: Any | None = None

    @property
    def project_env(self) -> str:
        return self.settings.project_env

    @classmethod
    def from_settings(cls, settings: DataWorksSettings) -> "DataWorksReadOnlyClient":
        if settings.api_version != "2020-05-18":
            raise DataWorksClientError(
                "Only DataWorks OpenAPI 2020-05-18 is wired for this read-only fallback. "
                "Set DATAWORKS_API_VERSION=2020-05-18 or add a 2024 adapter."
            )

        add_vendor_paths()

        try:
            from alibabacloud_dataworks_public20200518.client import Client
            from alibabacloud_dataworks_public20200518 import models
            from alibabacloud_tea_openapi.models import Config
        except ImportError as exc:
            raise DataWorksClientError(
                "DataWorks SDK is not installed in the local vendor environment. "
                "Run scripts\\bootstrap_vendor.py or install alibabacloud_dataworks_public20200518."
            ) from exc

        config = Config(
            access_key_id=settings.access_id,
            access_key_secret=settings.secret_access_key,
            endpoint=settings.endpoint,
        )
        return cls(settings=settings, sdk_client=Client(config), models=models)

    def _request(self, name: str, **kwargs: Any) -> Any:
        if self.models and hasattr(self.models, name):
            return getattr(self.models, name)(**kwargs)
        return SimpleNamespace(**kwargs)

    def _call(self, method_name: str, request_name: str, **kwargs: Any) -> dict[str, Any]:
        method = getattr(self.sdk_client, method_name)
        response = normalize_response(method(self._request(request_name, **kwargs)))
        success = response.get("Success")
        if success is False or success == "false":
            raise DataWorksClientError(
                str(response.get("ErrorMessage") or response.get("ErrorCode") or "DataWorks request failed.")
            )
        return response

    def find_nodes_by_outputs(self, outputs: list[str]) -> list[dict[str, Any]]:
        response = self._call(
            "list_nodes_by_output",
            "ListNodesByOutputRequest",
            project_env=self.settings.project_env,
            outputs=",".join(outputs),
        )
        data = response.get("Data") or []
        return data if isinstance(data, list) else [data]

    def search_meta_tables(self, keyword: str, *, page_size: int = 20) -> list[dict[str, Any]]:
        response = self._call(
            "search_meta_tables",
            "SearchMetaTablesRequest",
            keyword=keyword,
            data_source_type="odps",
            page_number=1,
            page_size=page_size,
        )
        data = response.get("Data") or {}
        if isinstance(data, dict):
            rows = data.get("DataEntityList") or data.get("data_entity_list") or []
        else:
            rows = data
        return rows if isinstance(rows, list) else [rows]

    def get_meta_table_producing_tasks(self, table_guid: str, *, table_name: str | None = None) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "table_guid": table_guid,
            "data_source_type": "odps",
        }
        if table_name:
            kwargs["table_name"] = table_name
        response = self._call(
            "get_meta_table_producing_tasks",
            "GetMetaTableProducingTasksRequest",
            **kwargs,
        )
        data = response.get("Data") or []
        return data if isinstance(data, list) else [data]

    def get_node(self, node_id: int) -> dict[str, Any]:
        response = self._call(
            "get_node",
            "GetNodeRequest",
            node_id=int(node_id),
            project_env=self.settings.project_env,
        )
        data = response.get("Data") or {}
        return data if isinstance(data, dict) else {"Data": data}

    def get_node_code(self, node_id: int) -> str:
        response = self._call(
            "get_node_code",
            "GetNodeCodeRequest",
            node_id=int(node_id),
            project_env=self.settings.project_env,
        )
        return str(response.get("Data") or "")
