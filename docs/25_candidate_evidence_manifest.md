# 阶段 05：候选运行文件证据清单（首版）

`src/orfadc/cadence/evidence.py` 为**同一个本地运行目录**建立并复核文件清单。它是阶段 05 的一小部分，不会启动 Cadence，也不会从 PSF 重新计算指标。2026-09-26 已用 mock 成功/失败目录做单元测试，并对既有 Git 忽略的被动 Spectre 实测目录 `results/runs/rf_smoke/passive_noise/20260926T014327Z_bbaff6d2/` 做**只读**交叉检查：7 个文件通过哈希与来源契约，`circuit_class=passive_twoport`、`spec_pass=null`；未改动该历史运行。`Refiner.refine_from_run` 现能读取带清单的失败候选以提供回溯建议；在真实数据重提取完成前，所有“通过”结果均不能 accepted。

`src/orfadc/cadence/candidate_runs.py` 现提供 `reserve_candidate_run(runs_root, spec, candidate)`，独占创建 `results/runs/<spec>/<seed>/<candidate>/<run_id>/`。它拒绝不安全路径段、上下文不符、已有 run_id 和可检测的符号链接。此接口仅预留目录，尚未由真实候选 backend 调用；Windows 当前测试环境无法创建目录符号链接，相应两项测试跳过。

## 文件与接口

新后端应先在独立的 `results/runs/<spec>/<seed>/<candidate>/<run_id>/` 中写入 `metrics.json`、`candidate.json`（有候选时）、`netlist.scs`、`spectre.log`、CSV 和各项原始仿真数据。`build_evidence_manifest(run_dir, artifacts)` 只读构造包含 `schema_version`、`run_id`、各逻辑文件的相对路径、字节数与 SHA-256 的字典；`write_evidence_manifest` 用独占创建写出 `evidence_manifest.json`，拒绝覆盖既有清单；`verify_evidence_manifest` 重新计算哈希并返回经过 envelope 校验的 `metrics.json`。

```python
from pathlib import Path
from orfadc.cadence.evidence import write_evidence_manifest, verify_evidence_manifest
import json

run_dir = Path("results/runs/S1/seed0/candidate01/run001")
artifacts = {
    "metrics": "metrics.json",
    "candidate": "candidate.json",
    "netlist": "netlist.scs",
    "spectre_log": "spectre.log",
    "waveforms": "waveforms.csv",
    "dc_raw": "raw/dcOp.dc",
    "sp_raw": "raw/sp.sp",
    "noise_raw": "raw/sp.noise.sp",
    "compression_raw": "raw/compression.csv",
}
manifest_path = write_evidence_manifest(run_dir, artifacts)
metrics = verify_evidence_manifest(
    run_dir, json.loads(manifest_path.read_text(encoding="utf-8"))
)
```

代码中的路径只是目录格式示例，**不是**现有合格 LNA 运行。`artifacts` 的值必须是运行目录内的可移植相对路径；拒绝绝对/上级路径、符号链接、重复文件路径、缺文件和哈希/大小变化。成功仿真须有网表、Spectre 日志和指标；`spec_pass=true` 的完整 LNA 结果另外必须有候选快照、波形及 DC/SP/noise/compression 原始文件。成功日志需包含 Spectre 0-error 完成标志，关键文件不得为空；空的可选 stderr 日志可保留。连接失败等未进入仿真的候选可仅存指标失败记录与候选快照，不虚构 Spectre 文件。

## 安全边界

SHA-256 只能证明**清单生成后文件未被替换或混放**；攻击者或错误程序仍可同时伪造文件和清单。当前没有把原始 PSF/压缩曲线与 `metrics.json` 再计算比对，也没有由可信后端签发运行收据，因此**不能**把通过本清单验证解释为“真实 LNA 规格通过”。`Refiner.refine_from_run` 遇到 `spec_pass=true` 一律返回 `needs_evaluation`；直接 `refine` 对零违规 JSON 也同样不接受。Manager 后续必须从受控 `RemoteRunner` 的进程返回、日志、原始数据及参数快照产生候选记录，再调用提取器重算指标，最后才允许 Refiner 判定。LLM 不能写入或提交可接受的 `metrics.json`/清单。

本地商业 PDK 模型、网表和日志继续只留在 Git 忽略的运行目录，不放入 prompt 或开源仓库。下一步让真实 backend 使用独占 run_id 目录，并实现失败分类、受控仿真执行与重提取；之后用一个真实成功候选和一个真实失败候选验收。当前 `fullchain_eval` 仍是不可通过的模板，阶段 05 保持 partial。
