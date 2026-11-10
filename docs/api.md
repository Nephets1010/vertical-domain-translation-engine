# API 文档 · VDT-MT 垂直领域专业术语机器翻译引擎

> 版本：v0.1.0 ｜ 基础路径：`http://localhost:8000` ｜ 接口前缀：`/api/v1`
> 交互式文档：启动后访问 `http://localhost:8000/docs`（Swagger UI）或 `/redoc`。
> 所有 JSON 字段名均以 `src/vdtmt/schemas.py` 与路由源码为准；下文凡与旧文档不符处，均已按源码修正。

---

## 0. 通用约定

### 0.1 鉴权
默认部署**不启用**鉴权（内网 / 单机场景）。生产建议在前置网关（Nginx / API 网关 / Kong）增加 API Key / OAuth2；本服务通过 `API_CORS_ORIGINS` 与 `API_RATE_LIMIT_PER_MIN` 做基础边界控制。

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
| 40900 | 409 | 资源冲突（ConflictError，如自关联术语） |
| 42900 | 429 | 触发限流（配置 `API_RATE_LIMIT_PER_MIN`） |
| 50200 | 502 | 翻译上游失败（TranslationError） |
| 50300 | 503 | 功能不可用（如缺 GPU 的真实训练，UnavailableError） |
| 50000 | 500 | 未预期内部错误（已脱敏） |

> 说明：`422 Unprocessable Entity` 由 FastAPI/Pydantic 在请求体字段校验失败时**自动**返回，其结构为 FastAPI 原生的 `detail` 数组（见 §0.4），不走上面的 `error` 包装。

### 0.3 内容类型
请求与响应均为 `application/json`（UTF-8），除 `/viz`（HTML 页面）与 `/api/v1/viz/term-graph`（JSON）。

### 0.4 错误响应示例

**400 参数校验失败（VdtmtError 包装）**
```json
{
  "error": {
    "code": 40000,
    "message": "no updatable fields provided",
    "context": {}
  }
}
```

**404 资源不存在**
```json
{
  "error": {
    "code": 40400,
    "message": "term not found: 999",
    "context": {}
  }
}
```

**409 资源冲突（如将术语关联到自身）**
```json
{
  "error": {
    "code": 40900,
    "message": "cannot relate a term to itself",
    "context": {}
  }
}
```

**422 请求体字段校验失败（FastAPI 原生结构，非 `error` 包装）**
```json
{
  "detail": [
    {
      "loc": ["body", "text"],
      "msg": "Field required",
      "type": "missing"
    }
  ]
}
```

---

## 1. 端到端演练（End-to-End Walkthrough）

下面按真实顺序演示「载入样例 → 启动服务 → 术语约束翻译 → 质量评估 → 质量报告」完整闭环。所有命令假设已在项目根目录且已安装依赖（见 §10）。

### 步骤 0：载入样例数据（CLI）

```bash
# 使用默认样例路径（自动建表并写入 corpus 与 terms）
python -m vdtmt.tools.seed

# 等价显式写法（路径可覆盖）
python -m vdtmt.tools.seed \
  --corpus sample_data/corpus/en_zh_sample.jsonl \
  --terms  sample_data/corpus/terms.csv
```

输出（节选）：
```
SEED_REPORT: {'corpus': {'accepted': 25, 'rejected': 0, 'low_quality': 0}, 'terms': 18}
```

### 步骤 1：启动服务

```bash
uvicorn vdtmt.main:app --reload --port 8000
```

健康检查：
```bash
curl http://localhost:8000/health
# {"status":"ok","version":"0.1.0","components":{"db":"ok","scheduler":"running","translator":"mock"}}
```

### 步骤 2：列出术语

```bash
curl "http://localhost:8000/api/v1/terms?domain=legal&limit=5"
```

```python
import requests
r = requests.get("http://localhost:8000/api/v1/terms",
                 params={"domain": "legal", "limit": 5})
print(r.json())
# [{"id":1,"literal":"merger agreement","target":"并购协议","domain":"legal",
#   "confidence":0.95,"source":"sample","enabled":true,"freq":3,"updated_at":"..."}]
```

