# LEGACY：v1.1 清理时删除的内容（2026-10-05）

v1（标签 `v1-decision-points`，提交 e80dfd3，已推送到私有仓库）完整保留了下列文件。v1.1 从当前版本中删除它们，
因为当前复现（`src/orfadc/repro` 及其 Cadence/PDK 后端）不依赖它们。判定方法与执行记录见 docs/129。

找回单个文件或目录：

```bash
git checkout v1-decision-points -- <path>      # 例如 src/orfadc/experiments 或 docs/113_stage10_incomplete_remote_quarantine.md
git show v1-decision-points:<path>             # 只查看，不恢复
```

完整清单：`docs/LEGACY_files.txt`（566 个文件）。

| 类别 | 删除内容 | 说明 |
|---|---|---|
| 路线 B 代码 | `src/orfadc/agents/`（37）、`experiments/`（133）、`baselines/`（5）、`plots/`（8）、`metric_contract.py`、`cadence/` 中 20 个模块、`tools/` 中 10 个模块 | Codex 阶段的 Virtuoso/OCEAN 实机链路、教学电路、远程恢复/隔离、早期工具与基线实现。复现用的 GA/BO 基线在 `repro/baselines.py` |
| 路线 B 测试 | `tests/` 中 148 个文件 | 只覆盖上面删除的代码 |
| 电路文件 | `circuit/`（ocean 19、skill 15、spectre 6） | 复现后端自行生成网表 |
| 文档 | docs/00–114（`00_index` 已重写）、`agent_system/`、`audits/`、`project_history/`（2 个跟踪文件）、`open_rfampdesigner_cadence_*.md`、`ota_to_lna_migration_notes.md` | 路线 B 过程记录。原 docs/113–114 的远程隔离/预算规则已并入 CLAUDE.md 规则 2 |
| 配置 | `config/agent_settings.yaml`、`sweep_settings.yaml`、`metrics_v1.schema.json`、`requirements_bo.txt`；`model_paths.yaml` 改为 `model_paths.example.yaml` | 只被路线 B 使用 |
| 脚本 | `fix_claude_rationale.*`、`claude_fix/`、`a09_stability_acceptance.ps1`、`run_codex_followup.*`、`git_snapshot_v1*` | 一次性脚本，已完成使命 |
| 冗余产物 | `results/repro/2026-09-29/`（与 2026-10-03 逐字节相同）、`.claude/**/*.bak` | — |
