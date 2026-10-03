import json

from orfadc.repro import bench


def _run(d, spec, seed, pol, ok, viol_ip1, calls=None):
    r = {"spec": spec, "seed": seed, "success": ok, "report": {"violations": {"ip1db": viol_ip1}},
         "sims": {"equiv_time_s": 100.0}}
    if calls is not None:
        r["llm_usage"] = {"calls": calls, "prompt_tokens": 10, "completion_tokens": 5, "fallbacks": 0,
                          "rule_after_disable": 1, "errors": 0}
    (d / f"design_{spec}_seed{seed}_mode1_{pol}.json").write_text(json.dumps(r), encoding="utf-8")


def test_llm_seeds_merges_folders_and_counts(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    _run(a, "S9", 0, "rule", False, 2.0)
    _run(b, "S9", 1, "rule", True, 0.0)
    _run(b, "S9", 1, "codex-mcp", False, 1.0, calls=4)
    (b / "design_S9_seed0_mode1_rule_pdk.json").write_text("{}", encoding="utf-8")   # Spectre runs are skipped
    assert bench.cmd_llm_seeds(b, [a]) == 0
    s = {(r["spec"], r["policy"]): r for r in json.loads((b / "llm_seeds.json").read_text())["summary"]}
    assert s[("S9", "rule")]["pass"] == 1 and s[("S9", "rule")]["seeds"] == [0, 1]
    assert s[("S9", "codex-mcp")]["calls_mean"] == 4 and s[("S9", "codex-mcp")]["tokens_mean"] == 15
    assert s[("S9", "rule")]["viol_median"] == 0.5 * (0 + 2.0 / bench.B.NORM["ip1db"])
