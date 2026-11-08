"""SQLAlchemy 数据模型（企业级：命名清晰、约束明确、可溯源）。

对应文档数据模型并扩展：
  corpus / term / translation_job / eval_record
  + term_relation（术语网络/图谱）
  + model_version（模型版本管理）
  + quality_risk（质量风险告警记录）
  + source_provenance（来源溯源）
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Corpus(Base):
    """平行语料句对。"""

    __tablename__ = "corpus"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    src_text: Mapped[str] = mapped_column(Text, nullable=False)
    tgt_text: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(String(64), default="general", nullable=False)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    source: Mapped[str] = mapped_column(String(128), default="unknown", nullable=False)
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<Corpus id={self.id} domain={self.domain} q={self.quality_score:.2f}>"


class Term(Base):
    """术语条目（术语库核心）。literal+domain 唯一。"""

    __tablename__ = "term"
    __table_args__ = (UniqueConstraint("literal", "domain", name="uq_term_literal_domain"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    literal: Mapped[str] = mapped_column(String(256), nullable=False)
    target: Mapped[str] = mapped_column(String(256), nullable=False)
    domain: Mapped[str] = mapped_column(String(64), default="general", nullable=False)
    freq: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    source: Mapped[str] = mapped_column(String(128), default="extracted", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    relations: Mapped[list["TermRelation"]] = relationship(
        "TermRelation",
        foreign_keys="TermRelation.source_term_id",
        back_populates="source_term",
        cascade="all, delete-orphan",
    )


class TermRelation(Base):
    """术语网络（图谱）边：同义/反义/消歧/上下位/共现等。"""

    __tablename__ = "term_relation"
    __table_args__ = (
        UniqueConstraint(
            "source_term_id", "target_term_id", "relation_type", "domain",
            name="uq_term_relation",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_term_id: Mapped[int] = mapped_column(
        ForeignKey("term.id", ondelete="CASCADE"), nullable=False
    )
    target_term_id: Mapped[int] = mapped_column(
        ForeignKey("term.id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    domain: Mapped[str] = mapped_column(String(64), default="general", nullable=False)
    evidence: Mapped[str] = mapped_column(Text, default="", nullable=False)

    source_term: Mapped[Term] = relationship(
        "Term", foreign_keys=[source_term_id], back_populates="relations"
    )


class ModelVersion(Base):
    """微调模型版本登记。"""

    __tablename__ = "model_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    base_model: Mapped[str] = mapped_column(String(256), nullable=False)
    adapter_path: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class TranslationJob(Base):
    """批量翻译/文档翻译任务。"""

    __tablename__ = "translation_job"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    doc_path: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    domain: Mapped[str] = mapped_column(String(64), default="general", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    model_ver: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result_path: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    evals: Mapped[list["EvalRecord"]] = relationship(
        "EvalRecord", back_populates="job", cascade="all, delete-orphan"
    )


class EvalRecord(Base):
    """翻译质量评估结果 + 错误回流。"""

    __tablename__ = "eval_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("translation_job.id", ondelete="CASCADE"), nullable=True
    )
    corpus_id: Mapped[int | None] = mapped_column(
        ForeignKey("corpus.id", ondelete="SET NULL"), nullable=True
    )
    src_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tgt_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    comet_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    term_hit_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    error_type: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    job: Mapped[TranslationJob | None] = relationship(
        "TranslationJob", back_populates="evals"
    )


class QualityRisk(Base):
    """质量风险告警（规则引擎命中记录）。"""

    __tablename__ = "quality_risk"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    eval_id: Mapped[int | None] = mapped_column(
        ForeignKey("eval_record.id", ondelete="CASCADE"), nullable=True
    )
    rule: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="warning", nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class SourceProvenance(Base):
    """来源溯源：记录每条语料/术语的数据出处。"""

    __tablename__ = "source_provenance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_name: Mapped[str] = mapped_column(String(256), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    extra: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
