from __future__ import annotations

from collections.abc import Iterable

from .config import DEFAULT_ODPS_SQL_TIMEOUT_SECONDS, OdpsSettings
from .vendor_paths import add_vendor_paths


class OdpsQueryTimeoutError(TimeoutError):
    """Raised when a submitted ODPS SQL instance exceeds the configured timeout."""


def make_odps(settings: OdpsSettings):
    add_vendor_paths()

    try:
        from odps import ODPS
    except ImportError as exc:
        raise RuntimeError(
            "PyODPS is not installed. Run: python .\\scripts\\bootstrap_vendor.py"
        ) from exc

    return ODPS(
        settings.access_id,
        settings.secret_access_key,
        settings.project,
        endpoint=settings.endpoint,
    )


def _is_key_value_pair(value: object) -> bool:
    return isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str)


def rows_to_dicts(reader: Iterable) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in reader:
        if hasattr(row, "items"):
            rows.append(dict(row.items()))
        elif hasattr(row, "asdict"):
            rows.append(row.asdict())
        else:
            values = list(row)
            if values and all(_is_key_value_pair(value) for value in values):
                rows.append({key: value for key, value in values})
            else:
                rows.append({str(index): value for index, value in enumerate(values)})
    return rows


def _is_wait_timeout_error(exc: Exception) -> bool:
    try:
        add_vendor_paths()
        from odps.errors import WaitTimeoutError
    except ImportError:
        return exc.__class__.__name__ == "WaitTimeoutError"
    return isinstance(exc, WaitTimeoutError)


def _stop_instance_best_effort(instance) -> bool:
    stop = getattr(instance, "stop", None)
    if not callable(stop):
        return False
    try:
        stop()
    except Exception:
        return False
    return True


def execute_sql_to_dicts(
    odps,
    sql: str,
    *,
    limit: int | None = None,
    hints: dict[str, str] | None = None,
    timeout_seconds: int | None = DEFAULT_ODPS_SQL_TIMEOUT_SECONDS,
) -> list[dict[str, object]]:
    instance = odps.run_sql(sql, hints=hints)
    try:
        instance.wait_for_success(timeout=timeout_seconds)
    except Exception as exc:
        if not _is_wait_timeout_error(exc):
            raise
        stopped = _stop_instance_best_effort(instance)
        instance_id = getattr(instance, "id", None)
        instance_text = f" instance={instance_id}" if instance_id else ""
        stop_text = "attempted to stop the instance" if stopped else "could not stop the instance automatically"
        raise OdpsQueryTimeoutError(
            f"ODPS SQL timed out after {timeout_seconds} seconds; {stop_text}.{instance_text}"
        ) from exc
    with instance.open_reader() as reader:
        rows = rows_to_dicts(reader)
    return rows[:limit] if limit is not None else rows
