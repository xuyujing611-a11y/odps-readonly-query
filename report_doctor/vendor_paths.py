from __future__ import annotations

import sys
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def iter_vendor_paths():
    root = project_root()
    for name in ("vendor_runtime", "vendor"):
        path = root / name
        if path.exists():
            yield path


def add_vendor_paths() -> None:
    paths = [str(path) for path in iter_vendor_paths()]
    for path in reversed(paths):
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)
