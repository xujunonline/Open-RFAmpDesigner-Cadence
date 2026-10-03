from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.cadence.remote_runner import RemoteRunner, load_remote_config
from orfadc.experiments.audit_live_ssh_disconnect import audit_live_ssh_disconnect
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT


_TRACE = _PRIVATE_ROOT / "agent_live_disconnect_probe" / "20260927T161928Z_8de49aaa"
_CONFIG = Path("config/remote_cadence.local.yaml")


def _audit(trace: Path) -> dict:
    return audit_live_ssh_disconnect(trace, _PRIVATE_ROOT, RemoteRunner(load_remote_config(_CONFIG)))


def _require_live_opt_in() -> None:
    if os.environ.get("ORFADC_RUN_LIVE_SSH_AUDIT") != "1":
        pytest.skip("live SSH audit requires ORFADC_RUN_LIVE_SSH_AUDIT=1")


def test_real_live_disconnect_remains_pending_without_replay() -> None:
    _require_live_opt_in()
    if not _TRACE.is_dir() or not _CONFIG.is_file():
        pytest.skip("private live SSH disconnect probe is unavailable")
    report = _audit(_TRACE)
    assert report["status"] == "live_ssh_disconnected_remote_quiescent_incomplete"
    assert report["safe_to_dispatch"] is False
    assert report["safe_to_reconcile"] is False
    assert report["spec_pass"] is None


@pytest.mark.parametrize("mutation", ["raw_active", "parsed_active", "termination", "remote_dir"])
def test_live_disconnect_audit_rejects_tampered_trace(mutation: str) -> None:
    _require_live_opt_in()
    if not _TRACE.is_dir() or not _CONFIG.is_file():
        pytest.skip("private live SSH disconnect probe is unavailable")
    with tempfile.TemporaryDirectory(prefix="live_disconnect_audit_", dir=_PRIVATE_ROOT.resolve()) as root:
        copied = Path(root) / _TRACE.name
        shutil.copytree(_TRACE, copied)
        path = copied / "live_disconnect_probe.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if mutation == "raw_active":
            payload["samples"][0]["raw_stdout"] = payload["samples"][0]["raw_stdout"].replace(
                "active=1", "active=0",
            )
        elif mutation == "parsed_active":
            payload["samples"][0]["parsed"]["spectre_active"] = False
        elif mutation == "termination":
            payload["local_ssh_terminated"] = False
        else:
            payload["remote_dir_sha256"] = "0" * 64
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            _audit(copied)
