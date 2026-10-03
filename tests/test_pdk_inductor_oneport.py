from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from orfadc.cadence.evidence import build_evidence_manifest, read_evidenced_metrics
from orfadc.experiments.audit_pdk_inductor_oneport import (
    audit_pdk_inductor_oneport, compare_pdk_inductor_width_pair,
)


_REAL = Path("results/runs/passive_quality_reference/20260926T205333Z_b96aea29")
_W7 = Path("results/runs/passive_quality_reference/20260926T211116Z_4bb251a3")


def _copy_and_rehash(tmp_path: Path, change) -> Path:
    if not _REAL.is_dir():
        pytest.skip("private PDK one-port archive is unavailable")
    copied = tmp_path / _REAL.name
    shutil.copytree(_REAL, copied)
    change(copied)
    manifest = copied / "evidence_manifest.json"
    old = json.loads(manifest.read_text(encoding="utf-8"))
    artifacts = {key: entry["path"] for key, entry in old["artifacts"].items()}
    manifest.write_text(json.dumps(build_evidence_manifest(copied, artifacts)), encoding="utf-8")
    return copied


def test_real_default_pdk_inductor_rebuilds_without_physical_qualification() -> None:
    if not _REAL.is_dir():
        pytest.skip("private PDK one-port archive is unavailable")
    assert audit_pdk_inductor_oneport(_REAL)["status"] == "verified"
    payload = read_evidenced_metrics(_REAL)
    assert payload["points"] == 591
    assert payload["spectre_warning_count"] == 5
    assert payload["spectre_warning_codes"] == ["SFE-1131"]
    assert payload["metrics"]["minimum_q_in_band"] == pytest.approx(10.52424026198)
    assert payload["metrics"]["status"] == "response_screen_fail"
    assert payload["metrics"]["observed_srf_hz"] is None
    assert payload["physical_qualification"] is False
    assert payload["spec_pass"] is None


def test_real_width_property_pair_rebuilds_without_cdf_qualification() -> None:
    if not _REAL.is_dir() or not _W7.is_dir():
        pytest.skip("private PDK one-port width pair is unavailable")
    result = compare_pdk_inductor_width_pair(_REAL, _W7)
    assert result["status"] == "verified"
    assert result["maximum_complex_s11_delta"] == pytest.approx(0.04082155898)
    assert result["minimum_q_variant"] == pytest.approx(10.51541185977)
    assert result["cdf_callback_validated"] is False
    assert result["physical_qualification"] is False


def test_rehashed_pdk_response_pass_claim_is_rejected(tmp_path: Path) -> None:
    def change(copied: Path) -> None:
        target = copied / "metrics.json"
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload["metrics"]["status"] = "response_screen_pass"
        target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="metrics differ from raw"):
        audit_pdk_inductor_oneport(_copy_and_rehash(tmp_path, change))


def test_rehashed_pdk_run_status_qualification_claim_is_rejected(tmp_path: Path) -> None:
    def change(copied: Path) -> None:
        target = copied / "run_status.json"
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload["physical_qualification"] = True
        target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="source snapshot or run status"):
        audit_pdk_inductor_oneport(_copy_and_rehash(tmp_path, change))


def test_rehashed_pdk_quality_csv_tamper_is_rejected(tmp_path: Path) -> None:
    def change(copied: Path) -> None:
        target = copied / "quality.csv"
        lines = target.read_text(encoding="utf-8").splitlines()
        fields = lines[1].split(",")
        fields[5] = str(float(fields[5]) + 1)
        lines[1] = ",".join(fields)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="CSV differs"):
        audit_pdk_inductor_oneport(_copy_and_rehash(tmp_path, change))