### 步骤 3：术语约束翻译

```bash
curl -X POST http://localhost:8000/api/v1/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"The merger agreement is binding.","domain":"legal","use_term_injection":true}'
```

```python
import requests
r = requests.post("http://localhost:8000/api/v1/translate", json={
    "text": "The merger agreement is binding.",
    "domain": "legal",
    "use_term_injection": True,
})
print(r.json())
# {"translated":"该并购协议具有约束力。","domain":"legal","backend":"mock",
#  "term_hits":[{"literal":"merger agreement","target":"并购协议","matched":true}],
#  "term_hit_rate":1.0,"comet_score":null,"risk_score":0.0,"warnings":[]}
```

### 步骤 4：质量评估（触发风险规则）

```bash
curl -X POST http://localhost:8000/api/v1/eval/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"src":"The merger agreement is binding.","tgt":"该协议具有约束力。","domain":"legal","term_hit_rate":0.0}'
```

```python
import requests
r = requests.post("http://localhost:8000/api/v1/eval/evaluate", json={
    "src": "The merger agreement is binding.",
    "tgt": "该协议具有约束力。",           # 待评估译文（术语被漏译）
    "domain": "legal",
    "term_hit_rate": 0.0,                 # 术语未命中率 100%
})
print(r.json())
# {"eval_id":12,"comet_score":null,"term_hit_rate":0.0,"error_type":"term_miss",
#  "risk_score":0.4,"hits":[{"rule":"term_miss","severity":"warning",
#  "message":"term miss rate 1.000 > 0.2"}]}
```

### 步骤 5：质量报告

```bash
curl "http://localhost:8000/api/v1/analytics/report?domain=legal"
```

```python
import requests
r = requests.get("http://localhost:8000/api/v1/analytics/report",
                 params={"domain": "legal"})
print(r.json())
# {"domain":"legal","sample_size":1,"avg_comet":0.0,"avg_term_hit_rate":0.0,
#  "avg_risk_score":0.4,"top_error_types":[{"error_type":"term_miss","count":1}],
#  "risk_distribution":{"term_miss":1},"summary":"..."}
```

---

## 2. 系统与健康

### `GET /health`
存活探针。返回服务状态与运行环境（与路由源码 `src/vdtmt/api/routes_health.py` 一致）。

```json
{ "status": "ok", "version": "0.1.0", "env": "dev" }
```

### `GET /ready`
就绪探针：数据库可连通、依赖齐备时返回 200，否则 503。

### `GET /metrics`
Prometheus 指标：`vdtmt_requests_total`、`vdtmt_request_latency_seconds`、`vdtmt_term_hits_total`、`vdtmt_risk_alerts_total`、各指标 Gauge 等。

---

## 3. 语料（Corpus · M1）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/v1/corpus` | 列表（支持 `?domain=&limit=&offset=`） |
| GET  | `/api/v1/corpus/count` | 计数（支持 `?domain=`） |
| GET  | `/api/v1/corpus/{id}` | 单条详情 |
| POST | `/api/v1/corpus` | 新增句对（自动清洗 + 质量评分） |
| POST | `/api/v1/corpus/ingest` | 导入文件（查询参数） |
| DELETE | `/api/v1/corpus/{id}` | 删除 |

### 新增句对 `POST /api/v1/corpus`
请求（`CorpusCreate`）：
```json
{ "src_text": "The merger agreement is binding.", "tgt_text": "该并购协议具有约束力。",
  "domain": "legal", "source": "manual", "meta": {} }
```
响应 `201`（`CorpusRead`）：
```json
{ "id": 1, "src_text": "The merger agreement is binding.",
  "tgt_text": "该并购协议具有约束力。", "domain": "legal", "source": "manual",
  "meta": {}, "quality_score": 0.92, "created_at": "2026-11-08T12:00:00" }
```
> 入库前会经过 `corpus.cleaner`：去噪 / 对齐 / 质量评分；评分低于阈值标记为 `low_quality`（仍可入库但供训练过滤），源=译文完全相同将**硬失败**（400）。

