from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest
from PIL import Image

from orfadc.experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT
from orfadc.plots.plot_teaching_stage2_efficiency import (
    _render, _series, audit_teaching_stage2_plot,
)


_SOURCE = _PRIVATE_ROOT / "teaching_stage2_multiseed" / "20260927T033634Z_f6923862"
_PLOT = _PRIVATE_ROOT / "teaching_stage2_plots" / "20260927T043054Z_1c5c5a35"


def _private() -> Path:
    if not _SOURCE.is_dir() or not _PLOT.is_dir():
        pytest.skip("private teaching multiseed and plot archives are unavailable")
    return _PLOT


def test_real_plot_reaudits_without_paper_claim() -> None:
    result = audit_teaching_stage2_plot(_private())
    assert result == {
        "status": "verified", "seed_count": 5,
        "budget_per_method": 4, "not_lna_result": True,
    }
    with Image.open(_PLOT / "teaching_stage2_sample_efficiency.png") as image:
        assert image.size == (1200, 760)
        assert len(image.getcolors(maxcolors=100000)) > 10


@pytest.mark.parametrize("mutation", ("image", "source_hash", "false_lna", "false_paper", "run_id"))
def test_plot_audit_rejects_tampered_archive(mutation: str) -> None:
    source = _private()
    with tempfile.TemporaryDirectory(prefix="test_teaching_plot_", dir=_PRIVATE_ROOT.resolve()) as root:
        copied = Path(root) / source.name
        shutil.copytree(source, copied)
        if mutation == "image":
            path = copied / "teaching_stage2_sample_efficiency.png"
            path.write_bytes(path.read_bytes() + b"tampered")
        else:
            path = copied / "metrics.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            if mutation == "source_hash":
                payload["source_manifest_sha256"] = "0" * 64
            elif mutation == "false_lna":
                payload["not_lna_result"] = False
            elif mutation == "false_paper":
                payload["spec_pass"] = True
            else:
                payload["run_id"] = "other_run"
            path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            audit_teaching_stage2_plot(copied)


@pytest.mark.parametrize("rows", (
    [{"evaluations": 2, "random_mean_best": 2.0, "pso_mean_best": 1.0}],
    [{"evaluations": 1, "random_mean_best": float("nan"), "pso_mean_best": 1.0},
     {"evaluations": 2, "random_mean_best": 1.0, "pso_mean_best": 1.0}],
))
def test_plot_rejects_missing_or_nonfinite_samples(rows: list[dict]) -> None:
    with pytest.raises(ValueError):
        _series({"budget_per_method": 2, "per_evaluation": rows})


def test_plot_renderer_is_deterministic() -> None:
    source = {
        "run_id": "toy", "seed_count": 2, "budget_per_method": 2,
        "per_evaluation": [
            {"evaluations": 1, "random_mean_best": 4.0, "pso_mean_best": 4.0},
            {"evaluations": 2, "random_mean_best": 3.0, "pso_mean_best": 2.5},
        ],
    }
    assert _render(source) == _render(source)
