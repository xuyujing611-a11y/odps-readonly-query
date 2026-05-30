from __future__ import annotations

import json


def print_rows(rows: list[dict[str, object]], *, json_output: bool = False) -> None:
    if json_output:
        print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        return

    if not rows:
        print("(no rows)")
        return

    columns = list(rows[0].keys())
    widths = {
        column: max(
            len(str(column)),
            *(len(str(row.get(column, ""))) for row in rows),
        )
        for column in columns
    }
    header = " | ".join(str(column).ljust(widths[column]) for column in columns)
    print(header)
    print("-+-".join("-" * widths[column] for column in columns))
    for row in rows:
        print(" | ".join(str(row.get(column, "")).ljust(widths[column]) for column in columns))