### 导入文件 `POST /api/v1/corpus/ingest`
> 注意：该端点通过**查询参数**接收输入（非 JSON 请求体）。

```bash
curl -X POST "http://localhost:8000/api/v1/corpus/ingest" \
  --data-urlencode "path=sample_data/corpus/en_zh_sample.jsonl" \
  --data-urlencode "domain=general" \
  --data-urlencode "fmt=auto"
```

```python
import requests
r = requests.post("http://localhost:8000/api/v1/corpus/ingest", params={
    "path": "sample_data/corpus/en_zh_sample.jsonl",
    "domain": "general",
    "fmt": "auto",            # auto | jsonl | tsv | csv | tmx
    "accept_low_quality": False,
})
print(r.json())
```

支持的 `fmt`：
- `jsonl`：每行 `{src_text, tgt_text, domain?}`
- `tsv`：制表符分隔 `src\ttgt`
- `csv`：术语表 `literal,target,domain?,confidence?`（UTF-8 BOM 自动处理）
- `tmx`：翻译记忆交换格式（解析 `<tu>/<tuv>`）
- `auto`：按扩展名推断（默认）

响应返回 `IngestReport`：
```json
{ "source_name": "en_zh_sample.jsonl", "total": 25, "accepted": 25,
  "rejected": 0, "low_quality": 0, "first_id": 1, "provenance_id": 3 }
```
导入同时写入 `SourceProvenance`（来源可追溯）。

### 列表 `GET /api/v1/corpus`
```bash
curl "http://localhost:8000/api/v1/corpus?domain=legal&limit=10&offset=0"
```
```python
import requests
r = requests.get("http://localhost:8000/api/v1/corpus",
                 params={"domain": "legal", "limit": 10, "offset": 0})
print(r.json())
```

### 计数 `GET /api/v1/corpus/count`
```bash
curl "http://localhost:8000/api/v1/corpus/count?domain=legal"
# {"domain":"legal","count":25}
```

---

## 4. 术语库与术语网络（Terminology · M2）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/v1/terms` | 列表（`?domain=&enabled=&limit=&offset=`） |
| GET  | `/api/v1/terms/search?q=` | 检索（PG `LIKE` / 可选 ES） |
| GET  | `/api/v1/terms/{id}` | 详情 |
| POST | `/api/v1/terms` | 新增术语（幂等 upsert） |
| POST | `/api/v1/terms/bulk` | 批量导入 |
| POST | `/api/v1/terms/extract` | 从语料抽取并入库（查询参数） |
| POST | `/api/v1/terms/relations` | 写入术语关系（轻量图谱） |
| POST | `/api/v1/terms/suggest-network` | 术语网络（图谱）导出 |
| GET  | `/api/v1/terms/{id}/relations` | 某术语的关联 |
| PATCH | `/api/v1/terms/{id}` | 局部更新可写字段 |
| DELETE | `/api/v1/terms/{id}` | 删除 |

### 新增术语 `POST /api/v1/terms`
请求（`TermCreate`）：
```json
{ "literal": "merger agreement", "target": "并购协议", "domain": "legal",
  "confidence": 0.95, "source": "manual", "enabled": true }
```
响应 `201`（`TermRead`）：
```json
{ "id": 1, "literal": "merger agreement", "target": "并购协议", "domain": "legal",
  "confidence": 0.95, "source": "manual", "enabled": true, "freq": 0, "updated_at": "..." }
```

### 批量导入 `POST /api/v1/terms/bulk`
```bash
curl -X POST http://localhost:8000/api/v1/terms/bulk \
  -H 'Content-Type: application/json' \
  -d '{"terms":[{"literal":"anti-trust","target":"反垄断","domain":"legal"}],"source":"manual"}'
```
```python
import requests
r = requests.post("http://localhost:8000/api/v1/terms/bulk", json={
    "terms": [{"literal": "anti-trust", "target": "反垄断", "domain": "legal"}],
    "source": "manual",
})
print(r.json())   # {"imported": 1}
```

