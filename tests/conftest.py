"""Shared pytest configuration.

Several Cadence-diagnostic entry points refuse to write outside the private
``results/runs`` root (a deliberate safety rule).  Their tests therefore need
``tmp_path`` to live under that root.  Earlier the README asked for
``--basetemp=results/runs/...`` on every invocation and a plain ``pytest``
failed 9 tests; this hook applies the same default automatically.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("ORFADC_RUN_LIVE_SSH_AUDIT", "0")


def pytest_configure(config):  # noqa: D103
    if not config.option.basetemp:
        base = ROOT / "results" / "runs" / f"pytest_{time.strftime('%Y%m%dT%H%M%S')}_{os.getpid()}"
        base.parent.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(base)
