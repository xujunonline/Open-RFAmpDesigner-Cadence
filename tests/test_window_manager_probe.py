from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.experiments.audit_window_manager_probe import audit_window_manager_probe
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT


_RUN = _PRIVATE_ROOT / "window_manager_probe" / "20260927T130445Z_0c200f55"


def _private() -> Path:
    if not _RUN.is_dir():
        pytest.skip("private Xvfb/Mutter probe is unavailable")
    return _RUN


def test_real_isolated_window_manager_registers_without_cadence() -> None:
    assert audit_window_manager_probe(_private()) == {
        "status": "verified", "wm_registered": True, "cadence_launched": False,
    }


@pytest.mark.parametrize("mutation", ("metrics", "property", "script"))
def test_window_manager_probe_rejects_rehashed_tampering(mutation: str) -> None:
    source = _private()
    with tempfile.TemporaryDirectory(prefix="test_wm_probe_", dir=_PRIVATE_ROOT.resolve()) as root:
        copied = Path(root) / source.name
        shutil.copytree(source, copied)
        if mutation == "metrics":
            path = copied / "metrics.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["wm_registered_at_probe"] = False
            path.write_text(json.dumps(payload), encoding="utf-8")
        elif mutation == "property":
            (copied / "wm_property.txt").write_text("_NET_SUPPORTING_WM_CHECK: not found.\n", encoding="utf-8")
        else:
            path = copied / "run_window_manager_probe.sh"
            path.write_bytes(path.read_bytes() + b"\n# changed\n")
        artifacts = {key: entry["path"] for key, entry in json.loads(
            (copied / "evidence_manifest.json").read_text(encoding="utf-8")
        )["artifacts"].items()}
        manifest = build_evidence_manifest(copied, artifacts)
        (copied / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(ValueError):
            audit_window_manager_probe(copied)
