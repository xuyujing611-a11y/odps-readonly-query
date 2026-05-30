from __future__ import annotations

from collections.abc import Iterable

from .config import OdpsSettings
from .vendor_paths import add_vendor_paths


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


def rows_to_dicts(reader: Iterable) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in reader:
        if hasattr(row, "items"):
            rows.append(dict(row.items()))
        elif hasattr(row, "asdict"):
            rows.append(row.asdict())
        else:
            rows.append({str(index): value for index, value in enumerate(row)})
    return rows


def execute_sql_to_dicts(
    odps,
    sql: str,
    *,
    limit: int | None = None,
    hints: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    instance = odps.execute_sql(sql, hints=hints)
    with instance.open_reader() as reader:
        rows = rows_to_dicts(reader)
    return rows[:limit] if limit is not None else rows