### 检索 `GET /api/v1/terms/search`
```bash
curl "http://localhost:8000/api/v1/terms/search?q=merger&domain=legal&limit=10"
```
```python
import requests
r = requests.get("http://localhost:8000/api/v1/terms/search",
                 params={"q": "merger", "domain": "legal", "limit": 10})
# [{"literal":"merger agreement","target":"并购协议","domain":"legal",
#   "confidence":0.95,"freq":3}]
```

### 抽取术语 `POST /api/v1/terms/extract`
> 注意：通过**查询参数**接收输入（非 JSON 请求体）；响应为 `{domain, extracted, literals}`。

```bash
curl -X POST "http://localhost:8000/api/v1/terms/extract?domain=legal&min_conf=0.7"
```
```python
import requests
r = requests.post("http://localhost:8000/api/v1/terms/extract",
                 params={"domain": "legal", "min_conf": 0.7})
print(r.json())
# {"domain":"legal","extracted":12,"literals":["acquisition","..."]}
```
从指定 domain 语料中自动抽取候选术语并入库（确定性算法，无 LLM）；`min_conf` 为最低置信度阈值（默认 0.7）。

### 写入关系 `POST /api/v1/terms/relations`
```bash
curl -X POST http://localhost:8000/api/v1/terms/relations \
  -H 'Content-Type: application/json' \
  -d '{"source_literal":"merger agreement","target_literal":"acquisition","relation_type":"synonym","weight":1.0,"domain":"legal","evidence":"co-occur in 5 docs"}'
```
```python
import requests
r = requests.post("http://localhost:8000/api/v1/terms/relations", json={
    "source_literal": "merger agreement", "target_literal": "acquisition",
    "relation_type": "synonym", "weight": 1.0, "domain": "legal",
    "evidence": "co-occur in 5 docs"})
print(r.json())
# {"id":1,"relation_type":"synonym","weight":1.0,"domain":"legal",
#  "evidence":"co-occur in 5 docs","source_literal":"merger agreement",
#  "target_literal":"acquisition"}
```
`relation_type` 取值：`synonym` / `antonym` / `disambiguation` / `hypernym` / `cooccurrence`。写入前两端术语必须已存在于该 domain，且不可自关联（否则 409）。

### 术语网络导出 `POST /api/v1/terms/suggest-network`
```bash
curl -X POST "http://localhost:8000/api/v1/terms/suggest-network?domain=legal"
# {"domain":"legal","relations":9}
```
由语料共现与同译文自动建议关系，返回新增关系条数（节点/边可在 `/api/v1/viz/term-graph` 取得完整图谱）。

### 局部更新 `PATCH /api/v1/terms/{id}`
仅接受 `literal` / `target` / `domain` / `confidence` / `enabled` / `source` 中的可写字段（其余忽略；若全为空则返回 400）。
```bash
curl -X PATCH http://localhost:8000/api/v1/terms/1 \
  -H 'Content-Type: application/json' \
  -d '{"confidence":0.99,"enabled":true}'
# 返回更新后的 TermRead
```

### 列表 / 详情 / 关联 / 删除
```bash
curl "http://localhost:8000/api/v1/terms?domain=legal&enabled=true&limit=50&offset=0"
curl "http://localhost:8000/api/v1/terms/1"
curl "http://localhost:8000/api/v1/terms/1/relations"
curl -X DELETE http://localhost:8000/api/v1/terms/1
# {"message":"deleted"}
```

---

## 5. 领域微调（Training · M3）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/training/prepare` | 离线构建 SFT 数据集（查询参数） |
| POST | `/api/v1/training/dry-run` | 离线演练（登记版本，无需 GPU） |
| POST | `/api/v1/training/run` | 真实 LoRA 微调（需 GPU + ML 栈） |
| GET  | `/api/v1/training/versions` | 模型版本列表 |
| GET  | `/api/v1/training/versions/{id}` | 版本详情 |
| DELETE | `/api/v1/training/versions/{id}` | 删除版本 |

