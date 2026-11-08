"""配置管理（企业级：环境隔离、密钥不硬编码、可校验）。

所有敏感信息（数据库口令、API Key、模型路径）均通过环境变量注入，
绝不以明文写在代码或提交到仓库。详见 .env.example。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置。优先级：环境变量 > .env 文件 > 默认值。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- 基础 ----
    app_name: str = "vdt-mt"
    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    log_json: bool = True

    # ---- 存储 ----
    # 开发/测试默认 SQLite（零依赖、可离线跑）；生产由 docker-compose 注入 PostgreSQL
    database_url: str = "sqlite:///./vdtmt.db"
    database_echo: bool = False
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = False  # 本地无 Redis 时关闭，降级为内存缓存

    # ---- 术语检索（可选 Elasticsearch）----
    use_elasticsearch: bool = False
    elasticsearch_url: str = "http://localhost:9200"
    elasticsearch_index: str = "vdt_terms"

    # ---- 翻译器后端 ----
    # mock: 确定性术语替换（离线/测试默认）；vllm: 本地 vLLM 服务；api: OpenAI 兼容 API
    translator_backend: Literal["mock", "vllm", "api"] = "mock"
    vllm_base_url: str = "http://localhost:8000/v1"
    vllm_model_name: str = "Qwen2.5-7B"
    api_base_url: str = ""
    api_model_name: str = ""
    api_timeout_seconds: float = 60.0
    # 注意：API Key 仅通过环境变量注入，见 api_key 字段
    api_key: str = ""

    # ---- 基座模型 / 微调（仅 M3 训练时使用，本地运行不依赖）----
    base_model_name: str = "Qwen2.5-7B"
    lora_adapter_path: str = ""  # 训练产物路径；为空则使用 base
    hf_cache_dir: str = "./models"

    # ---- 质量评估 ----
    comet_enabled: bool = False  # 未装 unbabel-comet 时自动回退到词法近似
    comet_model: str = "Unbabel/wmt22-cometkiwi-da"
    term_hit_weight: float = 0.5
    comet_weight: float = 0.5

    # ---- 术语注入 ----
    term_injection_enabled: bool = True
    max_terms_per_request: int = 200
    low_confidence_threshold: float = 0.6  # 低于该置信度交人工校核/告警

    # ---- 质量风险规则引擎阈值 ----
    risk_comet_low: float = 0.75  # COMET 低于该值触发风险
    risk_term_miss_rate_high: float = 0.20  # 术语未命中率高于该值触发风险
    risk_domain_drift_rate: float = 0.30  # 领域漂移比例阈值

    # ---- 调度与监控 ----
    scheduler_enabled: bool = True
    metrics_enabled: bool = True
    metrics_port: int = 9090

    # ---- 安全 ----
    api_cors_origins: str = "*"  # 生产应显式指定域名，逗号分隔
    api_rate_limit_per_min: int = 120

    @field_validator("api_cors_origins")
    @classmethod
    def _split_cors(cls, v: str) -> list[str]:
        if v in ("*", ""):
            return ["*"]
        return [o.strip() for o in v.split(",") if o.strip()]

    @property
    def is_testing(self) -> bool:
        return self.environment == "test"

    @property
    def is_production(self) -> bool:
        return self.environment == "prod"


@lru_cache
def get_settings() -> Settings:
    """进程内单例配置。测试中可通过 settings_env 覆盖。"""
    return Settings()


def reset_settings() -> None:
    """测试或重载时清空缓存。"""
    get_settings.cache_clear()
