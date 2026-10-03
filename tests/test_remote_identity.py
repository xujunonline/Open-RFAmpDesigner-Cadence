from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from orfadc.agents.executor import execute_manager_planned
from orfadc.agents.journal import inspect_journal
from orfadc.agents.manager import Manager
from orfadc.agents.remote_identity import (
    read_remote_identity_snapshot, remote_identity, write_remote_identity_snapshot,
)
from orfadc.cadence.remote_runner import RemoteCadenceConfig
from orfadc.schemas import Spec


def _config() -> RemoteCadenceConfig:
    return RemoteCadenceConfig(
        host="example.org", user="student", port=2222,
        remote_root="/tmp/agent_runs", strict_host_key_checking="yes",
    )


def _spec() -> Spec:
    return Spec("S1", 10.0, 0.2, 10.0, 10.0, 3.0, -15.0)


def test_remote_identity_snapshot_is_canonical_and_exclusive(tmp_path: Path) -> None:
    digest = write_remote_identity_snapshot(tmp_path, _config())
    assert len(digest) == 64
    assert read_remote_identity_snapshot(tmp_path, digest) == remote_identity(_config())
    assert "identity_file" in json.loads((tmp_path / "agent_remote.json").read_text(encoding="ascii"))
    with pytest.raises(FileExistsError):
        write_remote_identity_snapshot(tmp_path, _config())
    with pytest.raises(ValueError, match="digest"):
        read_remote_identity_snapshot(tmp_path, "0" * 64)


@pytest.mark.parametrize(("change", "valid"), [
    ({"host": "other.example.org"}, True),
    ({"port": True}, False),
    ({"remote_root": "../outside"}, False),
    ({"schema_version": 2}, False),
    ({"unexpected": "value"}, False),
])
def test_remote_identity_rejects_rehashed_invalid_or_changed_snapshots(
    tmp_path: Path, change: dict, valid: bool,
) -> None:
    write_remote_identity_snapshot(tmp_path, _config())
    path = tmp_path / "agent_remote.json"
    data = json.loads(path.read_text(encoding="ascii"))
    data.update(change)
    raw = (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    if valid:
        # A self-consistent alternative identity is a valid snapshot, but
        # the pending probe must compare it to the current SSH config.
        assert read_remote_identity_snapshot(tmp_path, digest)["host"] == "other.example.org"
    else:
        with pytest.raises(ValueError):
            read_remote_identity_snapshot(tmp_path, digest)


def test_new_planned_executor_binds_remote_identity_before_dispatch(tmp_path: Path) -> None:
    seen = []

    def evaluator(candidate, run_id):
        audit = inspect_journal(tmp_path)
        assert audit.disposition == "reconcile_pending_evaluation"
        assert audit.remote_identity_verified
        assert read_remote_identity_snapshot(
            tmp_path, json.loads((tmp_path / "agent_events.jsonl").read_text().splitlines()[0])[
                "remote_identity_sha256"
            ],
        ) == remote_identity(_config())
        seen.append((candidate.candidate_id, run_id))
        return tmp_path / "missing_mock_archive"

    outcome = execute_manager_planned(
        Manager(), _spec(), evaluator, tmp_path, remote_config=_config(),
    )
    assert outcome.status == "budget_exhausted"
    assert len(seen) == 1
    audit = inspect_journal(tmp_path)
    assert audit.disposition == "complete" and audit.remote_identity_verified


def test_unbound_historical_planned_journal_still_audits(tmp_path: Path) -> None:
    execute_manager_planned(
        Manager(), _spec(), lambda candidate, run_id: tmp_path / "missing", tmp_path,
    )
    audit = inspect_journal(tmp_path)
    assert audit.disposition == "complete" and not audit.remote_identity_verified
    assert not (tmp_path / "agent_remote.json").exists()