### 准备数据集 `POST /api/v1/training/prepare`
```bash
curl -X POST "http://localhost:8000/api/v1/training/prepare?domain=legal&out_path=./data/train_legal.jsonl"
```
```python
import requests
r = requests.post("http://localhost:8000/api/v1/training/prepare",
                 params={"domain": "legal", "out_path": "./data/train_legal.jsonl"})
print(r.json())
# {"path":"./data/train_legal.jsonl","count":120,"with_hints":80,"domain":"legal"}
```
（仅取 `quality_score >= 0.5` 的句对；命中术语时注入 `[TERMS]` 提示。）

### 演练 `POST /api/v1/training/dry-run`
无需 GPU，登记一个 `status=dry_run` 版本，证明管线接通。
```bash
curl -X POST "http://localhost:8000/api/v1/training/dry-run?domain=legal"
# {"model_version_id":1,"name":"dry-Qwen2.5-7B-legal","status":"dry_run"}
```

### 真实训练 `POST /api/v1/training/run`
```bash
curl -X POST "http://localhost:8000/api/v1/training/run?domain=legal"
```
**依赖守护**：若环境缺少 `torch/peft/transformers/deepspeed` 或 GPU，返回 `503`（`code=50300`，`context.mode=requires_gpu`）并给出可执行指引，**绝不静默失败**。
成功时登记 `status=completed` 的 `ModelVersion`，返回 adapter 路径：
```json
{ "model_version_id": 2, "name": "lora-Qwen2.5-7B-legal",
  "adapter_path": "./models/lora/adapter", "status": "completed", "metrics": {"loss":0.0,"eval_loss":0.0} }
```
可选请求体（`TrainingConfigPayload`，全部有默认值）：
```json
{ "base_model": "Qwen2.5-7B", "lora_r": 16, "lora_alpha": 32, "lora_dropout": 0.05,
  "learning_rate": 0.0002, "num_epochs": 3, "per_device_batch_size": 4,
  "max_seq_length": 1024, "output_dir": "./models/lora", "use_term_hints": true }
```

### 版本列表 `GET /api/v1/training/versions`
```bash
curl "http://localhost:8000/api/v1/training/versions"
# [{"id":1,"name":"dry-Qwen2.5-7B-legal","base_model":"Qwen2.5-7B",
#   "adapter_path":"","metrics":{"note":"dry_run"},"created_at":"..."}]
```

---

## 6. 翻译（Translation · M4 / M6）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/translate` | 单条术语约束翻译 |
| POST | `/api/v1/translate/batch` | 批量翻译（同步落库任务） |
| POST | `/api/v1/translate/document` | 整篇文档翻译（按句切分） |
| GET  | `/api/v1/translate/jobs/{id}` | 任务状态 / 结果路径 |

### 单条翻译 `POST /api/v1/translate`
请求（`TranslateRequest`）：
```json
{ "text": "The merger agreement is binding.", "domain": "legal",
  "source_lang": "en", "target_lang": "zh", "use_term_injection": true }
```
响应（`TranslateResponse`）：
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
**术语注入机制**：将命中的术语字面替换为占位符 `@TERM<n>@` → 调用翻译器（真实后端被要求保留占位符）→ 强制还原为权威译文，**保证 100% 术语准确率**（术语不被改写）。`backend` 由 `TRANSLATOR_BACKEND` 决定：`mock`（离线默认）/ `vllm` / `api`（OpenAI 兼容）。

### 批量翻译 `POST /api/v1/translate/batch`
```bash
curl -X POST http://localhost:8000/api/v1/translate/batch \
  -H 'Content-Type: application/json' \
  -d '{"texts":["The merger agreement is binding.","The contract is valid."],"domain":"legal","job_title":"legal-batch-001"}'
```
```python
import requests
r = requests.post("http://localhost:8000/api/v1/translate/batch", json={
    "texts": ["The merger agreement is binding.", "The contract is valid."],
    "domain": "legal", "job_title": "legal-batch-001"})
print(r.json())   # {"job_id":7,"status":"completed","total":2}
```
通过 `GET /api/v1/translate/jobs/{id}` 获取进度与结果文件路径：
```bash
curl http://localhost:8000/api/v1/translate/jobs/7
# {"id":7,"title":"legal-batch-001","domain":"legal","status":"completed",
#  "total":2,"processed":2,"result_path":"./data/batch_7.jsonl"}
```

