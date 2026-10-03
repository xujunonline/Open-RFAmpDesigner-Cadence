from __future__ import annotations

import argparse
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from orfadc.agents.manager import Manager
from orfadc.config_loader import load_specs, write_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", default="S1")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.dry_run:
        parser.error("this entry point only supports --dry-run; no Cadence simulation is run")

    project_root = Path(__file__).resolve().parents[3]
    specs_path = project_root / "config" / "specs_table_iii.yaml"
    specs = {spec.id: spec for spec in load_specs(specs_path)}
    if args.spec not in specs:
        raise SystemExit(f"Unknown spec {args.spec}. Available: {', '.join(sorted(specs))}")

    manager = Manager()
    candidates = manager.search_candidates(specs[args.spec], seed=args.seed)
    out = project_root / "results" / "runs" / args.spec / f"seed{args.seed}" / "dry_run_candidates.json"
    write_json(out, [candidate.to_dict() for candidate in candidates])
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
