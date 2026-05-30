from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path

from .encrypted_config import decrypt_env_text


REQUIRED_ENV_KEYS = (
    "ALIBABA_CLOUD_ACCESS_KEY_ID",
    "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
    "ODPS_PROJECT",
    "ODPS_ENDPOINT",
)


@dataclass(frozen=True)
class OdpsSettings:
    access_id: str
    secret_access_key: str
    project: str
    endpoint: str


@dataclass(frozen=True)
class DataWorksSettings:
    access_id: str
    secret_access_key: str
    region: str
    project_env: str
    endpoint: str
    api_version: str
    project_id: str | None = None
    project_identifier: str | None = None


@dataclass(frozen=True)
class RuntimeSettings:
    odps: OdpsSettings
    dataworks: DataWorksSettings


def default_env_path() -> Path:
    return Path(__file__).resolve().parents[1] / ".env"


def default_encrypted_env_path() -> Path:
    return Path(__file__).resolve().parents[1] / ".env.enc"


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _parse_env_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _default_password_provider() -> str:
    return getpass("Password for .env.enc: ")


def _load_env_values(
    env_path: str | Path | None = None,
    *,
    password_provider: Callable[[], str] | None = None,
) -> dict[str, str]:
    path = Path(env_path) if env_path else default_env_path()
    password_provider = password_provider or _default_password_provider

    if path.suffix == ".enc":
        encrypted_path = path
        file_values = _parse_env_text(decrypt_env_text(encrypted_path.read_text(encoding="utf-8"), password_provider()))
    elif path.exists():
        file_values = _parse_env_file(path)
    else:
        encrypted_path = path.with_name(path.name + ".enc")
        if encrypted_path.exists():
            file_values = _parse_env_text(
                decrypt_env_text(encrypted_path.read_text(encoding="utf-8"), password_provider())
            )
        else:
            file_values = {}

    return {**file_values, **os.environ}


def load_settings(
    env_path: str | Path | None = None,
    *,
    password_provider: Callable[[], str] | None = None,
) -> OdpsSettings:
    path = Path(env_path) if env_path else default_env_path()
    merged = _load_env_values(env_path, password_provider=password_provider)
    return _odps_settings_from_values(merged, path)


def _odps_settings_from_values(merged: dict[str, str], path: Path) -> OdpsSettings:
    missing = [key for key in REQUIRED_ENV_KEYS if not merged.get(key)]
    if missing:
        raise ValueError(
            "Missing required ODPS settings: "
            + ", ".join(missing)
            + f". Put them in {path} or process environment variables."
        )

    return OdpsSettings(
        access_id=merged["ALIBABA_CLOUD_ACCESS_KEY_ID"],
        secret_access_key=merged["ALIBABA_CLOUD_ACCESS_KEY_SECRET"],
        project=merged["ODPS_PROJECT"],
        endpoint=merged["ODPS_ENDPOINT"],
    )


def _dataworks_settings_from_values(merged: dict[str, str], path: Path) -> DataWorksSettings:
    missing = [key for key in REQUIRED_ENV_KEYS[:2] if not merged.get(key)]
    if missing:
        raise ValueError(
            "Missing required DataWorks settings: "
            + ", ".join(missing)
            + f". Put them in {path} or process environment variables."
        )

    region = merged.get("DATAWORKS_REGION", "cn-beijing").strip() or "cn-beijing"
    project_env = merged.get("DATAWORKS_PROJECT_ENV", "PROD").strip().upper() or "PROD"
    api_version = merged.get("DATAWORKS_API_VERSION", "2020-05-18").strip() or "2020-05-18"
    endpoint = merged.get("DATAWORKS_ENDPOINT", f"dataworks.{region}.aliyuncs.com").strip()
    project_id = merged.get("DATAWORKS_PROJECT_ID") or None
    project_identifier = merged.get("DATAWORKS_PROJECT_IDENTIFIER") or None

    return DataWorksSettings(
        access_id=merged["ALIBABA_CLOUD_ACCESS_KEY_ID"],
        secret_access_key=merged["ALIBABA_CLOUD_ACCESS_KEY_SECRET"],
        region=region,
        project_env=project_env,
        endpoint=endpoint,
        api_version=api_version,
        project_id=project_id,
        project_identifier=project_identifier,
    )


def load_dataworks_settings(
    env_path: str | Path | None = None,
    *,
    password_provider: Callable[[], str] | None = None,
) -> DataWorksSettings:
    path = Path(env_path) if env_path else default_env_path()
    merged = _load_env_values(env_path, password_provider=password_provider)
    return _dataworks_settings_from_values(merged, path)


def load_runtime_settings(
    env_path: str | Path | None = None,
    *,
    password_provider: Callable[[], str] | None = None,
) -> RuntimeSettings:
    path = Path(env_path) if env_path else default_env_path()
    merged = _load_env_values(env_path, password_provider=password_provider)
    return RuntimeSettings(
        odps=_odps_settings_from_values(merged, path),
        dataworks=_dataworks_settings_from_values(merged, path),
    )
