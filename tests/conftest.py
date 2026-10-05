"""Shared pytest configuration.

Keeps pytest's ``tmp_path`` under the git-ignored ``results/runs`` root so test
artefacts never land in tracked folders.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def pytest_configure(config):  # noqa: D103
    if not config.option.basetemp:
        base = ROOT / "results" / "runs" / f"pytest_{time.strftime('%Y%m%dT%H%M%S')}_{os.getpid()}"
        base.parent.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(base)
