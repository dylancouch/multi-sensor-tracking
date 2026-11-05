"""Shared, path-free source and environment provenance."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import scipy


def source_state() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    if not (root / ".git").exists():
        return {"revision": None, "dirty": None}
    try:
        revision = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return {"revision": None, "dirty": None}
    if revision.returncode != 0 or status.returncode != 0:
        return {"revision": None, "dirty": None}
    return {"revision": revision.stdout.strip(), "dirty": bool(status.stdout.strip())}


def environment_versions() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "architecture": platform.machine(),
        "logical_cpus": os.cpu_count(),
        "platform": sys.platform,
        "numpy": np.__version__,
        "scipy": scipy.__version__,
    }