### 文档翻译 `POST /api/v1/translate/document`
整篇文档（按句切分）翻译，返回译文与句段数（**非**任务对象）：
```bash
curl -X POST http://localhost:8000/api/v1/translate/document \
  -H 'Content-Type: application/json' \
  -d '{"text":"The merger agreement is binding. The contract is valid.","domain":"legal"}'
```
```python
import requests
r = requests.post("http://localhost:8000/api/v1/translate/document", json={
    "text": "The merger agreement is binding. The contract is valid.",
    "domain": "legal"})
print(r.json())
# {"translated":"该并购协议具有约束力。 该合同有效。","segments":2,"domain":"legal"}
```

---

## 7. 质量风险引擎与评分（Quality · M5）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/eval/evaluate` | 评估译文并触发风险规则 |
| POST | `/api/v1/eval/feedback` | 错误句对回流（错误闭环） |
| GET  | `/api/v1/eval/records` | 评估记录列表 |
| GET  | `/api/v1/eval/risks` | 风险列表（`?resolved=`） |
| POST | `/api/v1/eval/risks/{id}/resolve` | 处置风险 |

### 评估 `POST /api/v1/eval/evaluate`
请求（`EvaluateRequest`）：`src` 原文、`tgt` 待评估译文、`ref` 可选参考译文、`term_hit_rate` 术语命中率（来自翻译阶段）、`warnings` 翻译阶段告警、`job_id` / `corpus_id` 可选关联。
```bash
curl -X POST http://localhost:8000/api/v1/eval/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"src":"The merger agreement is binding.","tgt":"该协议具有约束力。","domain":"legal","term_hit_rate":0.0}'
```
```python
import requests
r = requests.post("http://localhost:8000/api/v1/eval/evaluate", json={
    "src": "The merger agreement is binding.",
    "tgt": "该协议具有约束力。",   # 术语被漏译
    "domain": "legal",
    "term_hit_rate": 0.0,
    "warnings": [],
    "job_id": None,
    "corpus_id": None,
})
print(r.json())
```
评分逻辑：
- `comet_score`：启用 COMET 时用 COMETKiwi；否则**回退**到字符级 Jaccard 词法相似度（需 `ref`）；两者皆无则为 `null`。
- `error_type`：`term_hit_rate < 1.0` → `term_miss`；否则 `comet_score < RISK_COMET_LOW` → `low_quality`；否则 `none`。
- `risk_score`：规则加权聚合（`TERM_HIT_WEIGHT` / `COMET_WEIGHT`），命中"严重规则"额外 +0.2，上限 1.0。

触发规则：`low_comet`、`term_miss`、`low_confidence_term`、`domain_drift`。命中规则写入 `QualityRisk` 并触发告警。

响应：
```json
{ "eval_id": 12, "comet_score": null, "term_hit_rate": 0.0,
  "error_type": "term_miss", "risk_score": 0.4,
  "hits": [ { "rule": "term_miss", "severity": "warning", "message": "term miss rate 1.000 > 0.2" } ] }
```

### 错误回流 `POST /api/v1/eval/feedback`
将人工判定为错误的句对回写（登记为 `source=feedback` 待复审语料 + 评估记录），形成"评估 → 风险 → 术语补强 → 重训"闭环。请求（`FeedbackRequest`）：`src`、`tgt`、`domain`、`error_type`（默认 `manual_flag`）、`note`。
```bash
curl -X POST http://localhost:8000/api/v1/eval/feedback \
  -H 'Content-Type: application/json' \
  -d '{"src":"The merger agreement is binding.","tgt":"该协议具有约束力。","domain":"legal","error_type":"term_miss","note":"漏译术语 并购协议"}'
```
```python
import requests
r = requests.post("http://localhost:8000/api/v1/eval/feedback", json={
    "src": "The merger agreement is binding.",
    "tgt": "该协议具有约束力。",
    "domain": "legal", "error_type": "term_miss",
    "note": "漏译术语 并购协议"})
print(r.json())   # {"corpus_id":30,"eval_id":13}
```

