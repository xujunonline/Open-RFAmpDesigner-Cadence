"""MCP server exposing the RFAmpDesigner tool middleware (paper Table I).

With this server connected, Claude Code itself can play RFAmpManager: it
calls the same four tools the paper gives its agents, keeps sessions, and
reads/writes the KB/EB memory.  Start (stdio):

    PYTHONPATH=src python -m orfadc.repro.mcp_server

Registered in the repository's ``.mcp.json`` as server ``rfamp``.
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any

SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    from mcp.server.fastmcp import FastMCP  # noqa: E402  (mcp 1.x API)
except ModuleNotFoundError as exc:  # mcp 2.x renamed FastMCP
    raise SystemExit("orfadc MCP servers need the mcp 1.x SDK: python -m pip install \"mcp>=1.2,<2\" "
                     f"(see config/requirements_repro.txt); import error: {exc}") from exc

from orfadc.config_loader import load_specs  # noqa: E402
from orfadc.repro import agents as A  # noqa: E402
from orfadc.repro.memory import MemoryStore  # noqa: E402
from orfadc.schemas import Spec  # noqa: E402

ROOT = SRC.parent
MEMORY = MemoryStore(ROOT / "results" / "memory" / "repro")
SESSIONS: dict[str, A.DesignSession] = {}
mcp = FastMCP("rfamp")


def _specs() -> dict[str, Spec]:
    from orfadc.repro.bench import scaled_hard_specs
    return {**{s.id: s for s in load_specs(ROOT / "config" / "specs_table_iii.yaml")}, **scaled_hard_specs()}


def _sess(session_id: str) -> A.DesignSession:
    if session_id not in SESSIONS:
        raise ValueError(f"unknown session {session_id}; call new_session first")
    return SESSIONS[session_id]


def _j(x: Any) -> str:
    return json.dumps(A._public(x), default=float, ensure_ascii=False)


@mcp.tool()
def list_specs() -> str:
    """List the Table III benchmark specs (S1..S10)."""
    return _j({k: v.__dict__ for k, v in _specs().items()})


@mcp.tool()
def new_session(spec_id: str = "S2", seed: int = 0, budget_equiv_s: float = 3600.0,
                custom_spec: dict | None = None) -> str:
    """Open a design session for a Table III spec or a custom spec dict
    {id, fc_ghz, fbw_ratio, power_ma, gain_db, nf_max_db, ip1db_min_dbm}."""
    spec = Spec(**custom_spec) if custom_spec else _specs()[spec_id]
    sid = uuid.uuid4().hex[:8]
    SESSIONS[sid] = A.DesignSession(spec, seed=seed, budget_equiv_s=budget_equiv_s, memory=MEMORY)
    return _j({"session_id": sid, "spec": spec.__dict__, "band_ghz": spec.band_edges_ghz,
               "load": "1787 ohm || 62 fF", "backend": SESSIONS[sid].ctx.backend.name})


@mcp.tool()
def active_sizing(session_id: str, power_ratio_list: list[float]) -> str:
    """Stage 1: split the current budget [r1,r2,r3] -> four extreme active configurations."""
    return _j(_sess(session_id).tool_active_sizing(power_ratio_list))


@mcp.tool()
def impedance_matching(session_id: str, power_ratio_list: list[float], config_id: str,
                       nf_headroom_db: float = 0.2, gain_require_db: float | None = None) -> str:
    """Stage 2: PSO + L-match for the critical stages (Eq. 1). Returns a candidate id (cid)."""
    return _j(_sess(session_id).tool_impedance_matching(power_ratio_list, config_id, nf_headroom_db, gain_require_db))


@mcp.tool()
def band_planning(session_id: str, cid: str, gain_user_db: float | None = None,
                  gain_req_list: list[float] | None = None) -> str:
    """Stage 3: MCR2/MCR3 band planning with Eq. 3 + multi-fidelity calibration (Eq. 2). Returns a design id."""
    return _j(_sess(session_id).tool_band_planning(cid, gain_user_db, gain_req_list))


@mcp.tool()
def fullchain_evaluation(session_id: str, did: str) -> str:
    """Stage 4: full-chain S-parameters, NF, IP1dB, power; returns pass flag, violations and per-stage compression."""
    return _j(_sess(session_id).tool_fullchain_evaluation(did))


@mcp.tool()
def session_status(session_id: str) -> str:
    """Budget use, candidate briefs and evaluated designs of a session."""
    s = _sess(session_id)
    designs = {d: {"cid": v["cid"], "pass": v.get("fullchain", {}).get("pass")} for d, v in s.designs.items()}
    return _j({"spec": s.spec.__dict__, "sims": s.ctx.counter.to_dict(), "budget_left": s.budget_left(),
               "candidates": [c.brief() for c in s.candidates.values()], "designs": designs})


@mcp.tool()
def export_design(session_id: str, did: str) -> str:
    """Full parameter dictionary (active + passive) and the frequency sweep of an evaluated design."""
    rec = _sess(session_id).designs[did]
    out = {"design": rec["design"].summary()}
    if "fullchain" in rec:
        out["sweep"] = rec["fullchain"]["_sweep"]
        out["metrics"] = rec["fullchain"]["sim_results_dict"]
    return _j(out)


@mcp.tool()
def query_memory(spec_id: str = "S2", k: int = 3, custom_spec: dict | None = None) -> str:
    """Retrieve top-k Knowledge-Base design points and Experience-Base insights for a spec (Mode 2 RAG)."""
    spec = Spec(**custom_spec) if custom_spec else _specs()[spec_id]
    return _j({"kb": MEMORY.retrieve(spec, k=k), "eb": MEMORY.insights(spec)})


@mcp.tool()
def run_autonomous(spec_id: str = "S2", seed: int = 0, mode: int = 1, policy: str = "rule",
                   budget_equiv_s: float | None = None) -> str:
    """Run the full Manager/Searcher/Refiner loop (rule or LLM policy) and store results in KB/EB."""
    from orfadc.repro.llm import make_policy
    spec = _specs()[spec_id]
    from orfadc.repro.bench import budget_for
    b = budget_equiv_s or budget_for(spec_id)
    r = A.run_design(spec, seed, mode=mode, memory_dir=MEMORY.root, budget_equiv_s=b, policy=make_policy(policy))
    r.pop("trace", None)
    r.pop("_session", None)
    r.pop("sweep", None)
    return _j(r)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
