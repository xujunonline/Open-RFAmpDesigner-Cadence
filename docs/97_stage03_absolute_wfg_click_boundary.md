# Stage 03: 绝对坐标 Wfg 点击与 Virtuoso 内部焦点边界

## 为什么重做焦点探针

`docs/94_stage03_mutter_x11_focus_boundary.md` 中首次鼠标档的辅助程序从 `xwininfo -root -tree` 解析到了窗口的相对坐标；Mutter 又移动了属性窗，因此那份归档只能证明发出了点击，不能证明点击 Wfg。该历史结论保持不变。本轮新增独立辅助程序，从唯一 `Edit Object Properties` 窗口 ID 调用 `xwininfo -id`，只读取 `Absolute upper-left X/Y` 和尺寸；移动指针后再次核对相同窗口的绝对几何，几何不稳定则不点击。两个新实验只发出一次鼠标按下/释放，不输入参数、不 Apply/OK、不保存设计。

所有商业 OA、截图、网表、日志、连接配置留在 Git 忽略的私有 `results/runs/`。公开文档只记录证据类别和状态，不附带器件参数或截图。实验前检查来宾可用物理内存，使用独占 Xvfb/Mutter display；运行后检查源 schematic OA 前后字节及远端残留进程。

| 只读模式 | 私有 run ID | 点击与 Cadence 观察 | 只读审计 |
| --- | --- | --- | --- |
| `-nographE` + Mutter | `20260927T150359Z_7987493d` | 点击时窗口绝对几何稳定；指针位于 Wfg 输入区；`hiSetCurrentField` 返回 `t`，但延时 `hiGetKeyboardFocusField=InfoAll`、`hiGetCurrentForm=nil`；X I/O 异常退出 | `click_emitted_focus_not_proven`，`click_target_verified=true`，源 OA 未变；首版未记录后屏 SHA 字段，不能声称该字段通过哈希验收 |
| 完整 Virtuoso GUI + Mutter | `20260927T151028Z_26cc4b54` | 运行前来宾可用物理内存约 2583 MiB；窗口绝对几何稳定，点击时指针位于 Wfg 输入区；Cadence 延时焦点仍为 `InfoAll`，`hiGetCurrentForm=nil`；X I/O 异常退出 | `click_emitted_focus_not_proven`，`click_target_verified=true`，后屏哈希与 OA 前后字节均通过 |

点击目标的结论来自点击时保存的窗口 ID、绝对几何、辅助程序报告及私有 XWD 画面核对；它不等于 Cadence 表单接受了键盘焦点。辅助程序没有键入字符，因而也没有证明 Wfg 数值可修改、CDF callback 会运行、PCell 合法范围正确、网表/寄生会随几何变化。两轮退出均不干净，`gui_x_io_failure` 不能降格成成功。虚拟机 `seat0` 的活动 `X0` 会话属于 GDM greeter，不是可直接借用的用户设计桌面；回合后 Virtuoso、Spectre、OCEAN、Xvfb、Mutter 均为空闲。

新增代码：`circuit/skill/x11_click_form_field_absolute.py`、`circuit/skill/run_virtuoso_gui_mutter_full_capture.sh`，以及 `run_virtuoso_form_focus_probe.py` 和 `audit_virtuoso_form_capture_probe.py` 的可选绝对点击/完整 GUI 模式。旧 helper 和旧归档不被改写；审计器按归档模式核对脚本哈希、窗口 ID、点击坐标、OA、XWD 和已存在的后屏哈希。合成篡改测试覆盖点击报告、窗口详情、helper、OA 与焦点报告，真实私有两份新归档均可重新只读审计。

本机定向测试 `34 passed`；加入本探针后的全量 Python 回归 `907 passed, 7 skipped`。测试不验证 CDF/PCell 或射频设计指标。

## 门禁与后续

本轮消除了“是否点到 Wfg”的一个测量歧义，却仍未建立 Cadence **内部** Wfg 焦点。不要继续在当前无交互 Xvfb 路径盲目发送键盘值，也不要把低层参数赋值或属性级网表变化当成 CDF/PCell 验证。Stage 03/08/09 的物理与合格 LNA fullchain 仍为 `partial`。下一次有效实验需要授权交互式用户桌面，或由工艺/EDA 负责人给出可审计的受支持 CDF/PCell 参数设置、回调、网表/寄生和 DRC 验证路径；随后才在新用户 cell 做一次受限单字段编辑。独立软件层 Stage 10/11 工作不必等待这一门禁。

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_virtuoso_form_capture_probe results/runs/virtuoso_cdf_form_variant/20260927T025834Z_c26b554a results/runs/virtuoso_form_focus_probe/20260927T150359Z_7987493d
python -m orfadc.experiments.audit_virtuoso_form_capture_probe results/runs/virtuoso_cdf_form_variant/20260927T025834Z_c26b554a results/runs/virtuoso_form_focus_probe/20260927T151028Z_26cc4b54
python -m pytest tests/test_x11_click_form_absolute.py tests/test_virtuoso_form_capture_probe.py tests/test_virtuoso_mutter_focus_probe.py -q
```
