from __future__ import annotations

import re
from pathlib import Path
from string import Template


_TOKEN_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def render_sql_template(path: str | Path, parameters: dict[str, str]) -> str:
    sql_path = Path(path)
    template_text = sql_path.read_text(encoding="utf-8")
    required = sorted(set(_TOKEN_RE.findall(template_text)))
    missing = [name for name in required if name not in parameters]
    if missing:
        raise KeyError(f"Missing SQL template parameters: {', '.join(missing)}")
    return Template(template_text).substitute(parameters)

