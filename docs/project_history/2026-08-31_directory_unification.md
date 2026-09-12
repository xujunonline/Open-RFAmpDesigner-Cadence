# 目录统一记录（2026-08-31）

## 目的

原工作区同时包含迁移资料根目录 `RFAmpDesignerCodexProject/` 和代码子目录 `Open-RFAmpDesigner-Cadence/`。本次整理将代码、文档和论文资料统一到一个工程根目录，并将最终目录命名为 `Open-RFAmpDesigner-Cadence`。

## 内容映射

| 原位置 | 统一后位置 | 说明 |
| --- | --- | --- |
| `Open-RFAmpDesigner-Cadence/src/` | `src/` | Python 包 |
| `Open-RFAmpDesigner-Cadence/config/` | `config/` | 规格和工程配置 |
| `Open-RFAmpDesigner-Cadence/circuit/` | `circuit/` | OCEAN/Cadence 资源 |
| `Open-RFAmpDesigner-Cadence/docs/` | `docs/` | 当前工程文档 |
| `deliverables/RFAmpDesigner.pdf` | `references/paper/RFAmpDesigner.pdf` | 论文原文 |
| `deliverables/RFAmpDesigner_中文翻译.md` | `references/paper/RFAmpDesigner_中文翻译.md` | 中文翻译 |
| `deliverables/RFAmpDesigner_figures/` | `references/paper/figures/` | 论文插图 |
| `source/` | `references/paper/source/` | arXiv 源码和文本抽取稿 |
| 原外层 `docs/` 和 `README.md` | `docs/project_history/` | 迁移历史与需求追溯 |

## 校验结果

- 内层代码工程迁移前共有 77 个文件。
- 外层历史资料迁移前共有 23 个文件（不含测试缓存）。
- 原 `MANIFEST.tsv` 的 21 条记录中，20 条按字节数完全匹配新位置。
- 清单中的旧 `README.md` 长度为 1,904 字节，但迁移前实际文件已经扩展为 25,826 字节；归档后的 `legacy_workspace_README.md` 仍为 25,826 字节。该差异来自旧清单未随 README 更新，不是迁移造成的数据丢失。
- 论文 PDF 不在旧清单中；本次单独确认并迁移，文件大小为 1,309,546 字节。
- `python -m compileall -q src` 通过。
- `run_spec.py --spec S1 --dry-run` 通过。
- `python -m pytest tests -q` 结果为 2 passed；26 条警告来自当前 pytest 在 Python 3.13 下使用待弃用 AST API。

## 路径规则

当前文档、脚本和提示词应优先使用仓库相对路径。只有需要明确进入项目目录时才使用 `F:\Open-RFAmpDesigner-Cadence`。历史归档中的旧绝对路径保持原样，用于还原当时的上下文。
