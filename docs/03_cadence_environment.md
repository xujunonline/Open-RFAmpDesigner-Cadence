# Cadence 环境约定

本工程只提交 Cadence 调用接口、OCEAN 模板和结果 schema，不提交商业 PDK、PCell、模型文件、原始 netlist 或含敏感路径的日志。

推荐本地环境变量：

- `ORFADC_CADENCE_HOME`
- `ORFADC_CDS_LIB`
- `ORFADC_OCEAN_BIN`
- `ORFADC_SPECTRE_BIN`
- `ORFADC_WORK_ROOT`

本地私有配置可复制 `config/model_paths.yaml` 后改名为 `model_paths.local.yaml`，并加入 `.gitignore`。

远程 Cadence 主机使用 `config/remote_cadence.example.yaml` 作为无敏感信息模板，复制为被 Git 忽略的 `remote_cadence.local.yaml` 后填写。远程探测、SCP 验证和 OCEAN 上传执行接口见 `docs/ota_to_lna_migration_notes.md`。