### 记录 / 风险 / 处置
```bash
curl "http://localhost:8000/api/v1/eval/records?domain=legal&limit=50"
curl "http://localhost:8000/api/v1/eval/risks?resolved=false"
curl -X POST http://localhost:8000/api/v1/eval/risks/5/resolve
# {"message":"resolved"}
```

---

## 8. 翻译智能分析（Analytics · 重映射模块）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/v1/analytics/associations` | 术语关联挖掘 |
| POST | `/api/v1/analytics/similar-cases` | 相似错误案例 |
| GET  | `/api/v1/analytics/report` | 质量报告摘要 |

### 关联挖掘 `GET /api/v1/analytics/associations`
> 注意：参数为 `min_cooccur`（最小共现次数，默认 2），**不是** `min_strength`；响应为**数组**（非 `items` 包装）。

```bash
curl "http://localhost:8000/api/v1/analytics/associations?domain=legal&min_cooccur=2&limit=100"
```
```python
import requests
r = requests.get("http://localhost:8000/api/v1/analytics/associations",
                 params={"domain": "legal", "min_cooccur": 2, "limit": 100})
print(r.json())
# [{"term_a":"并购","term_b":"协议","cooccur_count":9,"strength":0.6}]
```

### 相似案例 `POST /api/v1/analytics/similar-cases`
请求（`SimilarCaseRequest`）：`snippet`（文本片段）、`eval_id`（按评估记录查找）、`top_k`（默认 5）。二选一提供 `snippet` 或 `eval_id`。
```bash
curl -X POST http://localhost:8000/api/v1/analytics/similar-cases \
  -H 'Content-Type: application/json' \
  -d '{"snippet":"该协议具有约束力","top_k":5}'
```
```python
import requests
r = requests.post("http://localhost:8000/api/v1/analytics/similar-cases", json={
    "snippet": "该协议具有约束力", "top_k": 5})
# [{"eval_id":12,"error_type":"term_miss","snippet":"该协议具有约束力。","similarity":0.83}]
```
基于错误类型 + 文本相似度返回历史相似评估记录。

### 质量报告 `GET /api/v1/analytics/report`
```bash
curl "http://localhost:8000/api/v1/analytics/report?domain=legal"
```
```python
import requests
r = requests.get("http://localhost:8000/api/v1/analytics/report",
                 params={"domain": "legal"})
print(r.json())
# {"domain":"legal","sample_size":120,"avg_comet":0.85,
#  "avg_term_hit_rate":0.97,"avg_risk_score":0.05,
#  "top_error_types":[{"error_type":"term_miss","count":3}],
#  "risk_distribution":{"term_miss":3,"low_comet":1},"summary":"..."}
```
`domain` 默认值为 `all`（全量）；返回 `QualityReport`（`top_error_types` 为对象数组）。

---

## 9. 可视化检索（Viz）

### `GET /api/v1/viz/term-graph?domain=general&node_limit=200`
返回术语网络数据：
```bash
curl "http://localhost:8000/api/v1/viz/term-graph?domain=general&node_limit=200"
```
```python
import requests
r = requests.get("http://localhost:8000/api/v1/viz/term-graph",
                 params={"domain": "general", "node_limit": 200})
print(r.json())
```
```json
{ "domain": "general",
  "nodes": [ { "id": 1, "label": "merger agreement", "target": "并购协议",
               "domain": "general", "confidence": 0.95, "freq": 12 } ],
  "edges": [ { "source": 1, "target": 2, "relation_type": "synonym", "weight": 1.0 } ] }
```
`edges` 的 `source` / `target` 为 `term.id`。

### `GET /viz`
离线自包含术语网络可视化页面（`static/term_graph.html`，纯 SVG，无外部依赖），前端拉取 `/api/v1/viz/term-graph` 并渲染力导向图。

---

## 10. CLI 与运维：种子数据 / 迁移 / 环境变量

