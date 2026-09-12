# Open-RFAmpDesigner-Cadence

基于 RFAmpDesigner 论文的 Cadence 版方法级复现工程。目标不是严格复现作者的 TSMC N65 数值结果，而是在可授权 Cadence/PDK 环境中复现其核心流程：

- 论文 Table I 的工具中间件接口；
- Table II/III 的变量范围和 LNA benchmark 规格；
- Stage 2/Stage 3 cost function；
- Python 调用 OCEAN/Spectre 的自动仿真闭环；
- Manager/Searcher/Refiner 多智能体调度框架；
- Table IV/V/VI-like 与 Fig. 7/8/9/10/11-like 的趋势级输出格式。

## 当前边界

本仓库不包含任何 TSMC、Cadence 或商业 PDK 文件。`config/model_paths.yaml` 只提供本地路径占位符，真实路径必须由实验室授权环境配置，并且不应提交到公开仓库。

论文原文、中文翻译、论文插图和 arXiv 源文件统一保存在 `references/paper/`。从旧 Codex 对话任务迁移来的聊天记录和清单保存在 `docs/project_history/`，仅作为项目来源与决策追溯资料。

## 第一版 MVP

1. 使用 `config/specs_table_iii.yaml` 读取 10 个 LNA 规格。
2. 使用 `src/orfadc/tools/cost_functions.py` 复现论文公式 (1)(2)。
3. 使用 `src/orfadc/tools/*` 形成 Active sizing、Impedance matching、Band planning、Fullchain evaluation 的可调用接口。
4. 使用 `src/orfadc/cadence/*` 封装 OCEAN/Spectre 调用和 CSV/PSFASCII 结果解析。
5. 使用 `src/orfadc/agents/*` 提供 Manager/Searcher/Refiner 的确定性骨架，后续可接入 LLM。

## 快速检查

在没有 Cadence 的机器上也可以运行纯 Python 检查：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m compileall src
python src\orfadc\experiments\run_spec.py --spec S1 --dry-run
python -m pytest tests -q
```

## 推荐阅读顺序

1. `docs/00_index.md`
2. `docs/open_rfampdesigner_cadence_full_plan.md`
3. `docs/open_rfampdesigner_cadence_design.md`
4. `config/specs_table_iii.yaml`
5. `src/orfadc/tools/cost_functions.py`
6. `src/orfadc/experiments/run_spec.py`
7. `references/paper/README.md`
8. `docs/project_history/README.md`
