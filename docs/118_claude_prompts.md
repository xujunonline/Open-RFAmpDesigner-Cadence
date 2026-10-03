# 118 Claude 详细提示词（自主逐步推进版）

本文件取代 `docs/10_detailed_prompts.md`（历史）作为**路线 A 起点**；路线 B（实机）继续参考
`docs/15_autonomous_completion_prompts.md` 的阶段 03–14，但须先完成本文件 P0–P6。
所有提示词可直接粘贴到 Claude Code（仓库根目录，已加载 `CLAUDE.md`、`.claude/`、`.mcp.json`）。

通用约束（每条提示词都隐含）：
- 先读 `CLAUDE.md`；只用仓库内命令；每步给出命令、原始输出路径、通过判据；失败则定位根因再修，不跳步。
- 不伪造数字；代理结果标注"surrogate / trend-level"；不读私密配置；不做未授权的远程动作。
- 修改代码必须附带回归测试；每阶段结束运行 `python -m pytest tests/test_repro_core.py -q`。
- 用中文汇报；汇报末尾给出"已完成 / 证据路径 / 未完成 / 下一步"四段。

---

## P0 总控提示词（一次粘贴，自动逐阶段推进）

```text
你是本仓库的自主实施负责人。目标：在不依赖 Cadence 的前提下，完整复现 RFAmpDesigner 论文的方法级结果，
并为切换到 Cadence 后端做好接口与验证准备。严格按 docs/117 的阶段 0→6 推进，每个阶段：
1) 用 TodoWrite/任务列表列出子步骤；2) 执行命令并保存原始输出到 results/；3) 对照"通过判据"自检；
4) 失败时读相关源码定位根因，最小修改 + 新增测试，重跑直到通过或确认是模型/物理限制（写明理由）；
5) 在 docs/1xx_<主题>.md 记录，更新 docs/00_index.md。
阶段顺序：P1 环境与回归 → P2 论文审计复核 → P3 代理模型物理合理性 → P4 工具链逐级验证 →
P5 智能体闭环 → P6 全量表图与核验 →（可选）P7 LLM 主干 → P8 Cadence 桥接设计。
遇到需要我决策的事项（花钱的 API 调用、远程 SSH、删除文件）先停下来问我。
全部完成后输出最终报告：论文每个表/图 → 本仓库对应产物 → 复现程度（完全/趋势/未复现）→ 差异原因。
```

## P1 环境与回归

```text
按 docs/117 阶段 0–1 执行：安装 config/requirements_repro.txt，设置 PYTHONPATH=src，
运行 compileall、tests/test_repro_core.py 与全量 tests。把 pytest 的汇总行写入 results/logs/<日期>_pytest.txt。
若有失败：区分 (a) 环境缺包 (b) 代码缺陷 (c) 缺私有 Cadence 原始档（应为 skip 而非 fail）。
只修 (a)(b)，(c) 若表现为 fail 则改成显式 skip 并说明。
```

## P2 论文审计复核（使用 skill: rfamp-paper-audit）

```text
逐条核对论文与代码：Table I 四个工具的输入/输出字段、Table II 变量范围、Table III 十个规格、
Eq.(1)(2)(3)、Sec. II-B-4 回溯策略、Sec. II-C 两种模式与 KB/EB 模板、Sec. III 评估指标（pass@1、平均时间、token）。
对 Eq.(3) 用节点分析数值复核（tests/test_repro_core.py 已有，需再用 2 组新参数加测）。
输出 claim matrix（claim → 页码 → 代码位置 → 测试 → 状态），并把新发现追加到 docs/116 的 B 系列台账。
```

## P3 代理模型物理合理性

```text
审查 src/orfadc/repro/device.py 与 circuit.py 的物理合理性，写 tests/test_repro_physics.py：
- 器件：Id 随 Vgs 单调、gm/Id ≤ 1/(n·Ut)、fT 在 65 nm 合理区间（W=100 µm, Vb=0.5 V 时 80–200 GHz）；
- 两端口：无源网络 F = 1/G_av；Friis 级联；互易无源网络 S11/S22 ≤ 0 dB；
- 电路：S2 设计在 30 GHz 的 NFmin 位于 1.5–4 dB；增益随 MCR k 的变化呈双峰展宽；
- 压缩：IP1dB 随第三级电流增加而单调改善（固定其余参数）。
任何不合理处给出修正与前后对比；所有修改记录到 docs/115 的"模型参数"一节。
```

## P4 工具链逐级验证（Stage 1→4）

