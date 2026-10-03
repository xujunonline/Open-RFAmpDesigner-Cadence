from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from pathlib import Path

from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.experiments.extract_active_oa import extract_active_oa
from orfadc.experiments.run_active_diagnostic_candidate import (
    _SUPPLY_LINE,
    _read_ade_companion,
    render_active_diagnostic_netlist,
)
from orfadc.schemas import Candidate, Spec


_RAW_ARTIFACTS = {
    "metrics", "candidate", "netlist", "spectre_log", "waveforms",
    "dc_raw", "sp_raw", "noise_raw", "stdout", "stderr",
}
_RECOVERY_MODE = "remote_quiescent_download_v1"
_RECOVERED_ARTIFACTS = (_RAW_ARTIFACTS - {"stdout", "stderr"}) | {
    "ade_companion", "recovery_provenance",
}
_RECOVERY_FILES = (
    "netlist.scs", "ade_e.scs", "spectre.log",
    "psf/dcOp.dc", "psf/sp.sp", "psf/sp.noise.sp",
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CSV_COLUMNS = ("freq_hz", "freq_ghz", "s11_db", "s21_db", "s22_db", "nf_db", "nfmin_db")


def _audit_recovery_provenance(run_dir: Path, saved: dict, candidate: Candidate, spec: Spec) -> None:
    path = run_dir / "recovery_provenance.json"
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 8192:
        raise ValueError("recovered diagnostic provenance is missing or unsafe")
    raw = path.read_bytes()
    if saved.get("recovery_provenance_sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("recovered diagnostic provenance digest differs")
    try:
        record = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("recovered diagnostic provenance is malformed") from exc
    if (
        not isinstance(record, dict) or set(record) != {
            "schema_version", "mode", "trace_id", "spec_id", "seed", "candidate_id",
            "run_id", "remote_identity_sha256", "remote_dir_sha256",
            "remote_artifacts_sha256", "controller_stdout_stderr_captured",
            "spectre_dispatched_by_recovery",
        }
        or record["schema_version"] != 1 or type(record["schema_version"]) is not int
        or record["mode"] != _RECOVERY_MODE
        or record["spec_id"] != spec.id or record["seed"] != candidate.seed
        or record["candidate_id"] != candidate.candidate_id
        or record["run_id"] != run_dir.name
        or not isinstance(record["trace_id"], str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", record["trace_id"])
        or any(not isinstance(record[key], str) or not _SHA256.fullmatch(record[key])
               for key in ("remote_identity_sha256", "remote_dir_sha256"))
        or record["controller_stdout_stderr_captured"] is not False
        or record["spectre_dispatched_by_recovery"] is not False
        or not isinstance(record["remote_artifacts_sha256"], dict)
        or set(record["remote_artifacts_sha256"]) != set(_RECOVERY_FILES)
    ):
        raise ValueError("recovered diagnostic provenance context is invalid")
    for name, digest in record["remote_artifacts_sha256"].items():
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ValueError("recovered diagnostic source hash is invalid")
        path = run_dir / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("recovered diagnostic bytes differ from the remote snapshot")


def audit_active_diagnostic_candidate(
    run_dir: Path, *, template: Path, template_sha256: str,
) -> dict:
    """Rebuild a completed, non-LNA RD/VBIAS run from archived source and PSFASCII."""
    if not isinstance(run_dir, Path) or not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("active diagnostic archive is missing or unsafe")
    saved = read_evidenced_metrics(run_dir)
    manifest = json.loads((run_dir / "evidence_manifest.json").read_text(encoding="utf-8"))
    artifacts = manifest["artifacts"]
    recovery_mode = saved.get("recovery_mode")
    if recovery_mode is None:
        if (not _RAW_ARTIFACTS.issubset(artifacts)
                or "recovery_provenance" in artifacts
                or (run_dir / "recovery_provenance.json").exists()):
            raise ValueError("active diagnostic archive lacks required raw artifacts")
    elif recovery_mode == _RECOVERY_MODE:
        if (
            not _RECOVERED_ARTIFACTS.issubset(artifacts)
            or "stdout" in artifacts or "stderr" in artifacts
            or any((run_dir / name).exists() or (run_dir / name).is_symlink()
                   for name in ("spectre.stdout.log", "spectre.stderr.log"))
            or saved.get("controller_stdout_stderr_captured") is not False
        ):
            raise ValueError("recovered diagnostic cannot claim control-process logs")
    else:
        raise ValueError("unsupported diagnostic recovery mode")
    if (
        saved.get("run_id") != run_dir.name
        or saved.get("status") != "ok_with_warnings"
        or saved.get("simulation_status") != "ok"
        or saved.get("source") != "cadence_spectre"
        or saved.get("source_run_kind") != "oa_netlist_derivative_bias_load_direct_spectre"
        or saved.get("circuit_class") != "active_common_source_smoke"
        or saved.get("not_lna_result") is not True
        or saved.get("spec_pass") is not None
        or saved.get("analysis") != ["dc", "sp", "noise"]
        or saved.get("template_sha256") != template_sha256
        or saved.get("source_template_sha256") != template_sha256
    ):
        raise ValueError("active diagnostic archive has incompatible provenance or result class")
    try:
        candidate = Candidate(**saved["candidate"])
        spec = Spec(**saved["spec"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("active diagnostic candidate context is invalid") from exc
    if candidate.spec_id != spec.id or candidate.seed != saved.get("seed"):
        raise ValueError("active diagnostic candidate context differs from spec")
    if recovery_mode == _RECOVERY_MODE:
        _audit_recovery_provenance(run_dir, saved, candidate, spec)
    netlist = render_active_diagnostic_netlist(candidate, template, template_sha256)
    if (run_dir / "netlist.scs").read_bytes() != netlist.encode("utf-8"):
        raise ValueError("active diagnostic archived netlist differs from the OA derivative")
    companion = _read_ade_companion(template, netlist)
    companion_path = run_dir / "ade_e.scs"
    if companion is None:
        if companion_path.exists() or "ade_companion" in artifacts:
            raise ValueError("unexpected active diagnostic OA companion")
    elif "ade_companion" not in artifacts or companion_path.read_bytes() != companion:
        raise ValueError("active diagnostic OA companion differs from source")
    supply = _SUPPLY_LINE.findall(netlist)
    if len(supply) != 1:
        raise ValueError("active diagnostic supply is missing or ambiguous")
    rows, rebuilt = extract_active_oa(
        run_dir / "psf", run_id=run_dir.name, supply_voltage_v=float(supply[0]),
        source_run_kind="oa_netlist_derivative_bias_load_direct_spectre",
    )
    for key in (
        "status", "simulation_status", "source", "raw_format", "source_run_kind",
        "circuit_class", "not_lna_result", "spec_pass", "analysis",
        "frequency_band_ghz", "reference_planes", "reference_plane_evidence",
        "units", "metrics", "stability", "points", "warnings",
    ):
        if saved.get(key) != rebuilt[key]:
            raise ValueError(f"active diagnostic {key} differs from raw PSFASCII")
    with (run_dir / "waveforms.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _CSV_COLUMNS:
            raise ValueError("active diagnostic CSV columns differ")
        csv_rows = list(reader)
    if len(csv_rows) != len(rows):
        raise ValueError("active diagnostic CSV point count differs")
    for actual, expected in zip(csv_rows, rows, strict=True):
        if any(not math.isclose(float(actual[key]), expected[key], rel_tol=1e-12, abs_tol=1e-12)
               for key in _CSV_COLUMNS):
            raise ValueError("active diagnostic CSV differs from raw PSFASCII")
    return saved