### 10.1 种子数据工具 `vdtmt.tools.seed`
```bash
# 默认路径（sample_data/corpus/en_zh_sample.jsonl + terms.csv），自动建表
python -m vdtmt.tools.seed

# 仅灌语料 / 仅灌术语
python -m vdtmt.tools.seed --corpus sample_data/corpus/en_zh_sample.jsonl
python -m vdtmt.tools.seed --terms  sample_data/corpus/terms.csv

# 跳过不存在的默认路径而不报错
python -m vdtmt.tools.seed --no-default-paths
```
`seed` 会先调用 `init_db()` 建表，再将语料写入 `corpus`、术语写入 `term`（`source=sample`），并打印 `SEED_REPORT`。

### 10.2 数据库迁移
```bash
# 生产：使用 Alembic（数据库无关，SQLite/PostgreSQL 通用）
alembic upgrade head

# 开发/测试：应用启动时若 ENVIRONMENT=dev/test 会自动 init_db()
# 也可手动：python -c "from vdtmt.db.base import init_db; init_db()"
```
> 注意：开发用 `init_db()` 创建全部表；生产**必须**走 `alembic upgrade head` 以保证迁移可追溯。

### 10.3 环境变量（`.env.example` 中的关键项）
| 变量 | 说明 | 默认 |
|------|------|------|
| `ENVIRONMENT` | `dev` / `test` / `prod`，决定是否自动 `init_db` | `dev` |
| `DATABASE_URL` | 数据库连接串（SQLite/PostgreSQL） | `sqlite:///./vdtmt.db` |
| `DATABASE_ECHO` | 是否打印 SQL | `false` |
| `REDIS_ENABLED` / `REDIS_URL` | 可选缓存 | `false` |
| `USE_ELASTICSEARCH` / `ELASTICSEARCH_URL` / `ELASTICSEARCH_INDEX` | 可选术语检索 | `false` |
| `TRANSLATOR_BACKEND` | `mock` / `vllm` / `api` | `mock` |
| `VLLM_BASE_URL` / `VLLM_MODEL_NAME` | vLLM 后端 | — |
| `API_BASE_URL` / `API_MODEL_NAME` / `API_KEY` / `API_TIMEOUT_SECONDS` | OpenAI 兼容 API 后端 | — |
| `COMET_ENABLED` / `COMET_MODEL` | COMET 质量评估 | `false` / `Unbabel/wmt22-cometkiwi-da` |
| `TERM_HIT_WEIGHT` / `COMET_WEIGHT` | 风险评分权重 | `0.5` / `0.5` |
| `TERM_INJECTION_ENABLED` / `MAX_TERMS_PER_REQUEST` / `LOW_CONFIDENCE_THRESHOLD` | 术语注入 | `true` / `200` / `0.6` |
| `RISK_COMET_LOW` / `RISK_TERM_MISS_RATE_HIGH` / `RISK_DOMAIN_DRIFT_RATE` | 风险阈值 | `0.75` / `0.20` / `0.30` |
| `SCHEDULER_ENABLED` / `METRICS_ENABLED` / `METRICS_PORT` | 调度与监控 | `true` / `true` / `9090` |
| `API_CORS_ORIGINS` / `API_RATE_LIMIT_PER_MIN` | 安全边界 | `*` / `120` |

复制模板：`cp .env.example .env`（敏感信息如 `API_KEY`、DB 口令**绝不入库**）。

---

## 11. 快速验证脚本

```bash
# 健康检查
curl http://localhost:8000/health

# 注入术语
curl -X POST http://localhost:8000/api/v1/terms \
  -H 'Content-Type: application/json' \
  -d '{"literal":"merger agreement","target":"并购协议","domain":"legal"}'

# 术语约束翻译
curl -X POST http://localhost:8000/api/v1/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"The merger agreement is binding.","domain":"legal"}'

# 评估（漏译触发风险）
curl -X POST http://localhost:8000/api/v1/eval/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"src":"The merger agreement is binding.","tgt":"该协议具有约束力。","domain":"legal","term_hit_rate":0.0}'
```
