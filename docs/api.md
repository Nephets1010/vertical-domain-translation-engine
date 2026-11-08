# API 文档 · VDT-MT 垂直领域专业术语机器翻译引擎

> 版本：v0.1.0 ｜ 基础路径：`http://localhost:8000` ｜ 接口前缀：`/api/v1`
> 交互式文档：启动后访问 `http://localhost:8000/docs`（Swagger UI）或 `/redoc`。

---

## 0. 通用约定

### 0.1 鉴权
默认部署**不启用**鉴权（内网 / 单机场景）。生产建议在前置网关（Nginx / API 网关 /
Kong）增加 API Key / OAuth2；本服务通过 `API_CORS_ORIGINS` 与 `API_RATE_LIMIT_PER_MIN`
做基础边界控制。

### 0.2 错误处理
所有业务异常继承 `VdtmtError`，统一返回如下结构（HTTP 状态码见下表）：

```json
{
  "error": {
    "code": 40400,
    "message": "术语不存在",
    "context": { "term_id": 123 }
  }
}
```

| 错误码 | HTTP | 含义 |
|--------|------|------|
| 40000 | 400 | 参数校验失败（ValidationError） |
| 40400 | 404 | 资源不存在（NotFoundError） |
| 40900 | 409 | 资源冲突（ConflictError） |
| 42900 | 429 | 触发限流（RateLimitError） |
| 50200 | 502 | 翻译 / 评估上游失败 |
| 50300 | 503 | 功能不可用（如缺 GPU 的真实训练，UnavailableError） |
| 50000 | 500 | 未预期内部错误（已脱敏） |

### 0.3 内容类型
请求与响应均为 `application/json`（UTF-8），除 `/viz`（HTML 页面）与
`/api/v1/viz/term-graph`（JSON）。

---

## 1. 系统与健康

### `GET /health`
存活探针。返回组件状态。

```json
{ "status": "ok", "version": "0.1.0",
  "components": { "db": "ok", "scheduler": "running", "translator": "mock" } }
```

### `GET /ready`
就绪探针：数据库可连通、依赖齐备时返回 200，否则 503。

### `GET /metrics`
Prometheus 指标：`vdtmt_requests_total`、`vdtmt_request_latency_seconds`、
`vdtmt_term_hits_total`、`vdtmt_risk_alerts_total`、各指标 Gauge 等。

---

## 2. 语料（Corpus · M1）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/v1/corpus` | 列表（支持 `?domain=&skip=&limit=`） |
| GET  | `/api/v1/corpus/count` | 计数（支持 `?domain=`） |
| GET  | `/api/v1/corpus/{id}` | 单条详情 |
| POST | `/api/v1/corpus` | 新增句对（自动清洗 + 质量评分） |
| POST | `/api/v1/corpus/ingest` | 导入文件 |
| DELETE | `/api/v1/corpus/{id}` | 删除 |

### 新增句对 `POST /api/v1/corpus`
请求：
```json
{ "src_text": "The merger agreement is binding.", "tgt_text": "该并购协议具有约束力。",
  "domain": "legal", "source": "manual" }
```
响应 `201`：
```json
{ "id": 1, "src_text": "The merger agreement is binding.",
  "tgt_text": "该并购协议具有约束力。", "domain": "legal", "source": "manual",
  "quality_score": 0.92, "created_at": "2026-11-08T12:00:00" }
```
> 入库前会经过 `corpus.cleaner`：去噪 / 对齐 / 质量评分；评分低于阈值标记为
> `low_quality`（仍可入库但供训练过滤），源=译文完全相同将**硬失败**（400）。

### 导入文件 `POST /api/v1/corpus/ingest`
```json
{ "path": "sample_data/corpus/en_zh_sample.jsonl",
  "file_type": "jsonl",            // jsonl | tsv | csv_terms | tmx | web
  "domain": "general", "source": "sample" }
```
支持类型：
- `jsonl`：每行 `{src_text, tgt_text, domain?}`
- `tsv`：制表符分隔 `src\ttgt`
- `csv_terms`：术语表 `literal,target,domain?,confidence?`（UTF-8 BOM 自动处理）
- `tmx`：翻译记忆交换格式（解析 `<tu>/<tuv>`）
- `web`：抓取网页正文文本（需可联网）

响应返回 `IngestReport`：
```json
{ "accepted": 25, "rejected": 0, "low_quality": 0,
  "provenance_id": 3, "detail": { "...": "..." } }
```
导入同时写入 `SourceProvenance`（来源可追溯）。

---