```text
对 S1、S2、S5 各执行一次手动四级流程（docs/117 阶段 3 的代码片段），记录：
Stage 1 各级可行器件数与 4 个极值配置；Stage 2 的 Eq.(1) 代价、NF/S11/关键增益、L-match 是否成立；
Stage 3 每一轮校准的 LF/HF 代价与最大残差（多保真收敛曲线）；Stage 4 全链指标与每级压缩机理。
检查：Stage 2 的 `Gain_require` 是否被满足（±1 dB）；Stage 3 的 gain_req_list 是否被 HF 分级增益跟随（±3 dB）。
不满足则分析是约束不可行还是优化器预算不足，给出参数（PSO 粒子/迭代、SA 迭代）的敏感性表。
```

## P5 智能体闭环（Manager / Searcher / Refiner）

```text
运行 `python -m orfadc.repro.bench design --spec S<k> --seed 0` 对 S1–S8 各一次并读 trace：
1) 检查每个 Refiner 决策是否符合 src/orfadc/repro/prompts/refiner.md 的回溯规则；
2) 统计每个 spec 的 search/refine 次数、失败瓶颈分布；
3) 对明显不合理的决策（重复无效动作、错误瓶颈归因、预算浪费）修改 RulePolicy，并用 scripted LLM
   策略验证 LLM 路径与规则路径一致（tests/test_repro_core.py::test_scripted_llm_policy_matches_rule_policy）。
禁止为单个 spec 硬编码参数；任何启发式都必须能用论文 Sec. II-B-4/II-C 的原则解释。
```

## P6 全量表图与核验（使用 skill: rfamp-reproduce + 子智能体 repro-verifier）

```text
后台运行 `python -m orfadc.repro.bench all --seeds 5 --out results/repro/<日期>`，定期轮询日志。
完成后调用 repro-verifier 子智能体核验 SUMMARY.md 与 tables/*.csv。然后写 docs/1xx_repro_<日期>.md：
- 论文 Table IV vs 本复现 Table IV-like（并排），论文 Fig.5b 88% vs 本复现，论文 Fig.10 5.5× vs 本复现；
- "复现程度"列：完全一致 / 趋势一致 / 不一致（附原因：代理器件、成本模型、规则策略替代 LLM 等）。
```

## P7 LLM 主干实验（订阅额度优先；API 方式需要我确认费用）

```text
先读 docs/119。确认 `bench llm-check --policy claude-cli` 与 `--policy codex-mcp` 均 ok=true；然后对 S9、S10（及 S9s、S10s）
各跑 seed 0..4：`ORFADC_LLM_MAX_CALLS=1000 python -m orfadc.repro.bench design --spec <S> --seed <k> --policy <p>`
（论文口径：不封顶，只受 5 h 等效预算约束，见 docs/127；若需保护额度可改为 40，但结果须标注"受限条件"），
每次运行后读 llm_usage（calls/errors/fallbacks/disabled_reason）；若 disabled_reason 含额度用尽，停止并告诉我剩余计划。
用 `bench llm-seeds --out <作业目录> --inputs <其他目录>` 汇总 pass@1、最佳评估违规、调用次数与 token，写 tables/table5_llm.md；结果注明 agent 实现版本（v1/v2）；订阅不能给出美元成本，Table VI 只列 token 与时延。
```

### P7-API（需要我确认 API 费用后再执行）

```text
对 S9、S10 各 5 个 seed，分别用 --policy anthropic（claude-sonnet-4-5）与 --policy openai（我指定的
base_url/model）运行 bench design，收集 pass@1、平均等效时间、prompt/completion tokens、回退次数，
按论文 Table V/VI 的列生成 tables/table5_llm.md 与 table6_cost.md（USD 按我提供的单价计算）。
对比规则策略，分析 LLM 决策与规则的差异样例（从 llm_log 中摘 3 条）。
```

## P8 Cadence 桥接（v1 已在真实 Spectre 上通过，2026-10-01；v2 见 docs/120，远程动作需我授权）

```text
在 Windows 宿主上运行 `scripts\windows_llm_cadence_check.ps1`（或只跑 `bench cadence-check --spec S2`），读 results\windows_checks\<ts>\30_cadence_check.log
与 cadence_check_S2.json：若 agree=false，逐项比较 Spectre 与引擎（gain/S11/NF/NFmin/IP1dB），先查网表（repro/backend_cadence.py::render_netlist）
的元件映射与噪声相关符号，再查解析与归一化；修复后加回归测试并重跑。通过后运行 `bench design --spec S2 --backend cadence`。
```

### P8-v3（论文口径 PDK pass@1，远程动作需我授权）

