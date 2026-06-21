# WenQu 开源前检查清单

本文档用于记录项目开源前需要完成的仓库清理、安全检查和发布准备。

## 仓库内容

- [ ] 确认 `.env`、本地数据库、日志、临时文件和 IDE 配置未被 Git 跟踪。
- [ ] 确认 `.codex-artifacts/`、截图对比产物和本地 QA 生成物未被 Git 跟踪。
- [ ] 保留 `uv.lock` 和 `frontend/package-lock.json`，用于复现 Python 与前端依赖环境。
- [ ] 检查示例数据只放在 `examples/` 下，且不包含真实业务数据。

## 安全检查

- [ ] 使用 `gitleaks`、`trufflehog` 或等价工具扫描当前仓库和 Git 历史。
- [ ] 确认历史提交中没有真实 API Key、数据库密码、连接串、私钥或内部地址。
- [ ] 确认 `.env.example` 只包含示例值，并说明生产环境必须自行配置密钥。
- [ ] 确认日志脱敏策略覆盖 prompt、SQL、数据源连接串、模型 API Key 和返回样例。

## 文档准备

- [ ] 完善根目录 `README.md`：项目定位、功能截图、架构图、快速启动、常见问题。
- [ ] 增加 `LICENSE`，明确开源协议。
- [ ] 增加 `CONTRIBUTING.md`，说明本地开发、测试、提交规范。
- [ ] 增加 `SECURITY.md`，说明漏洞报告方式和生产安全建议。
- [ ] 保持 `docs/project-design.md` 与当前架构一致。

## 工程验证

- [ ] 后端测试通过：`.venv/bin/python -m pytest -q`。
- [ ] 前端测试通过：`npm --prefix frontend test -- --run`。
- [ ] 前端构建通过：`npm --prefix frontend run build`。
- [ ] 使用本地示例数据跑通至少一个信贷智能体和一个电商智能体问数链路。

## 发布准备

- [ ] 配置 GitHub Actions，至少覆盖后端测试和前端构建。
- [ ] 准备首个 Release Notes，说明当前能力边界和已知限制。
- [ ] 检查 Issue / PR 模板是否需要补充。