## 3. 术语库与术语网络（Terminology · M2）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/v1/terms` | 列表（`?domain=&enabled=&skip=&limit=`） |
| GET  | `/api/v1/terms/search?q=` | 检索（PG `LIKE` / 可选 ES） |
| GET  | `/api/v1/terms/{id}` | 详情 |
| POST | `/api/v1/terms` | 新增术语 |
| POST | `/api/v1/terms/bulk` | 批量导入 |
| POST | `/api/v1/terms/extract` | 从语料抽取并入库 |
| POST | `/api/v1/terms/relations` | 写入术语关系（轻量图谱） |
| POST | `/api/v1/terms/suggest-network` | 术语网络（图谱）导出 |
| GET  | `/api/v1/terms/{id}/relations` | 某术语的关联 |
| DELETE | `/api/v1/terms/{id}` | 删除 |

### 新增术语 `POST /api/v1/terms`
```json
{ "literal": "merger agreement", "target": "并购协议", "domain": "legal",
  "confidence": 0.95, "source": "manual", "enabled": true }
```

### 抽取术语 `POST /api/v1/terms/extract`
从指定 domain 语料中自动抽取候选术语并入库（确定性算法，无 LLM）。
```json
{ "domain": "legal", "min_freq": 2, "limit": 100 }
```
响应：`{ "extracted": 12, "stored": 12, "skipped": 0 }`

### 写入关系 `POST /api/v1/terms/relations`
```json
{ "source_literal": "merger agreement", "target_literal": "acquisition",
  "relation_type": "synonym", "weight": 1.0, "domain": "legal", "evidence": "co-occur in 5 docs" }
```
`relation_type` 取值：`synonym` / `antonym` / `disambiguation` / `hypernym` / `cooccurrence`。

### 术语网络导出 `POST /api/v1/terms/suggest-network`
返回 `{ "nodes": [...], "edges": [...] }`，供可视化 / 关联挖掘消费。

---

## 4. 领域微调（Training · M3）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/training/prepare` | 离线构建 SFT 数据集 |
| POST | `/api/v1/training/dry-run` | 离线演练（登记版本） |
| POST | `/api/v1/training/run` | 真实 LoRA 微调（需 GPU + ML 栈） |
| GET  | `/api/v1/training/versions` | 模型版本列表 |
| GET  | `/api/v1/training/versions/{id}` | 版本详情 |
| DELETE | `/api/v1/training/versions/{id}` | 删除版本 |

### 准备数据集 `POST /api/v1/training/prepare`
```json
{ "domain": "legal", "out_path": "./data/train_legal.jsonl" }
```
响应：`{ "path": "./data/train_legal.jsonl", "count": 120, "with_hints": 80, "domain": "legal" }`
（仅取 `quality_score >= 0.5` 的句对；命中术语时注入 `[TERMS]` 提示。）

### 演练 `POST /api/v1/training/dry-run`
无需 GPU，登记一个 `status=dry_run` 版本，证明管线接通。

### 真实训练 `POST /api/v1/training/run`
```json
{ "domain": "legal" }
```
**依赖守护**：若环境缺少 `torch/peft/transformers/deepspeed` 或 GPU，返回 `503`
（`code=50300`，`context.mode=requires_gpu`）并给出可执行指引，**绝不静默失败**。
成功时登记 `status=completed` 的 `ModelVersion`，返回 adapter 路径。

---

## 5. 翻译（Translation · M4 / M6）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/translate` | 单条术语约束翻译 |
| POST | `/api/v1/translate/batch` | 批量翻译（异步任务） |
| POST | `/api/v1/translate/document` | 整篇文档翻译 |
| GET  | `/api/v1/translate/jobs/{id}` | 任务状态 / 结果 |

### 单条翻译 `POST /api/v1/translate`
请求：
```json
{ "text": "The merger agreement is binding.", "domain": "legal",
  "source_lang": "en", "target_lang": "zh", "use_term_injection": true }
```
响应：
```json
{
  "translated": "该并购协议具有约束力。",
  "domain": "legal", "backend": "mock",
  "term_hits": [ { "literal": "merger agreement", "target": "并购协议", "matched": true } ],
  "term_hit_rate": 1.0,
  "comet_score": null,
  "risk_score": 0.0,
  "warnings": []
}
```
**术语注入机制**：将命中的术语字面替换为占位符 `@TERM<n>@` → 调用翻译器 → 强制还原，
**保证 100% 术语准确率**（术语不被改写）。`backend` 由 `TRANSLATOR_BACKEND` 决定：
`mock`（离线默认）/ `vllm` / `api`（OpenAI 兼容）。

### 批量翻译 `POST /api/v1/translate/batch`
```json
{ "texts": ["...", "..."], "domain": "legal", "job_title": "legal-batch-001" }
```
响应 `201`：`{ "job_id": 7, "status": "pending", "total": 200 }`。
通过 `GET /api/v1/translate/jobs/{id}` 轮询获取结果与进度。

