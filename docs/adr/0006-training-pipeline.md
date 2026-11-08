# ADR-0006 领域微调管线（模块 M3）

- 状态：已采纳（2026-11-08）
- 决策人：交付总监 Qi

## 背景

垂直领域翻译质量高度依赖领域术语与语体一致性。通用基座模型（如 Qwen2.5-7B）在
垂直术语上准确率不足，需要通过监督微调（SFT）注入领域风格与术语偏好。模块 M3 负责
将「清洗后的平行语料 + 术语库」转化为可训练的 SFT 数据集，并登记可审计的模型版本。

工程约束：交付环境为 Windows + 无 GPU + 无 Docker 守护进程；CI 亦无法访问 GPU。
因此管线必须做到：**离线可跑（数据准备、版本登记、dry-run），真实训练受依赖守护，
绝不静默失败**。

## 决策

### 1. 三层职责分离

- **数据格式化（`training/format.py`）**：纯函数 `format_pair` / `build_training_dataset`，
  不依赖 GPU/数据库会话以外的资源，完全可单测、可复现。每条样本包含
  `messages`（system / user / assistant）与结构化字段（`src/tgt/domain/term_hints`），
  user 内容在命中术语时注入 `[TERMS] 字面->目标` 提示，使模型学习"术语约束"行为。
- **训练编排（`training/pipeline.py`）**：`TrainingPipeline` 暴露 `prepare`（离线建集）、
  `dry_run`（离线登记版本）、`run`（真实训练）、`list_versions`。
- **版本登记**：每次训练（含 dry-run）均写入 `ModelVersion`，保证可审计、可回滚。

### 2. 真实训练路径受依赖守护

`TrainingPipeline._training_available()` 在运行时探测 `torch / peft / transformers /
deepspeed`；任一缺失即显式抛出 `UnavailableError`（带 `mode=requires_gpu` 上下文与可执行
指引），**绝不静默跳过或假装成功**。`run()` 进入的真实路径（`_real_train`）使用
PEFT `LoraConfig`（默认 `r=16, alpha=32, dropout=0.05, target_modules=[q_proj,v_proj]`）
+ HuggingFace `Trainer`，并预留 `deepspeed=ds_zero2.json` 加载点（`TrainingConfig.
deepspeed_config`）。本地无 GPU 时不会进入该分支。

### 3. 默认离线、显式升级

- `dry_run`：在无 GPU 环境登记一个 `status=dry_run` 的版本，证明管线已接通、配置可用，
  不消耗算力。
- `prepare`：仅做数据集构建（写 `./data/train_{domain}.jsonl`），任意环境可执行，
  供后续在 GPU 节点 `run()` 消费。

### 4. 训练超参集中配置

`TrainingConfig` 默认值（基座模型名、`lora_r/alpha/dropout`、`learning_rate=2e-4`、
`num_epochs=3`、`per_device_batch_size=4`、`max_seq_length=1024`、输出目录、是否注入
术语提示）集中管理，便于实验复现与横切替换。

## 后果

- 管线在开发机 / CI / 无 GPU 环境均可完整跑通（prepare + dry_run + 版本列表），
  真实训练在具备 GPU 与依赖的节点一键升级。
- 模型版本全程登记，错误回流（质量风险 → 术语热更新 → 重建数据集）闭环可追溯。
- 依赖隔离避免因缺少 ML 栈导致整个服务启动失败：翻译/质量/分析等模块不受影响。

## 备选

- **训练服务独立进程 / 微服务**：过早拆分增加运维，中小规模不必要。否决，保留为
  同进程内受守护的管线，未来可平滑抽出。
- **直接在线调用 API 翻译器替代微调**：无法沉淀领域私有能力、长期成本高、数据出域风险。
  否决，微调作为长期资产，API 仅作轻量后端候选。
- **把数据集构建也塞进训练守护**：会降低可测试性。否决，数据集构建保持零依赖。
