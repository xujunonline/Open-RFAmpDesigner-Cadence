from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.experiments.audit_inflight_lost_reply import audit_inflight_lost_reply
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT


_TRACE = _PRIVATE_ROOT / "agent_inflight_probe" / "20260927T155701Z_64fdb795"
_TEMPLATE = _PRIVATE_ROOT / "lna_stage03" / "private_schematic_core" / "v2_raw_20260926_01" / "netlist.scs"


def _audit(trace: Path) -> dict:
    digest = hashlib.sha256(_TEMPLATE.read_bytes()).hexdigest()
    return audit_inflight_lost_reply(trace, _PRIVATE_ROOT, template=_TEMPLATE, template_sha256=digest)


def test_real_inflight_lost_reply_recovered_diagnostic_is_auditable() -> None:
    if not _TRACE.is_dir():
        pytest.skip("private real in-flight probe is unavailable")
    report = _audit(_TRACE)
    assert report["status"] == "inflight_seen_and_recovered_diagnostic"
    assert report["samples"] >= 1
    assert report["points"] == 47
    assert report["spec_pass"] is None


@pytest.mark.parametrize("mutation", ["raw_active", "parsed_active", "remote_dir", "lost_reply"])
def test_inflight_audit_rejects_tampered_private_trace(mutation: str) -> None:
    if not _TRACE.is_dir():
        pytest.skip("private real in-flight probe is unavailable")
    with tempfile.TemporaryDirectory(prefix="inflight_audit_", dir=_PRIVATE_ROOT.resolve()) as root:
        copied = Path(root) / _TRACE.name
        shutil.copytree(_TRACE, copied)
        if mutation == "lost_reply":
            path = copied / "lost_reply_probe.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["spectre_calls"] = 2
        else:
            path = copied / "inflight_probe.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            if mutation == "raw_active":
                payload["samples"][0]["raw_stdout"] = payload["samples"][0]["raw_stdout"].replace(
                    "active=1", "active=0",
                )
            elif mutation == "parsed_active":
                payload["samples"][0]["parsed"]["spectre_active"] = False
            else:
                payload["remote_dir_sha256"] = "0" * 64
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            _audit(copied)
