"""关联挖掘（重映射自"智能投研·关联挖掘"）。

基于语料中术语的共现，挖掘领域术语关联强度，支撑术语网络可视化与翻译一致性校验。
确定性、可复现，适合中小规模（<100 万）离线批算。
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from ..corpus.service import CorpusService
from ..db.models import Term
from ..logging_setup import get_logger
from ..schemas import AssociationItem
from ..terminology.service import TermService

logger = get_logger("vdtmt.analytics.association")


def mine_term_associations(
    db: Session, domain: str = "general", min_cooccur: int = 2, limit: int = 100,
) -> list[AssociationItem]:
    terms = TermService(db).list(domain=domain, enabled=True, limit=5000)
    name = {t.id: t.literal for t in terms}
    corpus = CorpusService(db)
    cooc: dict[frozenset[int], int] = defaultdict(int)
    for row in corpus.iterate(domain=domain, batch=2000):
        present = [t.id for t in terms if t.literal.lower() in row.src_text.lower()]
        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                cooc[frozenset((present[i], present[j]))] += 1

    items: list[AssociationItem] = []
    for pair, c in cooc.items():
        if c < min_cooccur:
            continue
        a, b = sorted(pair)
        items.append(AssociationItem(
            term_a=name[a], term_b=name[b], cooccur_count=c,
            strength=round(min(c / 10.0, 1.0), 3),
        ))
    items.sort(key=lambda x: -x.cooccur_count)
    return items[:limit]
