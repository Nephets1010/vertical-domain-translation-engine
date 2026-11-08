"""相似案例检索（重映射自"智能投研·相似案例"）。

给定一段文本或某条评估记录，检索历史上最相似的翻译/错误样本，支撑人工校核与根因分析。
相似度使用字符级 Jaccard（确定性、无外部依赖）。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import EvalRecord
from ..logging_setup import get_logger
from ..quality.evaluator import lexical_similarity
from ..schemas import SimilarCase

logger = get_logger("vdtmt.analytics.similar_cases")


def find_similar_cases(
    db: Session, snippet: str, top_k: int = 5, limit_scan: int = 5000,
) -> list[SimilarCase]:
    if not snippet or not snippet.strip():
        return []
    recs = db.execute(select(EvalRecord).limit(limit_scan)).scalars().all()
    scored: list[tuple[float, EvalRecord]] = []
    for r in recs:
        sim = max(
            lexical_similarity(snippet, r.src_text or ""),
            lexical_similarity(snippet, r.tgt_text or ""),
        )
        if sim > 0:
            scored.append((sim, r))
    scored.sort(key=lambda x: -x[0])
    return [
        SimilarCase(
            eval_id=r.id, error_type=r.error_type,
            snippet=(r.src_text or "")[:80], similarity=round(sim, 3),
        )
        for sim, r in scored[:top_k]
    ]


def find_similar_to_eval(
    db: Session, eval_id: int, top_k: int = 5
) -> list[SimilarCase]:
    rec = db.get(EvalRecord, eval_id)
    if rec is None:
        return []
    snippet = rec.src_text or rec.tgt_text or ""
    cases = find_similar_cases(db, snippet, top_k=top_k + 1)
    return [c for c in cases if c.eval_id != eval_id][:top_k]
