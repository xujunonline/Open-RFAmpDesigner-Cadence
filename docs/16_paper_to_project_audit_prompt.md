# 从英文论文到整个工程的彻底审查提示词

本文件是执行提示词，不是已完成的审查报告。它规定先核对英文论文，再逐文件审查、修复和验证当前仓库，最后才继续 `docs/15_autonomous_completion_prompts.md` 的后续实施阶段。适用于能访问本地仓库、运行 Python 测试并在授权条件下连接 Cadence 的 Codex 桌面任务。

## 1. 一次复制的总提示词

```text
你现在负责对 F:\Open-RFAmpDesigner-Cadence 进行一次从论文原文到运行证据的彻底审查，并修复发现的可修复问题。先完成审查与修复，再继续 docs/15_autonomous_completion_prompts.md 的项目实施。不要只输出审查计划，也不要把“文件存在”“脚本有名字”或“单元测试通过”当作真实 Cadence LNA 已完成。

审查对象：
- 英文论文 references/paper/RFAmpDesigner.pdf 是论文事实的首要依据；references/paper/source/2605.10093-source.tar 和抽取文本用于核对公式、表格与图注，但不要执行压缩包中的代码；中文翻译是辅助资料，不应覆盖英文原文。
- README.md、docs/ 下所有正文/索引/旧提示词/教学文档/agent_system 文档及必要的 project_history 决策记录。
- config/、src/、circuit/、tests/、third_party_notes/、.gitignore 和实际存在的 results/ 产物；检查 Git 已跟踪与未跟踪文件。私有配置和被忽略的结果只可本地核对，不得把内容复制进公开文档。
- 当前工作树可能包含用户和先前任务的未提交修改。先执行 git status 和有针对性的 diff，理解来源与依赖；不要回滚、覆盖或删除已有修改/结果。

审查目标：
1. 建立英文论文事实台账。逐项核对研究目标、三阶段 LNA 拓扑、Table I 四工具的输入输出、Table II 变量及范围、Table III 十项规格、公式 (1)-(3) 和 MCR 的数学关系、Table IV/V/VI 的统计定义、Fig. 7-11 的横纵轴/比较对象、LLM backbone、Manager/Searcher/Refiner、KB/EB、实验 seeds/timeout/baseline。每一项给出论文页码或明确表/图/公式号、英文原义、单位、适用条件、项目对应文件和差异。对公式中的绝对值、正部、阈值、求和/平均、dB/线性量特别仔细核对，禁止凭旧中文解释猜测。
2. 建立全文件清单。对每个有意义的源码、测试、配置、网表/OCEAN 脚本和文档标注：用途、宣称能力、实际实现状态（实机验证/单元测试/仅骨架或模板/失效/不适用）、依赖、测试证据、需修复问题。逐一阅读；大文件可分段读取，不可仅凭文件名或搜索结果下结论。对二进制论文/插图以可读原件、必要时 PDF 页面截图核对，不以 OCR 错字替代原件。
3. 建立论文 -> 规格配置 -> Python 数据结构 -> 工具 -> Cadence 网表/脚本 -> 原始 PSF/Touchstone -> CSV -> metrics.json -> agent observation -> 实验表图 -> 文档结论的双向追踪矩阵。找出断链、重复定义、单位不一致、缺省值错误、虚假的完成声明和结果来源混淆。
4. 对所有问题做有证据的优先级排序并实际修复。高优先级包括：会错误宣称 pass 的缺测/NaN 默认值、论文公式或 Table III 数值偏差、Touchstone 端口顺序/参考阻抗错误、NF 与 NFmin 混淆、IP1dB 与 OP1dB 混淆、S21 与 transducer/power gain 混淆、dBm 与 mA/W 混淆、频带边界和 ripple 定义错误、dry-run/mock 与真实仿真混淆、重复候选覆盖结果、agent 无预算死循环、私密信息进入 Git/LLM 请求。只有确认存在的才列为问题，不要凭空增加缺陷。
5. 按问题修复后重新验证：纯 Python 运行 compileall、pytest、S1 dry-run 和针对性测试；对已有理想二端口实验，在环境可用时以受控预算复验 Spectre/OCEAN，并从原始输出重算关键指标；涉及有源 PDK 的问题先检查授权和可用性。修复前后保留证据。测试应检查行为与边界，而不是把当前错误实现复述一遍。所有未运行的仿真明确标为未验证。
6. 审查结束时输出详尽报告和下一步执行入口。尚需授权 PDK、真实 LLM 凭据、版图/PEX 或作者未公开数据的项目应明确列为外部受限；这不是仓库代码已通过的证明。审查门槛通过后，按照 docs/15_autonomous_completion_prompts.md 从最早未通过的实施阶段继续。

审查顺序与执行细则：

A. 建立只读基线
- 记录时间、分支、git status、相关 diff、Python/Cadence 版本和现有结果目录。
- 先运行现有测试并保留基线输出。检查 .gitignore 是否覆盖私有 YAML、PDK 产物、日志和模型文件，但不删除用户文件。
- 从 rg --files 建立文件清单；检查未跟踪文件，不遗漏新增的 netlist、runner 和文档。

B. 英文论文精读
- 按论文出现顺序整理事实，不根据项目计划反推论文。
- Table II/III 每行每列逐格核对，明确 GHz、fF、pH、ohm、mA、dBm、dB、百分比/小数的单位约定；作者没有给的数据写“未公开”。
- 逐式抄录公式的数学结构到审查表，解释变量从哪个分析中获得，并给出边界/缺测处理。若 PDF 与抽取文本冲突，查看 PDF 页面并记录裁决依据。
- 审核 Table IV/V/VI 和 Fig. 7-11 的定义：样本数、seed、时间、token、成本和成功率；不得把项目生成的 like 表图称为论文原始曲线。
- 审核 agent 角色、工具调用顺序、搜索与细化、KB/EB 的原文依据，区分论文明确内容与本项目自行设计的 JSON schema/代码结构。模型名单、服务商和版本只写论文有依据的内容。

C. 全仓库静态审查
- 对 docs/ 每个可读文档检查事实依据、命名、链接、目录树、状态日期、互相矛盾的当前进度、初学者说明与可执行命令；纠正过时事实，但保留历史记录为历史，不重写历史。
- 对 config/ 检查 YAML 可解析性、类型、单位、范围、spec ID 唯一性和论文一致性；路径模板与私有配置隔离。
- 对 src/orfadc/cadence/ 检查 SSH/SCP 参数安全、超时、路径、日志、并发目录隔离、Spectre/OCEAN 退出码、PSFASCII/Touchstone 解析、参考阻抗、缺测、边界频点和复数到 dB 换算。
- 对 src/orfadc/tools/ 检查论文公式、输入输出契约、实际仿真调用、仅低保真状态与完整结果状态、无数据时是否被错误计分。
- 对 src/orfadc/agents/ 检查候选队列、Search/Refine/Stop、预算、去重、失败回溯、LLM JSON 验证、工具白名单、memory 来源与失败经验污染。明确当前只有骨架的部分。
- 对 experiments/baselines/plots/ 检查 dry-run、随机种子、相同仿真预算、公平性、pass@1 分母、时间统计、数据来源和图表空数据行为。占位模块必须在文档中标为占位。
- 对 circuit/ 检查 Spectre 网表分析语法和实际运行记录；OCEAN 每个脚本是可运行、只通过解释器验证、还是仅注释模板，逐一标注。
- 对 tests/ 检查关键路径和失败路径是否被覆盖，特别是缺失指标、无效单位、解析错误、非法候选及远程失败；别把 mock test 当作 Cadence 实机证据。
- 对 third_party_notes/ 检查来源、许可证、复用代码与归属说明；仅在需要核对可能变化的外部仓库/许可证时访问官方源，不猜测许可证。

D. 运行与数值审查
- 实跑可在当前环境执行的本地命令。真实 Cadence 只用已有授权环境和低预算 smoke，先确认远程状态，不擅自改 VMware/PDK/许可证配置。
- 对一份真实理想二端口结果，从原始 Touchstone/PSFASCII 抽样重算 S11/S21/S22 与最差值、ripple；核查频率点数和频带边界。被动二端口不可证明 LNA NF/IP1dB。
- 对仍未实现的 noise、compression、LNA、Stage 2/3、LLM、五种子表图保留“未验证”状态，不生成貌似真实的占位数值。

E. 修复循环
- 每个问题记录 issue ID、严重度、定位文件/行、论文或运行证据、影响、修复方法、验证命令和最终状态。
- 先修复错误结论、错误公式/单位、隐私泄露和会误判通过的代码，再修复接口/解析/测试，最后处理文档和命名。保持改动最小且符合现有风格；先说明拟修改文件，再编辑。
- 每批修复后运行针对性测试和相关端到端 smoke。若某项依赖外部资源且当前无法验证，记录 blocked，并继续独立可完成项。
- 不使用 git reset --hard、git checkout --、递归删除或覆盖现有未提交更改；不因整理目录误删有用历史。

F. 审查交付物
- 在 docs/audits/ 下生成日期化的审查报告，例如 2026-09-25_paper_to_project_audit.md，实际日期以执行时为准。
- 同目录保存 paper_claims_matrix.md、file_inventory.md、traceability_matrix.md、issue_register.md；内容较少时可以合并，但必须保留同等信息。表格每项有来源和状态。
- 新增或更新 docs/16_implementation_status.md：每阶段目标、证据路径、passed/partial/blocked/not_started、下一可执行动作。它是实施进度，不替代审查报告。
- 更新 README.md、docs/00_index.md、docs/09_step_by_step_operation_guide.md、docs/15_autonomous_completion_prompts.md 中确有过时或错误的表述。不要把本提示词误当审查已经完成。
- 最终向我报告：P0/P1/P2 问题数与修复数、论文核对的重要偏差、真实测试和仿真的通过/失败证据、仍受外部条件限制的项目、接下来从哪个阶段继续。对每个未关闭问题说明原因与可执行下一步。

完成门槛：
- 英文论文的核心事实已逐项追踪到配置、代码、文档或明确未实现项；表格、公式和单位均有来源。
- 每个相关文件已纳入 inventory，未跟踪文件和当前结果也在审查范围内；主要跨层数据链有双向追踪。
- 所有可在当前环境修复的 P0/P1 问题已修复并验证；P2 问题有修复或明确记录。不应宣称发现并消除了所有未知问题。
- 本地测试通过；可用的 Cadence smoke 有日志与原始产物，未运行的分析不写成功。
- 文档当前状态相互一致，审查报告完整，下一阶段可直接执行。

现在开始 A：建立基线，然后按 B-F 实施。审查过程中定期说明已核对范围、发现的高优先级问题及修复进度；不要在只读审查或计划阶段就结束任务。
```

## 2. 长任务续接提示词

审查可能跨多个任务。新任务复制本段，审查未完成时不要提前进入新功能开发：

```text
继续 F:\Open-RFAmpDesigner-Cadence 的论文到工程彻底审查。先读 docs/16_paper_to_project_audit_prompt.md、docs/audits/ 中已有报告、docs/16_implementation_status.md（若已创建）和 git status。查清上次完成到 A-F 的哪一项、哪些文件/论文部分尚未审阅、哪些 issue 已修复或仍待验证。仅补未完成部分，保留已有未提交更改和失败产物。达到审查完成门槛后，才按 docs/15_autonomous_completion_prompts.md 从最早未通过阶段继续自动实施。
```

## 3. 审查后的行动规则

审查结束后，`docs/15_autonomous_completion_prompts.md` 是后续实施顺序；审查报告与 `docs/16_implementation_status.md` 是当前进度依据。若审查发现现有阶段编号、数据契约或实验定义错误，先修正实施提示词，再继续开发。没有授权 PDK、真实 LLM 配置或 PEX 资源时，相关阶段保持受限状态，同时完成不依赖这些资源的代码与验证。
