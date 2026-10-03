from __future__ import annotations

import argparse
import csv
import hashlib
import math
from dataclasses import asdict
from pathlib import Path

from orfadc.config_loader import load_specs
from orfadc.experiments.audit_teaching_three_stage import audit_teaching_three_stage
from orfadc.cadence.evidence import read_evidenced_metrics
from orfadc.schemas import Candidate, Spec


_COLUMNS = ("freq_hz", "freq_ghz", "s11_db", "s21_db", "s22_db", "nf_db", "nfmin_db")


def observe_teaching_three_stage_candidate(run_dir: Path, spec: Spec, candidate: Candidate) -> dict:
    """Rebuild one bounded S1 small-signal observation; never award LNA pass."""
    audit_teaching_three_stage(run_dir)
    evidence = read_evidenced_metrics(run_dir)
    if (
        evidence.get("spec") != asdict(spec)
        or evidence.get("candidate") != candidate.to_dict()
        or evidence.get("run_id") != run_dir.name
        or evidence.get("source") != "cadence_spectre"
        or evidence.get("simulation_status") != "ok"
        or evidence.get("not_lna_result") is not True
        or evidence.get("spec_pass") is not None
    ):
        raise ValueError("three-stage observation does not match the evidenced candidate/spec")
    with (run_dir / "waveforms.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ValueError("three-stage observation waveform columns differ")
        rows = [{key: float(value[key]) for key in _COLUMNS} for value in reader]
    low, high = spec.band_edges_ghz
    band = [row for row in rows if low - 1e-10 <= row["freq_ghz"] <= high + 1e-10]
    if (
        len(band) < 3
        or not math.isclose(band[0]["freq_ghz"], low, abs_tol=1e-9)
        or not math.isclose(band[-1]["freq_ghz"], high, abs_tol=1e-9)
        or any(not math.isfinite(value) for row in band for value in row.values())
    ):
        raise ValueError("three-stage observation does not cover a finite S1 band")
    s21 = [row["s21_db"] for row in band]
    return {
        "schema_version": 1,
        "status": "raw_audited_teaching_small_signal",
        "run_id": run_dir.name,
        "candidate_id": candidate.candidate_id,
        "spec_id": spec.id,
        "seed": candidate.seed,
        "evidence_manifest_sha256": hashlib.sha256(
            (run_dir / "evidence_manifest.json").read_bytes()
        ).hexdigest(),
        "frequency_band_ghz": {"low": low, "high": high},
        "band_points": len(band),
        "s11_worst_db": max(row["s11_db"] for row in band),
        "s21_worst_db": min(s21),
        "s22_worst_db": max(row["s22_db"] for row in band),
        "nf_worst_db": max(row["nf_db"] for row in band),
        "s21_ripple_db": max(s21) - min(s21),
        "supply_current_ma": evidence["metrics"]["supply_current_ma"],
        "compression_status": "not_measured",
        "not_lna_result": True,
        "spec_pass": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild one audited three-stage S1 candidate observation")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--specs", type=Path, default=Path("config/specs_table_iii.yaml"))
    args = parser.parse_args()
    evidence = read_evidenced_metrics(args.run_dir)
    specs = {item.id: item for item in load_specs(args.specs)}
    if (
        not isinstance(evidence.get("candidate"), dict)
        or not isinstance(evidence.get("spec"), dict)
        or evidence["spec"].get("id") not in specs
    ):
        parser.error("run lacks a supported candidate/spec context")
    candidate = Candidate(**evidence["candidate"])
    if candidate.spec_id not in specs:
        parser.error("candidate spec is unsupported")
    try:
        result = observe_teaching_three_stage_candidate(args.run_dir, specs[candidate.spec_id], candidate)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(type(exc).__name__)
    print(
        f"status={result['status']} points={result['band_points']} "
        f"s21_worst_db={result['s21_worst_db']:.6f} not_lna_result=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
