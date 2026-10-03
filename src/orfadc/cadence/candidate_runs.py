from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from orfadc.schemas import Candidate, Spec


_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_WINDOWS_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL"})


def _segment(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SEGMENT_RE.fullmatch(value):
        raise ValueError(f"{label} is not a safe path segment")
    if value.upper().split(".", 1)[0] in _WINDOWS_RESERVED or re.fullmatch(
        r"(?:COM|LPT)[1-9]", value.upper().split(".", 1)[0]
    ):
        raise ValueError(f"{label} is a reserved path segment")
    if value.endswith("."):
        raise ValueError(f"{label} is not a portable path segment")
    return value


def reserve_candidate_run(
    runs_root: Path,
    spec: Spec,
    candidate: Candidate,
    *,
    run_id: str | None = None,
) -> Path:
    """Create one exclusive run directory; never reuse a prior candidate run."""
    if candidate.spec_id != spec.id or type(candidate.seed) is not int or candidate.seed < 0:
        raise ValueError("candidate does not match a valid spec/seed context")
    if not runs_root.is_dir() or runs_root.is_symlink():
        raise ValueError("runs root must be an existing non-symlink directory")

    spec_name = _segment(spec.id, "spec id")
    candidate_name = _segment(candidate.candidate_id, "candidate id")
    if run_id is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"{stamp}_{uuid.uuid4().hex[:8]}"
    run_name = _segment(run_id, "run id")

    parent = runs_root / spec_name / f"seed{candidate.seed}" / candidate_name
    cursor = runs_root
    for part in (spec_name, f"seed{candidate.seed}", candidate_name):
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("run path contains a symlink")
        cursor.mkdir(exist_ok=True)
        if cursor.is_symlink() or not cursor.is_dir():
            raise ValueError("run path is not a directory")
    run_dir = parent / run_name
    run_dir.mkdir(exist_ok=False)
    return run_dir
