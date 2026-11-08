"""Pydantic 数据契约（API 出入参、跨模块传输对象）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------- 语料 ----------
class CorpusCreate(BaseModel):
    src_text: str = Field(..., min_length=1)
    tgt_text: str = Field(..., min_length=1)
    domain: str = "general"
    source: str = "manual"
    meta: dict[str, Any] = Field(default_factory=dict)


class CorpusRead(CorpusCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    quality_score: float
    created_at: datetime


# ---------- 术语 ----------
class TermCreate(BaseModel):
    literal: str = Field(..., min_length=1, max_length=256)
    target: str = Field(..., min_length=1, max_length=256)
    domain: str = "general"
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    source: str = "manual"
    enabled: bool = True


class TermRead(TermCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    freq: int
    updated_at: datetime


class TermRelationCreate(BaseModel):
    source_literal: str
    target_literal: str
    relation_type: str = "synonym"  # synonym/antonym/disambiguation/hypernym/cooccurrence
    weight: float = 1.0
    domain: str = "general"
    evidence: str = ""


class TermRelationRead(TermRelationCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class TermSearchResult(BaseModel):
    literal: str
    target: str
    domain: str
    confidence: float
    freq: int


# ---------- 翻译 ----------
class TranslateRequest(BaseModel):
    text: str = Field(..., min_length=1)
    domain: str = "general"
    source_lang: str = "en"
    target_lang: str = "zh"
    use_term_injection: bool = True


class TermHit(BaseModel):
    literal: str
    target: str
    matched: bool


class TranslateResponse(BaseModel):
    translated: str
    domain: str
    backend: str
    term_hits: list[TermHit] = Field(default_factory=list)
    term_hit_rate: float = 0.0
    comet_score: float | None = None
    risk_score: float = 0.0
    warnings: list[str] = Field(default_factory=list)


class BatchTranslateRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=1000)
    domain: str = "general"
    source_lang: str = "en"
    target_lang: str = "zh"
    use_term_injection: bool = True
    job_title: str = "batch"


class BatchTranslateResponse(BaseModel):
    job_id: int
    status: str
    total: int


# ---------- 评估 / 风险 ----------
class EvalRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    job_id: int | None
    comet_score: float
    term_hit_rate: float
    error_type: str
    risk_score: float
    created_at: datetime


class QualityRiskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rule: str
    severity: str
    message: str
    resolved: bool
    created_at: datetime


# ---------- 分析 ----------
class AssociationItem(BaseModel):
    term_a: str
    term_b: str
    cooccur_count: int
    strength: float


class SimilarCase(BaseModel):
    eval_id: int
    error_type: str
    snippet: str
    similarity: float


class QualityReport(BaseModel):
    domain: str
    sample_size: int
    avg_comet: float
    avg_term_hit_rate: float
    avg_risk_score: float
    top_error_types: list[dict[str, Any]]
    risk_distribution: dict[str, int]
    summary: str


# ---------- 通用 ----------
class HealthResponse(BaseModel):
    status: str
    version: str
    components: dict[str, str]


class MessageResponse(BaseModel):
    message: str
