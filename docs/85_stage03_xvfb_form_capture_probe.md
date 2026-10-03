# Stage 03: Virtuoso 属性表单帧缓冲与鼠标焦点诊断

## 范围

沿用 `docs/69_stage03_form_focus_probe.md` 的已归档用户 schematic，只读打开实例属性表单。新增 Xvfb `-fbdir` 捕获与一次受限鼠标点击；没有发送键盘字符、点击 Apply/OK、调用 CDF callback 或保存 OA。商业器件值、截图、原始日志和远端路径仅在 Git 忽略的 `results/runs/`，不进公开仓库或外部模型请求。

## 过程与证据

- 无 PDK 的短时 Xvfb 试验证实帧缓冲文件需在服务存活时复制；停机后 Xvfb 自动移除 backing file。XWD 头和 BGRX 像素已在本地解码。
- `20260927T093506Z_cdbaab96` 的 1280×800 截图显示属性表单，但窗口树中的表单为 1169×712、起点 x=350，右侧超出帧边界。源 OA 前后字节相同，字段焦点仍是 `InfoAll`，会话以致命 X I/O 错误结束。
- `20260927T093901Z_bc548df8` 改为 1920×1080，完整显示属性表单和 Finger width 输入框；这是可视化定位，不是 CDF 参数写入。焦点和异常退出结论未改变。
- `20260927T094328Z_ada37ff7` 的首个点击运行在窗口标题出现后仅等待 1 秒。点击前画面尚未绘制表单，即使 XTest 报告已发出点击，也不能认定击中了输入框。该失败档保留。
- `20260927T094712Z_fc44a02c` 在窗口出现后等待 8 秒，点击前完整表单已绘制。辅助程序从唯一属性窗口几何计算目标位置，发出一次左键按下/释放；报告目标为窗口内 Finger width 区域。前后 1920×1080 帧缓冲的 RGB 像素比较仅 534 个像素不同，表单实际仍可见。Cadence 延时读回 `focus_later_before=InfoAll`、`focus_later_after=InfoAll`；源 OA 前后字节一致、报告完整，但进程仍以致命 X I/O 错误结束。**点击发出不等于字段焦点成立，更不等于参数编辑成功。**

`src/orfadc/experiments/audit_virtuoso_form_capture_probe.py` 独立检查最终归档的受控脚本/启动器/点击辅助程序哈希、XWD 头和长度、窗口几何与点击位置、Cadence 焦点报告、X I/O 错误及源 OA 前后字节；审计结论只能是 `click_emitted_focus_not_proven`，`form_field_edited=false`、`cdf_callback_validated=false`、`not_lna_result=true`、`spec_pass=null`。篡改焦点状态、OA、截图或点击记录均被拒绝。截图不属于可公开的 PDK 交付物。

## 阶段判定

Stage 03 仍为 `partial`。当前 Xvfb 没有已装窗口管理器，`hiSetCurrentField` 返回成功却不能改变 `hiGetKeyboardFocusField` 的 `InfoAll`，鼠标事件也没有形成可验证的 Wfg 焦点；会话还存在 X I/O 退出故障。停止自动键盘输入。后续需在授权交互桌面或经确认的窗口管理器环境中先取得稳定焦点和干净退出，再以新用户 cell 的单参数键盘编辑、CDF callback、OA/网表读回、同候选 PCell/DRC 和模型警告解释逐级验收。现有直接属性赋值、表单截图和低层 PCell 几何响应均不能代替这条链路。