### 文档翻译 `POST /api/v1/translate/document`
整篇文档（按句切分）批量翻译，返回 `{ "job_id": ..., "segments": [...] }`。

---

## 6. 质量风险引擎与评分（Quality · M5）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/eval/evaluate` | 评估译文并触发风险规则 |
| POST | `/api/v1/eval/feedback` | 错误句对回流（错误闭环） |
| GET  | `/api/v1/eval/records` | 评估记录列表 |
| GET  | `/api/v1/eval/risks` | 风险列表（`?resolved=`） |
| POST | `/api/v1/eval/risks/{id}/resolve` | 处置风险 |

### 评估 `POST /api/v1/eval/evaluate`
```json
{ "src": "The merger agreement is binding.", "tgt": "该协议具有约束力。",
  "translated": "该并购协议具有约束力。", "domain": "legal", "job_id": null }
```
评分逻辑：
- `comet_score`：启用 COMET 时用 COMETKiwi；否则**回退**到字符 Jaccard 词法相似度。
- `term_hit_rate`：术语命中率。
- `risk_score`：加权聚合（`TERM_HIT_WEIGHT` / `COMET_WEIGHT`），命中"严重规则"额外 +0.2。

触发规则：`low_comet`（COMET 低于 `RISK_COMET_LOW`）、`term_miss`（术语未命中率高于
`RISK_TERM_MISS_RATE_HIGH`）、`low_confidence_term`、`domain_drift`（领域漂移率高于
`RISK_DOMAIN_DRIFT_RATE`）。命中规则写入 `QualityRisk`。

响应：`{ "eval_id": 12, "comet_score": 0.88, "term_hit_rate": 1.0,
"risk_score": 0.0, "risks": [], "warnings": [] }`

### 错误回流 `POST /api/v1/eval/feedback`
将人工判定为错误的句对回写（可触发术语库热更新 / 数据集重建），形成
"评估 → 风险 → 术语补强 → 重训"闭环。
```json
{ "src": "...", "tgt": "...", "translated": "...", "domain": "legal",
  "error_type": "term_miss", "corrected": "..." }
```

---

## 7. 翻译智能分析（Analytics · 重映射模块）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/v1/analytics/associations` | 术语关联挖掘 |
| POST | `/api/v1/analytics/similar-cases` | 相似错误案例 |
| GET  | `/api/v1/analytics/report` | 质量报告摘要 |

### 关联挖掘 `GET /api/v1/analytics/associations?domain=legal&min_strength=0.1`
返回 `{ "items": [ { "term_a": "并购", "term_b": "协议", "cooccur_count": 9, "strength": 0.6 } ] }`。

### 相似案例 `POST /api/v1/analytics/similar-cases`
```json
{ "src": "The merger agreement is binding.", "error_type": "term_miss", "domain": "legal", "top_k": 5 }
```
基于错误类型 + 文本相似度返回历史相似评估记录。

### 质量报告 `GET /api/v1/analytics/report?domain=legal`
返回 `{ "domain": "legal", "sample_size": 120, "avg_comet": 0.85,
"avg_term_hit_rate": 0.97, "avg_risk_score": 0.05, "top_error_types": [...],
"risk_distribution": { "term_miss": 3, "low_comet": 1 }, "summary": "..." }`。

---

## 8. 可视化检索（Viz）

### `GET /api/v1/viz/term-graph?domain=general&node_limit=200`
返回术语网络数据：
```json
{ "domain": "general",
  "nodes": [ { "id": 1, "label": "merger agreement", "target": "并购协议",
               "domain": "general", "confidence": 0.95, "freq": 12 } ],
  "edges": [ { "source": 1, "target": 2, "relation_type": "synonym", "weight": 1.0 } ] }
```

### `GET /viz`
离线自包含术语网络可视化页面（`static/term_graph.html`，纯 SVG，无外部依赖），
前端拉取 `/api/v1/viz/term-graph` 并渲染力导向图。

---

## 9. 快速验证脚本

```bash
# 健康检查
curl http://localhost:8000/health

# 注入术语
curl -X POST http://localhost:8000/api/v1/terms \
  -H 'Content-Type: application/json' \
  -d '{"literal":"merger agreement","target":"并购协议","domain":"legal"}'

# 翻译
curl -X POST http://localhost:8000/api/v1/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"The merger agreement is binding.","domain":"legal"}'

# 评估
curl -X POST http://localhost:8000/api/v1/eval/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"src":"The merger agreement is binding.","tgt":"该协议具有约束力。","translated":"该并购协议具有约束力。","domain":"legal"}'
```
