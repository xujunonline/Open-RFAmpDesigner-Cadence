# Stage 03: Virtuoso 属性表单焦点的只读诊断

## 目的与边界

`docs/65_stage03_cdf_form_partial_propagation.md` 和 `docs/68_stage03_cdf_callback_response_probe.md` 已分别证明受控属性赋值、显式 callback 调用后的 OA/网表响应，但都**没有证明真实 GUI 键盘编辑**。本阶段只读取已有用户 schematic 的属性表单和焦点状态，不修改字段、不调用 CDF callback、不保存 OA。商业 PDK 细节和原始日志只留在 Git 忽略的 `results/runs/`。

## 实施与原始档

- 入口 `src/orfadc/experiments/run_virtuoso_form_focus_probe.py` 从已归档表单变体读取用户库/cell/实例身份，检查宿主空闲物理内存、用户库所有权、Xvfb 可执行文件；启动文件和脚本分别为 `circuit/skill/run_virtuoso_gui_hold.sh`、`circuit/skill/virtuoso_form_focus_probe.il`。
- 只读 SKILL 打开保存过的 schematic，选中指定 MOS，调用 `schHiObjectProperty()`，记录表单显示状态以及 `hiSetCurrentField(... 'Wfg)` 前后 `hiGetKeyboardFocusField` 的返回。定时回调再次查询焦点，归档日志、报告、脚本和源 OA 前后字节。未发送键盘事件。
- `20260927T040538Z_929b30ae` 和 `20260927T040633Z_354912c8`：较早即时探针正常归档。表单显示，但设置 Wfg 焦点返回 `t` 后，查询结果仍为 `InfoAll`；`hiGetCurrentForm` 为 `nil`。返回 `t` 不可解释为字段获得键盘焦点。
- `20260927T040730Z_4feb7049`：在 `-replay` 中安排延时回调，回放完成时进程退出，未等到回调结束标记，明确保留失败。
- `20260927T040845Z_6a6c393b`：单独的 `-restore` 启动使延时回调运行，报告完整，但 GUI 未自行结束，外层超时。X11 只读窗口树存在属性窗口；表单两次焦点仍为 `InfoAll`。
- `20260927T041302Z_84dd0660`：在延时回调中取消表单再退出；报告结束标记完整，源 OA 前后字节相同，焦点仍为 `InfoAll`；Virtuoso 出现致命 X I/O 错误，退出码非零。运行失败，不归类为干净 GUI 会话。远端随后无 Virtuoso/Xvfb 残留。
- `20260927T042345Z_1d332734`：将只读等待延长到 60 秒。在该进程运行时，独立 X11 查询只找到一个可见属性窗口；`XSetInputFocus` 与 `XGetInputFocus` 证明**X11 窗口焦点**已切换，但定时报告中 Cadence 的 Wfg **字段焦点**依然为 `InfoAll`。X11 焦点操作没有保存为本地归档，不作为独立审计通过项。该 run 的源 OA 前后相同，退出仍有致命 X I/O 错误；审计固定判为 `focus_not_proven`。

最后一份归档由 `src/orfadc/experiments/audit_virtuoso_form_focus_probe.py` 独立读取。它绑定受控脚本/启动文件哈希、源 OA 前后及既有表单变体、报告和错误日志；结论为 `focus_not_proven`、`form_field_edited=false`、`cdf_callback_validated=false`、`not_lna_result=true`、`spec_pass=null`。篡改状态、报告、脚本或源 OA 均被拒绝。Runner 现在也在异常状态中记录报告完整性、焦点布尔值、源 OA 一致性及致命 X I/O 标志，防止异常退出时丢掉关键诊断信息。

## 下一门槛

先在**只读**受控窗口中分辨 X11 顶层窗口焦点与 Cadence 表单字段焦点，并找到可重复、干净退出的交互方式。若焦点仍是 `InfoAll`，停止 GUI 输入，交由有授权桌面会话和工艺知识的人员检查表单布局/PDK 初始化。即使未来真实键盘编辑成功，也仍要独立 OA 读回、网表及同候选 layout/DRC/模型警告核验；不能把焦点探针当作已认证 RF MOS sizing、合格 LNA 或论文结果。
