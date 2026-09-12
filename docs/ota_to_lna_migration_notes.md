# OTA 自动化能力迁移到 LNA

## 1. 本阶段目标

本阶段只迁移 Cadence 自动化基础设施，不迁移折叠共源共栅 OTA 电路本身。迁移来源是本地 `VirtuosoFoldedCascodeProject`，目标工程为 Open-RFAmpDesigner-Cadence。

迁移后的最小链路是：

```text
本地私有 YAML
  -> Python RemoteRunner
  -> ssh/scp
  -> Linux Cadence 环境
  -> OCEAN/Spectre
  -> PSFASCII 或 CSV
  -> Python 指标提取
```

## 2. 来源和落点

| OTA 工程来源 | 可复用能力 | 本项目落点 | 处理方式 |
| --- | --- | --- | --- |
| `src/python/remote_ocean.py` | SSH、SCP、OCEAN 启动 | `src/orfadc/cadence/remote_runner.py` | 去除固定主机、用户和安装路径后重写 |
| `src/python/verify_connection.py` | 主机和 Cadence 工具探测 | `RemoteRunner.probe()`、`verify_remote.py` | 改为结构化 JSON |
| `src/python/psfascii_metrics.py` | 复数 AC、DC、相位和交点解析 | `psfascii_reader.py` | 改为与 OTA 指标无关的通用解析器 |
| `src/python/sweep_sizes.py` | 运行目录、错误状态、结果回收 | 后续 experiment runner | 本阶段只提取执行模式，不复制 OTA 扫参循环 |
| `scripts/resolve_ssh_key.ps1` | 私钥放在 NTFS 用户目录 | 私有 YAML 和环境变量约定 | 不复制任何密钥 |
| `tests/test_psfascii_metrics.py` | 小样本解析测试 | `tests/test_psfascii_reader.py` | 扩展到复数和标量 RF trace |

## 3. 已实现接口

### 3.1 远程配置

复制示例文件，但不要修改示例本身：

```powershell
Copy-Item config\remote_cadence.example.yaml config\remote_cadence.local.yaml
```

只在 `remote_cadence.local.yaml` 中填写实验室环境。该文件已被 Git 忽略。字段包括：

- SSH host、user、port；
- 可选私钥路径；
- 远程工作根目录；
- `ocean`、`spectre` 命令或包装脚本；
- 可选 `DISPLAY` 和 `XAUTHORITY`；
- 连接和命令超时。

不支持 `StrictHostKeyChecking=no`。首次连接可使用 `accept-new`，稳定后建议改为 `yes`。

### 3.2 RemoteRunner

`RemoteRunner` 提供：

- `run_remote()`：按参数列表安全引用并执行远程命令；
- `run_shell()`：执行确实需要 shell 语法的命令；
- `ensure_remote_dir()`：创建候选运行目录；
- `upload()` / `download()`：SCP 文件传输；
- `probe()`：读取远端用户、主机、工作目录和 Cadence 命令位置；
- `verify_transfer()`：上传、下载并比较 SHA-256；
- `run_ocean_script()`：上传 OCEAN/SKILL 脚本、执行并可回收日志。

日志中的 SSH 私钥路径会替换为 `<identity-file>`，避免进入 candidate record。

### 3.3 PSFASCII reader

`psfascii_reader.py` 当前支持：

- 频率等 sweep 变量；
- 复数 trace，例如 AC 电压或 S 参数；
- 标量 trace，例如导出的 NF；
- DC typed scalar；
- 差分复数信号相减；
- 幅度 dB、相位展开和下降沿交点插值。

它只负责读取数值，不假设具体 PDK、节点名或 RF 指标。S11、S21、NF、IP1dB 等工程含义由后续 `extract_rf_metrics.py` 负责。

## 4. 本地验证

不连接 Cadence 即可运行：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m pytest tests\test_remote_runner.py tests\test_psfascii_reader.py -q
```

测试通过只证明命令构造、路径保护、传输状态和解析算法正确，不代表远程主机或 Cadence 可用。

## 5. 远程验证

准备私有配置后运行只读探测：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m orfadc.cadence.verify_remote --config config\remote_cadence.local.yaml
```

如需验证 SCP 往返，先创建不含敏感信息的小文本文件：

```powershell
Set-Content results\logs\transfer_probe.txt 'orfadc transfer probe'
python -m orfadc.cadence.verify_remote `
  --config config\remote_cadence.local.yaml `
  --round-trip results\logs\transfer_probe.txt
```

远端只会创建 `work_root/transfer_probe/` 并写入该测试文件。当前实现不会自动删除远端测试文件，以免工具在未知目录执行删除操作。

## 6. 明确不迁移的内容

- `.secrets/` 和任何私钥；
- `ssh/` 中的主机专用公钥；
- `project.json` 中的固定 IP、用户名和绝对安装路径；
- `pdk/` 探测报告和商业 PDK 信息；
- OTA 专用 Spectre 网表和 OA schematic；
- OTA 扫描结果和日志；
- 假设 TSMC40 器件名、端口顺序或 model section 的代码。

## 7. 本阶段验收边界

本阶段完成的是“可测试的远程执行与 PSFASCII 基础层”。在真实私有配置和远程探测尚未成功前，不能声称 Cadence 已接通；在 RF testbench 尚未运行前，也不能声称已经得到 S 参数、NF 或压缩点结果。
