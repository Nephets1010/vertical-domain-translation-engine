# 贡献指南（CONTRIBUTING）

感谢你关注 **VDT-MT 垂直领域专业术语机器翻译引擎**。本项目采用 MIT 许可证开源，
欢迎 Issue、讨论与 Pull Request。

---

## 1. 开发环境

```bash
python -m venv .venv
source .venv/Scripts/activate        # Windows
pip install -e ".[dev]"
cp .env.example .env                 # 默认 mock 翻译器 + SQLite
```

运行测试（全程离线、SQLite，无需 GPU / Postgres）：

```bash
pytest tests/ -q
```

提交前请保持：

```bash
ruff check src tests                  # 风格 / 静态检查（若已安装）
pytest tests/ -q                      # 测试全绿
```

---

## 2. 分支与提交约定

- 默认分支为 `main`。
- 功能开发请基于 `main` 切出特性分支：`feature/xxx`、`fix/xxx`、`docs/xxx`。
- 提交信息建议遵循 Conventional Commits：
  `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`。
- 一个 PR 聚焦一件事，附带必要的测试与文档更新。

---

## 3. 代码规范

- **配置**：所有密钥 / 环境相关项通过环境变量（`.env`，不入库）；禁止在代码中硬编码口令。
- **日志**：使用 `vdtmt.logging_setup.get_logger`，结构化（JSON）输出；勿用裸 `print`。
- **异常**：业务异常继承 `VdtmtError`（见 `src/vdtmt/exceptions.py`），返回结构化错误。
- **测试**：新功能必须含单元测试（纯逻辑）与集成测试（FastAPI TestClient + SQLite
  `StaticPool`）。离线可跑是硬要求。
- **依赖守护**：涉及 GPU / 重型 ML 栈（如真实训练）必须做可用性探测，缺失时显式
  `UnavailableError`，**不得静默失败或假装成功**。

---

## 4. 架构边界（简述）

| 模块 | 路径 | 职责 |
|------|------|------|
| 配置 / 日志 / 异常 | `src/vdtmt/{config,logging_setup,exceptions}.py` | 横切基础 |
| 语料 M1 | `corpus/` | 接入 / 清洗 / 质量评分 |
| 术语 M2 | `terminology/` | 抽取 / 术语库 / 术语网络（轻量图谱） |
| 微调 M3 | `training/` | SFT 数据格式化 / 训练编排 / 版本登记 |
| 翻译 M4/M6 | `translation/` | 术语注入翻译 / 批量 / 文档 |
| 质量 M5 | `quality/` | COMET/词法评估 / 风险规则 / 错误回流 |
| 分析（重映射） | `analytics/` | 关联挖掘 / 相似案例 / 报告 |
| 接口层 | `api/` | FastAPI 路由 |
| 调度 / 监控 | `scheduler/`, `monitoring/` | APScheduler / Prometheus / 告警 |
| 决策记录 | `docs/adr/` | ADR（含已采纳的决策与备选） |

涉及架构级改动请先阅读 `docs/adr/` 并考虑新增 ADR。

---

## 5. 提交 Issue / PR 前自查

- [ ] `pytest tests/` 全绿
- [ ] 新增功能有测试覆盖
- [ ] 文档（`README.md` / `docs/api.md` / 相关 ADR）已同步更新
- [ ] 未提交任何密钥或 `.env`
- [ ] 遵循 Conventional Commits

---

## 6. 行为准则

请保持友善、就事论事。对不同意见以 PR 讨论与 ADR 记录为准，避免人身攻击。

如有疑问，欢迎在 GitHub Issues 中提问。
