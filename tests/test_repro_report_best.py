import os

from orfadc.repro import agents as A
from orfadc.repro.bench import specs


def _norm(v):
    return A._norm_viol(v)


def test_report_best_returns_least_violating_evaluation(monkeypatch):
    sp = specs()["S9"]                                  # infeasible on the surrogate: always a failed run
    monkeypatch.setenv("ORFADC_REPORT_BEST", "1")
    r = A.run_design(sp, 0, budget_equiv_s=1500.0)
    assert not r["success"]
    ev = [e for e in r["trace"] if e.get("event") == "evaluate" and e.get("violations")]
    assert ev
    final = _norm(r["report"]["violations"])
    # every refine loop reports its own best; the manager keeps the best report
    reps = [e for e in r["trace"] if e.get("event") == "refine_report" and e.get("violations")]
    assert final == min(_norm(e["violations"]) for e in reps)
    assert final <= _norm(ev[-1]["violations"]) + 1e-12


def test_report_best_is_off_by_default(monkeypatch):
    monkeypatch.delenv("ORFADC_REPORT_BEST", raising=False)
    sess = A.DesignSession(specs()["S2"], seed=0, budget_equiv_s=10.0)
    assert A.RFAmpManager(sess).report_best is False
    assert os.environ.get("ORFADC_REPORT_BEST") is None
