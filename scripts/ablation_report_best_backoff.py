"""Ablation for docs/124 §1.2–1.3: report-best (B20) with and without the Stage-2 back-off (B21).

    python scripts/ablation_report_best_backoff.py S1,S3,S9s 5 out.jsonl [workers]
"""
import json
import os
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def run(args):
    sid,seed,backoff,best=args
    os.environ['ORFADC_STAGE2_BACKOFF']='1' if backoff else '0'
    os.environ['ORFADC_REPORT_BEST']='1' if best else '0'
    from orfadc.repro import agents as A
    from orfadc.repro.bench import specs, scaled_hard_specs, budget_for
    sp={**specs(),**scaled_hard_specs()}[sid]
    r=A.run_design(sp, seed, budget_equiv_s=budget_for(sid))
    ev=[e for e in r['trace'] if e.get('event')=='evaluate']
    bv=min((A._norm_viol(e['violations']) for e in ev), default=float('nan'))
    rv=A._norm_viol(r['report']['violations']) if r.get('report') and r['report'].get('violations') else float('nan')
    t=r['sims']['equiv_time_s']
    return dict(spec=sid,seed=seed,backoff=backoff,best=best,success=r['success'],viol=0.0 if r['success'] else rv,best_eval=bv,t=t)


if __name__=='__main__':
    specs_=sys.argv[1].split(','); seeds=int(sys.argv[2]); out=sys.argv[3]
    jobs=[(s,k,b,True) for s in specs_ for k in range(seeds) for b in (False,True)]
    with Pool(int(sys.argv[4]) if len(sys.argv)>4 else 4) as p, open(out,'w') as fh:
        for r in p.imap_unordered(run,jobs):
            fh.write(json.dumps(r)+'\n'); fh.flush(); print(r,flush=True)