```text
先读 docs/127。按 S1–S8 × seed 0..4、rule 策略、1 h 等效预算，在 scripts/jobs/queue.txt 中写好
`set ORFADC_SPECTRE_MAX_PER_DESIGN=60` 与各 `design --spec <S> --seed <k> --policy rule --backend pdk` 行，
列出预计 Spectre 次数并等我确认后再启动；完成后统计 pass@1、到可行解的等效时间与 Spectre 次数，
与论文 Table IV 的 Ours 列并排（标注"示意 PDK + 理想无源，非 N65 后仿"），更新 docs/127 §5 与 docs/125。
```

### P8-v2（PDK 器件，远程动作需我授权）

```text
设计并实现 src/orfadc/repro/backend_cadence.py 的 CadenceBackend，满足 tools.Backend 协议，
复用 cadence/remote_runner.py、psfascii_reader.py、hb_metrics.py、noise_metrics.py。
按 docs/120 的 V2-0…V2-7 推进：先做离线部分（V2-1 器件卡钩子、V2-3 引擎接 PDK 表，配单测；
网表改动后用 tests/fakes/mna_spectre.py 无法覆盖 BSIM 器件，故 PDK 网表只做结构测试）。
远程步骤（V2-0 盘点、V2-2 表征、V2-4/5/6 验证与设计）每步列出预计 Spectre 次数与风险，在我确认前不得执行任何 ssh/scp。
```

---

## A. 智能体系统提示词（运行时使用，文件即源）

| 角色 | 文件 | 要点 |
|---|---|---|
| RFAmpManager | `src/orfadc/repro/prompts/manager.md` | 资源重分配规则（NF→stage1，IP1dB stage3→stage3 …）；输出 `{"power_ratio_list": [...]}` 或 `{"stop": true}` |
| RFAmpSearcher | `src/orfadc/repro/prompts/searcher.md` | 4 个极值配置 × {无约束, 有增益约束} 的 Stage 2 综合；返回 ΔS |
| RFAmpRefiner | `src/orfadc/repro/prompts/refiner.md` | 论文分级回溯策略；输出 `rerun_stage2 / rerun_stage3 / fail` 三种动作之一 |

输出格式为 `<rationale>…</rationale><tools>{JSON}</tools>`（论文 Fig. 6 用 `<think>`；要求模型输出 think 推理会触发 Claude 的 reasoning_extraction 安全拦截，故改为一句话 rationale）；`llm.py` 校验 JSON 模式，
非法时回退规则策略并计数（`llm_usage.fallbacks`）。

KB 模板（Fig. 6）：`power | gain | power_ratio_list | gain distribution | NF1 | NF | IP1_1 | IP1_2 | IP1_3 | IP1 | params_dict`
EB 模板：`x dB NF1 and y dB gain1 leads to z dB NF. The headroom should be a%. ... leads to IP1 of m dBm.`

## B. 交互式设计提示词（Claude 亲自当 RFAmpManager，MCP 工具）

```text
/design-lna "I want to design a 3-stage RF Amp working from 27GHz to 33GHz whose load is 1787.0ohm and 62.0fF.
I want to use 30.0mA to achieve 25.0dB gain, 3.5dB Noise Figure and -15.0dBm IP1dB."
要求：先 query_memory；搜索交给 rfamp-searcher，细化交给 rfamp-refiner；每次工具调用前写一行理由；
结束时给出 spec 对比表、参数字典、轨迹和"surrogate"标注；失败时说明瓶颈与建议的 Stage 1 重分配。
```

（这正是论文 Fig. 6 的用户查询，对应 Table III 的 S10。）

## C. 续接 / 故障恢复 / 审查

```text
【续接】读取 CLAUDE.md、docs/00_index.md 最新 3 条、docs/116 台账、git status 与最近一次 results/repro/*/SUMMARY.md，
总结当前处于 docs/117 的哪个阶段，列出下一步 3 个动作，然后继续执行。
```

```text
【故障恢复】上一步失败。请：1) 重现失败命令并保存完整输出；2) 判断属于环境/代码/模型/预算哪一类；
3) 给出最小修复并加测试；4) 重跑该阶段全部检查；5) 在 docs 记录"现象—根因—修复—验证"。
```

```text
【阶段验收审查】作为独立审查者（可用 repro-verifier 子智能体），不修改代码，只核对：
命令是否可重放、原始档是否存在、表格数字能否由原始档重算、结论措辞是否超出证据（尤其 surrogate vs PDK）。
输出 PASS/FAIL 与问题清单。
```
