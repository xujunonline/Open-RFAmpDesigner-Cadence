from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("skopt")

from orfadc.cadence.evidence import build_evidence_manifest
from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT
from orfadc.plots.plot_teaching_stage2_five_methods import (
    audit_teaching_stage2_five_method_plot,
)


_PLOT = _PRIVATE_ROOT / "teaching_stage2_plots" / "20260927T124542Z_aac7e263"


def _private() -> Path:
    if not _PLOT.is_dir():
        pytest.skip("private teaching five-method plot is unavailable")
    return _PLOT


def test_real_five_method_plot_is_reproducible() -> None:
    assert audit_teaching_stage2_five_method_plot(_private()) == {
        "status": "verified", "seed_count": 5,
        "budget_per_method": 4, "not_lna_result": True,
    }


@pytest.mark.parametrize("mutation", ("png", "source", "qualification"))
def test_five_method_plot_rejects_rehashed_tampering(mutation: str) -> None:
    source = _private()
    with tempfile.TemporaryDirectory(prefix="test_five_method_plot_", dir=_PRIVATE_ROOT.resolve()) as root:
        plot_dir = Path(root) / source.name
        shutil.copytree(source, plot_dir)
        if mutation == "png":
            path = plot_dir / "teaching_stage2_five_methods.png"
            path.write_bytes(path.read_bytes() + b"changed")
        else:
            path = plot_dir / "metrics.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            if mutation == "source":
                payload["source_manifest_sha256"] = "0" * 64
            else:
                payload["not_lna_result"] = False
            path.write_text(json.dumps(payload), encoding="utf-8")
        manifest = build_evidence_manifest(plot_dir, {
            "metrics": "metrics.json", "figure": "teaching_stage2_five_methods.png",
        })
        (plot_dir / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(ValueError):
            audit_teaching_stage2_five_method_plot(plot_dir)
