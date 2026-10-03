# Stage 03: Mutter/X11 与 Virtuoso 表单焦点的只读边界

## 目的与安全范围

此前 `docs/85_stage03_xvfb_form_capture_probe.md` 在无窗口管理器的 Xvfb 中看到属性窗，却不能证明 `Wfg` 字段焦点，且有 X I/O 退出故障。本轮只验证**隔离窗口管理器和 X11 输入焦点能否改变 Cadence 表单状态**。所有 Virtuoso 回合只读打开既有**用户库** cell，不键入字符、不点击 Apply/OK、不执行参数写入或保存；每轮下载 schematic OA 前后字节并比较。商业截图、OA、日志和远端身份均保留于 Git 忽略的私有 `results/runs/`，不进入公开文档或外部模型请求。

## 独立窗口管理器探针

授权虚拟机已有 Mutter 40.9、`xprop`、`xwininfo` 和项目配置的 Xvfb，未安装 `openbox`/`xfwm4`/`xdotool`。`run_window_manager_probe.py` 在独占 display 启动 Xvfb/Mutter，读取根窗 `_NET_SUPPORTING_WM_CHECK`，不启动 Cadence。完整档 `results/runs/window_manager_probe/20260927T130445Z_0c200f55/` 的窗口管理器注册、当时 Xvfb/Mutter 存活均为真，原始日志与脚本哈希经 `audit_window_manager_probe.py` 重审为 `verified`，随后两个进程为空闲。此前两个私有尝试因本项目证据清单键名和 metrics envelope 错误而在归档末步失败，原始文件保留，没有当作通过证据。

## 两种只读 Virtuoso 焦点实验

| 模式 | 私有 run ID | 原始观察 | 审计结论 |
| --- | --- | --- | --- |
| Mutter、无输入事件 | `20260927T130718Z_21152f21` | WM 注册；表单显示；`hiSetCurrentField` 返回 `t`，延时 `hiGetKeyboardFocusField=InfoAll`、`hiGetCurrentForm=nil`；OA 不变；退出码非零，stderr 为 `IO Error 0 (Success) on Display` | `focus_not_proven`；首版 runner 未识别这条 X I/O 文本，旧归档分类差异被显式保留 |
| Mutter、一次鼠标点击及前后 XWD | `20260927T131307Z_a097cdbe` | 点击事件已发出；WM 在初次窗口树采样后移动了属性窗，旧树与点击时坐标不一致；延时仍为 `InfoAll`；OA 不变；X I/O 退出 | `click_target_unverified_focus_not_proven`，**不声称击中 Wfg** |
| Mutter、无点击/键盘的 X11 窗口焦点请求 | `20260927T132124Z_317a4d09` | 辅助程序对唯一属性窗发 `XSetInputFocus`，紧接着 `XGetInputFocus` 读回相同窗口 ID；Cadence 仍报告 `hiGetCurrentForm=nil`、延时 `InfoAll`；OA 不变；X I/O 退出 | `focus_not_proven` |
| Mutter、完整 Virtuoso GUI（非 `-nographE`） | `20260927T134424Z_5064d4f4` | 独占 display；运行前来宾物理可用约 2615 MiB；完整表单报告，无许可证/脚本错误；延时仍为 `InfoAll`，OA 不变，X I/O 退出 | `focus_not_proven` |

四个 Virtuoso 回合的源 OA 前后字节相同。新脚本和辅助程序独立保存，不修改旧归档所绑定的 launcher。runner 现同时识别旧 `fatal X IO error` 与本轮 `IO Error 0 (Success) on Display`，不会把后者误报成干净退出。受限焦点及证据负例测试 `22 passed`；加入完整 GUI 对照前的默认环境全量 Python 回归 `867 passed, 7 skipped`。私有 OA/XWD/连接配置经 Git 忽略规则核验；远端 Mutter/Xvfb/Virtuoso/Spectre/OCEAN 在回合后均为空闲。

[Cadence 社区关于 `hiSetCurrentField` 的答复](https://community.cadence.com/cadence_technology_forums/f/custom-ic-skill/39878/how-to-automatically-select-the-content-of-a-field-when-a-form-appears/1356142)将其用于选择已显示表单的字段；[关于 `hiGetCurrentForm` 的答复](https://community.cadence.com/cadence_technology_forums/f/custom-ic-skill/50800/different-behavior-of-higetcurrentform-hiformsym-in-ic-and-icadvm-version)指出结果依赖实际表单焦点。[Cadence 对 `-nographE` 的说明](https://community.cadence.com/cadence_technology_forums/f/custom-ic-skill/30432/how-to-execute-a-skill-script-at-command-line)明确其仍启用图形但隐藏 CIW；本轮完整 GUI 对照也未改变结果。**本项目的推断**：仅有 X11 窗口管理器注册、外窗输入焦点或 `hiSetCurrentField` 返回 `t`，不足以证明此 Virtuoso/PDK 属性表单的内部焦点成立。这不是 Cadence 对该 PDK 的官方根因判定。

## 下一门禁

后续用绝对 X11 几何重做的一次 `-nographE` 与一次完整 GUI 点击已核对 Wfg 目标位置，但两次 Cadence 内部焦点依旧为 `InfoAll` 并有 X I/O 退出；详见 `docs/97_stage03_absolute_wfg_click_boundary.md`。这**不改变**上表中首次相对坐标点击归档的“目标未证实”历史审计状态。

停止在当前无交互的 Xvfb/`-nographE` 路径上盲目发送键盘值，也不把低层直接赋值、callback 调用、网表寄生变化或 Calibre 退出码当作 CDF/PCell 通过。下一步需要授权交互式桌面或工艺/EDA 负责人确认：实际 Wfg 表单焦点、一次新用户 cell 单字段编辑、CDF callback/合法参数范围、OA/网表模型宽度与寄生映射、同候选 layout/DRC、模型 `SFE-1131` 语义。任何新增实验仍需新独占归档、物理内存门禁、源 OA 前后核验和原始 Spectre/版图证据。Stage 03/08/09 及合格 LNA fullchain 继续 `partial`，本轮没有新 LNA 结果。

```powershell
$env:PYTHONPATH='src'
python -m orfadc.experiments.audit_window_manager_probe results/runs/window_manager_probe/20260927T130445Z_0c200f55
python -m orfadc.experiments.audit_virtuoso_form_focus_probe results/runs/virtuoso_cdf_form_variant/20260927T025834Z_c26b554a results/runs/virtuoso_form_focus_probe/20260927T132124Z_317a4d09
python -m orfadc.experiments.audit_virtuoso_form_capture_probe results/runs/virtuoso_cdf_form_variant/20260927T025834Z_c26b554a results/runs/virtuoso_form_focus_probe/20260927T131307Z_a097cdbe
python -m orfadc.experiments.audit_virtuoso_form_focus_probe results/runs/virtuoso_cdf_form_variant/20260927T025834Z_c26b554a results/runs/virtuoso_form_focus_probe/20260927T134424Z_5064d4f4
python -m pytest tests/test_window_manager_probe.py tests/test_virtuoso_mutter_focus_probe.py -q
```
