from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor_runtime"
PIP_CACHE = ROOT / "pip_cache"
PIP_TMP = ROOT / "pip_tmp"
PACKAGES = [
    "pyodps==0.12.6",
    "alibabacloud_dataworks_public20200518==8.0.4",
    "requests==2.34.2",
    "urllib3==2.7.0",
    "idna==3.16",
    "certifi==2026.5.20",
    "chardet==5.2.0",
]


def main() -> int:
    VENDOR.mkdir(exist_ok=True)
    PIP_CACHE.mkdir(exist_ok=True)
    PIP_TMP.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "PIP_CACHE_DIR": str(PIP_CACHE),
        "TEMP": str(PIP_TMP),
        "TMP": str(PIP_TMP),
    }

    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--target",
            str(VENDOR),
            "--cache-dir",
            str(PIP_CACHE),
            *PACKAGES,
        ],
        env=env,
    )

    shutil.rmtree(PIP_TMP, ignore_errors=True)
    print(f"Vendor dependencies are ready: {VENDOR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
