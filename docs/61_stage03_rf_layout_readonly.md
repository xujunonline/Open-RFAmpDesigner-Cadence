# Stage 03：授权 RF MOS 默认版图视图只读探针

## 目的与范围

此前 CDF 只读报告列出 RF MOS 的 `layout`、`ivpcell` 等 view，但“存在 view 名称”不等于实际几何可打开。本次在授权虚拟机上，仅用 OCEAN/SKILL 的 `dbOpenCellViewByType(... "r")` 分别打开这两个 view，读取边界框及形状、子实例、端子数量，然后关闭。**没有创建或修改 PDK/用户 OA cell、没有设置 CDF 参数、没有调用 callback、没有网表或 Spectre 仿真。** 原始脚本、远端回读、报告、OCEAN 日志和运行状态保存在 Git 忽略的 `results/runs/pdk_geometry_readonly/rf_layout_readonly_20260927_01/`；公开文档不含 PDK 内部路径或几何数据。

## 结果与核验

- 执行前宿主可用物理内存约 3.96 GiB，超过项目 2.66 GiB 门禁；OCEAN 返回码 0，报告下载成功。
- `layout` 和 `ivpcell` 均以只读方式打开，边界框非空，均有四个端子；前者有形状和子实例，后者有形状。报告记录了精确数量和边界框，留在私有档案中。
- 上传后的远端脚本下载回读，SHA-256 与本地脚本一致：`22089d745eb743badc16366dac099713cd0313c1274eca0cae9611457561c547`。私有报告的 SHA-256 为 `189f73d08c7285d230356f933207d6dd84561607eb512e2ad6d9dc2c5ed9d824`。
- 退出日志有 `hiDisplayForm` 在初始化完成前无法显示阻塞表单的警告。这是本次 OCEAN 环境观察，**不能据此判定**此前 `vfoSetParam` 中断的原因，也不能推断 RF 器件回调故障。

## 未通过的门禁

只读打开的是 PDK 提供的默认版图视图，不是项目候选实例的生成后几何。它没有证明 `lr/wr/nr` 的合法范围或 CDF 回调顺序，也没有建立 schematic 实例属性、Spectre netlist、PCell 实际宽长/寄生与 DRC 之间的同一候选映射。仍需在授权交互式 Virtuoso 环境对**新的用户库诊断 cell**进行单参数变更、Check and Save、网表导出及版图/DRC 对照；不能原样重试此前失败的无图形 `vfoSetParam`。无可用交互会话时，此阶段保持 `partial`。

后续已在不同新用户 layout cell 通过低层参数放置确认单参数 PCell 几何响应，见 `docs/62_stage03_rf_pcell_geometry_probe.md`；本页的默认视图证据与后续实例响应证据仍不能替代 CDF 表单、schematic/netlist 和 DRC 的同候选对照。
