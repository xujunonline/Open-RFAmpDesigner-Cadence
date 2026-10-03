from __future__ import annotations

import json
import hashlib
import math
import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..cadence.evidence import read_evidenced_metrics
from ..experiments.aggregate_pdk_rf_ladder_fullchain import audit_pdk_rf_ladder_fullchain
from ..experiments.run_active_diagnostic_candidate import _PRIVATE_ROOT
from ..schemas import Spec
from .run_lock import agent_run_lock


_MEMORY_ROOT = _PRIVATE_ROOT.parent / "memory"
_REPORT_ROOT = _PRIVATE_ROOT / "pdk_rf_ladder_fullchain"
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_FACT_METRICS = ("s11_db", "s21_db", "s22_db", "nf_db", "ripple_db", "ip1db_dbm", "power_ma")
_FACT_VIOLATIONS = ("s11_violation", "gain_violation", "nf_violation",
                    "ip1db_violation", "power_violation")


class JsonlMemory:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]


def build_ladder_failure_fact(report_dir: Path) -> dict[str, Any]:
    if (
        not isinstance(report_dir, Path)
        or not _SAFE_ID.fullmatch(report_dir.name)
        or report_dir.parent != _REPORT_ROOT
    ):
        raise ValueError("KB source must be one private ladder fullchain archive")
    audit_pdk_rf_ladder_fullchain(report_dir)
    report = read_evidenced_metrics(report_dir)
    score = report["violations"]
    if (
        report["status"] != "diagnostic_fullchain_unqualified"
        or report["not_lna_result"] is not True
        or report["spec_pass"] is not None
        or report["physical_qualification"] is not False
        or score["status"] != "unverified_score"
        or score["pass"] is not False
        or score["constraints_met"] is not False
    ):
        raise ValueError("KB source is not a verified diagnostic failure")
    spec = Spec(**report["diagnostic_spec"])
    if spec.id != "S1":
        raise ValueError("KB source has an unexpected diagnostic spec")
    metrics = {key: report["metrics"][key] for key in _FACT_METRICS}
    violations = {key: score[key] for key in _FACT_VIOLATIONS}
    if any(type(value) not in {int, float} or not math.isfinite(value)
           for value in (*metrics.values(), *violations.values())):
        raise ValueError("KB source contains nonfinite observations")
    return {
        "schema_version": 1,
        "kind": "diagnostic_failure",
        "source_type": "pdk_rf_ladder_fullchain",
        "run_id": report_dir.name,
        "evidence_manifest_sha256": hashlib.sha256(
            (report_dir / "evidence_manifest.json").read_bytes()
        ).hexdigest(),
        "spec": asdict(spec),
        "metrics": metrics,
        "violations": violations,
        "not_lna_result": True,
        "eligible_for_seed": False,
        "eligible_for_experience": False,
    }


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output = {}
    for key, value in pairs:
        if key in output:
            raise ValueError("KB JSON contains duplicate keys")
        output[key] = value
    return output


def _reject_constant(value: str) -> None:
    raise ValueError(f"KB JSON contains a nonfinite constant: {value}")


class VerifiedFailureKB:
    """Private, append-only diagnostic facts; every read reaudits its raw source."""

    def __init__(self) -> None:
        if _MEMORY_ROOT.is_symlink():
            raise ValueError("KB root must not be a symlink")
        _MEMORY_ROOT.mkdir(parents=True, exist_ok=True)
        self.path = _MEMORY_ROOT / "kb.jsonl"
        if self.path.is_symlink() or (self.path.exists() and not self.path.is_file()):
            raise ValueError("KB path is unsafe")

    def _read_verified(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        if self.path.is_symlink() or self.path.stat().st_size > 2_000_000:
            raise ValueError("KB file is unsafe or too large")
        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        with self.path.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip() or len(line.encode("utf-8")) > 8192 or len(output) >= 1000:
                    raise ValueError("KB line is empty, oversized, or exceeds record limit")
                record = json.loads(
                    line, object_pairs_hook=_unique_object, parse_constant=_reject_constant,
                )
                if not isinstance(record, dict):
                    raise ValueError("KB record must be an object")
                run_id = record.get("run_id")
                if not isinstance(run_id, str) or not _SAFE_ID.fullmatch(run_id) or run_id in seen:
                    raise ValueError("KB run ID is invalid or duplicated")
                if record != build_ladder_failure_fact(_REPORT_ROOT / run_id):
                    raise ValueError("KB record differs from reaudited Spectre evidence")
                seen.add(run_id)
                output.append(record)
        return output

    def append_ladder_failure(self, report_dir: Path) -> dict[str, Any]:
        record = build_ladder_failure_fact(report_dir)
        with agent_run_lock(_MEMORY_ROOT):
            if any(item["run_id"] == record["run_id"] for item in self._read_verified()):
                raise ValueError("KB already contains this evidence run")
            if self.path.is_symlink():
                raise ValueError("KB path changed to a symlink")
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        return record

    def retrieve_failure_context(self, spec: Spec, *, limit: int = 3) -> list[dict[str, Any]]:
        if not isinstance(spec, Spec) or type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError("KB query needs a validated spec and bounded limit")
        hits = []
        for record in self._read_verified():
            source = Spec(**record["spec"])
            center_distance = abs(math.log(source.fc_ghz / spec.fc_ghz))
            bandwidth_distance = abs(source.fbw_ratio - spec.fbw_ratio)
            if center_distance > math.log(1.1) or bandwidth_distance > 0.1:
                continue
            failed = [key.removesuffix("_violation") for key in _FACT_VIOLATIONS
                      if record["violations"][key] > 0]
            hits.append({
                "source_run_id": record["run_id"],
                "evidence_status": "verified_diagnostic_failure",
                "spec_id": source.id,
                "similarity": round(max(0.0, 1 - center_distance / math.log(1.1) / 2
                                        - bandwidth_distance / 0.2), 6),
                "failed_constraints": failed,
                "usable_as_successful_seed": False,
                "usable_as_experience": False,
            })
        return sorted(hits, key=lambda item: (-item["similarity"], item["source_run_id"]))[:limit]
