"""翻译服务层（模块 M4）。

- 术语约束注入翻译：检测源文术语 -> 占位注入 -> 翻译 -> 强制还原。
- 单条 / 批量 / 文档（分块 + 全局术语锁定）三种入口。
- 术语命中率与低置信度告警在翻译阶段即产出，供质量风险引擎（Phase 5）使用。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db.models import Term, TranslationJob
from ..logging_setup import get_logger
from ..monitoring.metrics import get_metrics
from ..schemas import (
    BatchTranslateRequest,
    BatchTranslateResponse,
    TermHit,
    TranslateRequest,
    TranslateResponse,
)
from .injection import count_preserved, inject_terms, literal_present, restore_terms
from .translators import FallbackTranslator, MockTranslator, get_translator

logger = get_logger("vdtmt.translation.service")

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

# 落盘根目录：优先 VDT_DATA_DIR 环境变量，否则取包根（src/）下的 data，
# 不依赖进程当前工作目录（CWD）。
_BASE_DIR = Path(__file__).resolve().parents[2]


def _batch_data_dir() -> Path:
    """返回批量结果落盘目录并确保存在（CWD 无关）。"""
    data_dir = Path(os.getenv("VDT_DATA_DIR", str(_BASE_DIR / "data")))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


class TranslationService:
    def __init__(self, db: Session, translator=None) -> None:
        self.db = db
        self.settings = get_settings()
        # 主翻译器（用于命名/指标上报）
        self.translator = translator or get_translator(self.settings)
        # 韧性包装：主后端失败时降级到次级（默认 MockTranslator 以保证可返回）
        self._fallback = FallbackTranslator(self.translator, MockTranslator())

    def load_terms(self, domain: str) -> list[Term]:
        stmt = select(Term).where(Term.domain == domain, Term.enabled.is_(True))
        return list(self.db.execute(stmt).scalars().all())

    def detect_terms(self, src: str, domain: str) -> list[Term]:
        return [t for t in self.load_terms(domain) if literal_present(src, t.literal)]

    def _translate_core(
        self, src: str, domain: str, source_lang: str, target_lang: str,
        use_term_injection: bool, preloaded_terms: list[Term] | None = None,
    ) -> TranslateResponse:
        terms = preloaded_terms if preloaded_terms is not None else self.detect_terms(src, domain)
        warnings: list[str] = []
        if use_term_injection and terms and self.settings.term_injection_enabled:
            inj = inject_terms(src, [(t.literal, t.target) for t in terms])
            raw = self._fallback.translate(inj.injected, source_lang, target_lang)
            preserved = count_preserved(raw, inj.placeholders)
            translated = restore_terms(raw, inj.placeholders)
            hit = preserved  # 后端保留的占位符数 = 成功约束的术语数
        else:
            translated = self._fallback.translate(src, source_lang, target_lang)
            preserved = 0
            hit = 0

        total = len(terms)
        term_hit_rate = (hit / total) if total else (1.0 if not total else 0.0)
        for t in terms:
            if t.confidence < self.settings.low_confidence_threshold:
                warnings.append(f"low_confidence_term:{t.literal}")

        # 收集翻译器（含降级）产生的告警，如 fallback_used:<backend>
        for obj in (self.translator, self._fallback):
            extra = getattr(obj, "warnings", None)
            if extra:
                for w in extra:
                    if w not in warnings:
                        warnings.append(w)

        resp = TranslateResponse(
            translated=translated, domain=domain, backend=self.translator.name,
            term_hits=[TermHit(literal=t.literal, target=t.target, matched=True) for t in terms],
            term_hit_rate=term_hit_rate, comet_score=None, risk_score=0.0,
            warnings=warnings,
        )
        try:
            m = get_metrics()
            m.translation_requests.labels(domain=domain, backend=self.translator.name, status="ok").inc()
            # 按 domain 记录术语命中率分布（需求 6：可观测）
            m.term_hit_rate.labels(domain=domain).observe(term_hit_rate)
            # 真实发生主后端失败时计数（+1）
            if self._fallback.last_error is not None:
                m.translation_errors_total.labels(
                    backend=self._fallback.primary.name, reason="backend_failure"
                ).inc()
        except Exception:  # noqa: BLE001
            pass
        return resp

    def translate(self, req: TranslateRequest) -> TranslateResponse:
        return self._translate_core(
            req.text, req.domain, req.source_lang, req.target_lang, req.use_term_injection,
        )

    def batch_translate(self, req: BatchTranslateRequest) -> BatchTranslateResponse:
        job = TranslationJob(
            title=req.job_title, domain=req.domain, status="pending",
            model_ver=self.translator.name, total=len(req.texts),
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)

        terms = self.detect_terms(" ".join(req.texts), req.domain) if req.use_term_injection else []
        out_path = _batch_data_dir() / f"batch_{job.id}.jsonl"
        count = 0
        with open(out_path, "w", encoding="utf-8") as f:
            for text in req.texts:
                resp = self._translate_core(
                    text, req.domain, req.source_lang, req.target_lang,
                    req.use_term_injection, preloaded_terms=terms,
                )
                f.write(json.dumps({
                    "src": text, "translated": resp.translated,
                    "term_hit_rate": resp.term_hit_rate,
                }, ensure_ascii=False) + "\n")
                count += 1
        job.processed = count
        job.status = "completed"
        job.finished_at = datetime.utcnow()
        job.result_path = str(out_path)
        self.db.commit()
        return BatchTranslateResponse(job_id=job.id, status=job.status, total=job.total)

    def translate_document(
        self, text: str, domain: str, source_lang: str = "en", target_lang: str = "zh",
        use_term_injection: bool = True,
    ) -> dict:
        # 全局术语锁定：整篇仅加载一次术语
        terms = self.load_terms(domain) if use_term_injection else []
        sentences = _SENT_SPLIT.split(text)
        parts: list[str] = []
        for s in sentences:
            if s.strip():
                resp = self._translate_core(
                    s, domain, source_lang, target_lang, use_term_injection,
                    preloaded_terms=terms,
                )
                parts.append(resp.translated)
            else:
                parts.append(s)
        return {
            "translated": " ".join(parts),
            "segments": len([s for s in sentences if s.strip()]),
            "domain": domain,
        }
