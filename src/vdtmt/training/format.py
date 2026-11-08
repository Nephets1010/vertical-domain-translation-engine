"""训练数据格式化（模块 M3）。

将清洗后的平行语料 + 术语库格式化为指令微调（SFT）样本：
- 系统提示：声明垂直领域译员身份与"必须套用术语约束"的要求。
- 用户：源文（可附带命中的术语提示）。
- 助手：译文（作为监督目标）。
- 额外保留结构化字段（src/tgt/domain/term_hints）便于评估与回流。

纯函数 ``format_pair`` 不依赖数据库，完全可单测、可复现。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..db.models import Corpus, Term
from ..logging_setup import get_logger
from sqlalchemy import select

logger = get_logger("vdtmt.training.format")

SYSTEM_PROMPT = (
    "You are a professional vertical-domain translator. "
    "Translate the user's text accurately and consistently, "
    "and strictly use the provided terminology constraints when applicable."
)


def detect_term_hints(src: str, terms: list[Term]) -> list[dict]:
    """返回源文中命中的术语（字面->目标）。"""
    hints: list[dict] = []
    low = src.lower()
    for t in terms:
        if t.literal.lower() in low:
            hints.append({"literal": t.literal, "target": t.target})
    return hints


def format_pair(
    src: str, tgt: str, domain: str = "general",
    term_hints: list[dict] | None = None, source_lang: str = "en", target_lang: str = "zh",
) -> dict:
    """格式化为一条 SFT 样本（messages + 元数据）。"""
    hints = term_hints or []
    user_content = src
    if hints:
        hint_str = "; ".join(f"{h['literal']}->{h['target']}" for h in hints)
        user_content = f"[TERMS] {hint_str}\n{src}"
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Translate {source_lang} to {target_lang} ({domain} domain):\n{user_content}",
        },
        {"role": "assistant", "content": tgt},
    ]
    return {
        "messages": messages,
        "src": src,
        "tgt": tgt,
        "domain": domain,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "term_hints": hints,
    }


@dataclass
class DatasetReport:
    path: str
    count: int
    with_hints: int
    domain: str


def build_training_dataset(
    db, domain: str = "general", out_path: str | None = None,
    min_quality: float = 0.5, limit: int = 50000,
) -> DatasetReport:
    """从语料库构建 SFT 数据集并写入 JSONL。"""
    terms = list(
        db.execute(
            select(Term).where(Term.domain == domain, Term.enabled.is_(True))
        ).scalars().all()
    )
    stmt = select(Corpus).where(
        Corpus.domain == domain, Corpus.quality_score >= min_quality
    ).limit(limit)
    rows = db.execute(stmt).scalars().all()

    if out_path is None:
        out_path = f"./data/train_{domain}.jsonl"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with_hints = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for r in rows:
            hints = detect_term_hints(r.src_text, terms)
            rec = format_pair(r.src_text, r.tgt_text, domain, hints)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            count += 1
            if hints:
                with_hints += 1
    logger.info("training dataset built: %s (%d pairs, %d with hints)",
                out_path, count, with_hints)
    return DatasetReport(path=out_path, count=count, with_hints=with_hints, domain=domain)
