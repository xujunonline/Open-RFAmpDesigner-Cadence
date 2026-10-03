# 阶段 06：有源 lookup 数据契约

`active_sizing` 目前仍不能从 power ratio 得出真实 MOS 尺寸。无表时，它只返回各级电流预算与 `lookup_status=missing`；显式传入空表会报错，不会悄悄回退到占位结果。

传入 lookup 表时，必须同时给出 `lookup_context`。上下文包含 `model_kind`（`authorized_pdk` 或 `teaching_model`）、`technology_id`、`model_revision`、`corner` 和 `temperature_c`。每行的 `metadata` 必须完全匹配上下文，并有安全的 `source_run_id`、级号、测得电流、W/L、VGS、gm、gds、Cgs、Cgd。数值须有限，物理量不得为负；每级只选不超出分配电流的最近行。混合工艺/模型/温度表、缺字段、空表与越界电流均失败，而不是选一个“差不多”的器件。

```python
context = {
    "model_kind": "teaching_model", "technology_id": "synthetic",
    "model_revision": "v1", "corner": "tt", "temperature_c": 27,
}
row = {
    "stage": 1, "current_ma": 3.9, "w_um": 10, "l_um": 0.1,
    "vgs_v": 0.6, "gm_s": 0.005, "gds_s": 0.0001,
    "cgs_f": 1e-14, "cgd_f": 1e-15,
    "metadata": context, "source_run_id": "synthetic_stage1",
}
```

该例**仅为合成单元测试格式**，不是可用的工艺数据。返回状态为 `metadata_matched_unverified`：匹配元数据不验证 `source_run_id` 真有 Cadence 原始文件，也不保证器件在目标 RF 频段可用。不能用该状态接受候选或向 LLM 宣称真实 sizing。公开仓库不得写入商业 PDK 模型路径、实例属性或未脱敏网表；真实表、原始结果与哈希清单保存在 Git 忽略目录。

## 教学模型的实际表征进展

2026-09-26 已从公开 MOS1 **单管共源诊断 testbench**，在固定 `W=300 um`、`L=0.1 um`、`VDD=1.2 V`、27 °C 下运行 `VBIAS=0.50/0.55/0.65/0.70 V` 四点。实际 `VDS` 由工作点决定，不能当作固定 1.2 V。每点直接 Spectre 25.1 DC、`info what=oppoint`、SP/noise 的 PSFASCII、日志、Touchstone 和清单均存于 Git 忽略的独立目录；`audit_teaching_lna.py` 从原始文件重算，并将 MOS `ids` 与电源电流、`vgs/vds` 与 DC 节点交叉核验。原固定宽度表输出在 `results/runs/teaching_device_lookups/20260926T125815Z_3658de5e/`，四行 `gm/Id` 约为 40/20/10/8 V^-1，记录了模型语句摘要、温度、尺寸、偏置、Id/gm/gds/Cgs/Cgd 及逐行 `source_run_id`。新增多宽度证据与限制见 `docs/37_teaching_multi_width_lookup.md`。

这**不是**上文 `active_sizing` 可直接使用的三级 stage lookup：表中刻意没有 `stage`，且仅扫描了一个固定 L、一个温度、一个理想 MOS1 模型；新增多 W 也不提供 stage 映射。`Cgd=0` 是此人为模型设置的结果，不能迁移为真实 GHz PDK 器件。归档内部哈希不能替代工艺审签。旧 OA 私有工艺仍需 CDF/PCell 参数传播核验；论文的每级 bias/阻抗/尺寸映射和可制造匹配仍未完成，阶段 06 保持 partial。

两个既有归档的最小只读复核：

```powershell
$env:PYTHONPATH='src'
py -m orfadc.experiments.audit_teaching_device_lookup `
  results/runs/teaching_device_lookups/20260926T125815Z_3658de5e `
  --source-root results/runs/teaching_lna
py -m orfadc.experiments.audit_teaching_device_lookup `
  results/runs/teaching_device_lookups/20260926T135143Z_99195868 `
  --source-root results/runs/teaching_lna
```

下一门槛：在授权工艺且宿主资源充足的环境中，先核实 PCell 尺寸与几何寄生，再扫描多 W/L、温度、角落、偏置；从原始 `info`/RF 小信号结果构建 stage-specific lookup，并校验实际源文件、单位和插值误差。只有该拓扑/工艺上下文验证后，才可让 `active_sizing` 输出可用器件尺寸。
