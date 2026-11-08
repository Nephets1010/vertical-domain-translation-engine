"""翻译服务层（模块 M4）。

- 术语约束注入翻译：检测源文术语 -> 占位注入 -> 翻译 -> 强制还原。
- 单条 / 批量 / 文档（分块 + 全局术语锁定）三种入口。
- 术语命中率与低置信度告警在翻译阶段即产出，供质量风险引擎（Phase 5）使用。
"""

from __future__ import annotations

import json
import re
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
from .injection import count_preserved, inject_terms, restore_terms
from .translators import get_translator

logger = get_logger("vdtmt.translation.service")

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


class TranslationService:
    def __init__(self, db: Session, translator=None) -> None:
        self.db = db
        self.settings = get_settings()
        self.translator = translator or get_translator(self.settings)

    def load_terms(self, domain: str) -> list[Term]:
        stmt = select(Term).where(Term.domain == domain, Term.enabled.is_(True))
        return list(self.db.execute(stmt).scalars().all())

    def detect_terms(self, src: str, domain: str) -> list[Term]:
        low = src.lower()
        return [t for t in self.load_terms(domain) if t.literal.lower() in low]

    def _translate_core(
        self, src: str, domain: str, source_lang: str, target_lang: str,
        use_term_injection: bool, preloaded_terms: list[Term] | None = None,
    ) -> TranslateResponse:
        terms = preloaded_terms if preloaded_terms is not None else self.detect_terms(src, domain)
        warnings: list[str] = []
        if use_term_injection and terms and self.settings.term_injection_enabled:
            inj = inject_terms(src, [(t.literal, t.target) for t in terms])
            raw = self.translator.translate(inj.injected, source_lang, target_lang)
            preserved = count_preserved(raw, inj.placeholders)
            translated = restore_terms(raw, inj.placeholders)
            hit = preserved  # 后端保留的占位符数 = 成功约束的术语数
        else:
            translated = self.translator.translate(src, source_lang, target_lang)
            preserved = 0
            hit = 0

        total = len(terms)
        term_hit_rate = (hit / total) if total else (1.0 if not total else 0.0)
        for t in terms:
            if t.confidence < self.settings.low_confidence_threshold:
                warnings.append(f"low_confidence_term:{t.literal}")

        resp = TranslateResponse(
            translated=translated, domain=domain, backend=self.translator.name,
            term_hits=[TermHit(literal=t.literal, target=t.target, matched=True) for t in terms],
            term_hit_rate=term_hit_rate, comet_score=None, risk_score=0.0,
            warnings=warnings,
        )
        try:
            m = get_metrics()
            m.translation_requests.labels(domain=domain, backend=self.translator.name, status="ok").inc()
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
        out_path = f"./data/batch_{job.id}.jsonl"
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
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
        job.result_path = out_path
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
