"""术语库与术语网络服务层（模块 M2）。

职责：
- 术语 CRUD（按 literal+domain 幂等 upsert，避免重复）
- 术语网络：同义/上下位/共现等边（TermRelation），支持来源溯源
- 抽取落库：基于语料抽取候选术语并入库（source=extracted）
- 网络建议：由语料共现与同译文自动建议关系，降低人工建网成本
"""

from __future__ import annotations

from collections import defaultdict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..corpus.service import CorpusService
from ..db.models import Corpus, Term, TermRelation
from ..exceptions import ConflictError, NotFoundError, ValidationError, VdtmtError, ErrorCode
from ..logging_setup import get_logger
from .extractor import TermExtractor
from .search import search_terms

logger = get_logger("vdtmt.terminology.service")

REL_TYPES = ("synonym", "antonym", "disambiguation", "hypernym", "cooccurrence")


class TermService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ---------- CRUD ----------
    def add_term(
        self, literal: str, target: str, domain: str = "general",
        confidence: float = 1.0, source: str = "manual", enabled: bool = True,
    ) -> Term:
        existing = self._find(literal, domain)
        if existing is not None:
            # 幂等更新：保留更高置信度
            existing.target = target
            existing.source = source
            existing.confidence = max(existing.confidence, confidence)
            existing.enabled = enabled
            self.db.commit()
            self.db.refresh(existing)
            return existing
        row = Term(
            literal=literal, target=target, domain=domain,
            confidence=confidence, source=source, enabled=enabled,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def bulk_add(self, terms: list[dict], source: str = "manual") -> int:
        n = 0
        for t in terms:
            self.add_term(
                t["literal"], t["target"], t.get("domain", "general"),
                float(t.get("confidence", 1.0)), source,
            )
            n += 1
        return n

    def _find(self, literal: str, domain: str) -> Term | None:
        stmt = select(Term).where(
            func.lower(Term.literal) == literal.lower(), Term.domain == domain
        )
        return self.db.execute(stmt).scalars().first()

    def get(self, term_id: int) -> Term | None:
        return self.db.get(Term, term_id)

    def list(
        self, domain: str | None = None, enabled: bool | None = None,
        limit: int = 200, offset: int = 0,
    ) -> list[Term]:
        stmt = select(Term).order_by(Term.id.desc())
        if domain:
            stmt = stmt.where(Term.domain == domain)
        if enabled is not None:
            stmt = stmt.where(Term.enabled.is_(enabled))
        return list(self.db.execute(stmt.limit(limit).offset(offset)).scalars().all())

    def update(self, term_id: int, **fields) -> Term:
        row = self.get(term_id)
        if row is None:
            raise NotFoundError(f"term not found: {term_id}")
        for k, v in fields.items():
            if k in ("literal", "target", "domain", "confidence", "enabled", "source"):
                setattr(row, k, v)
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete(self, term_id: int) -> bool:
        row = self.get(term_id)
        if row is None:
            return False
        self.db.delete(row)
        self.db.commit()
        return True

    def count(self, domain: str | None = None) -> int:
        stmt = select(func.count()).select_from(Term)
        if domain:
            stmt = stmt.where(Term.domain == domain)
        return int(self.db.execute(stmt).scalar_one())

    # ---------- 检索 ----------
    def search(self, query: str, domain: str | None = None, limit: int = 50) -> list[Term]:
        # ES "伪支持"改为 fail-loud：开启 use_elasticsearch 即明确报错，而非静默走 DB
        if self._settings().use_elasticsearch:
            raise VdtmtError(
                "Elasticsearch-based term search is not implemented in this build. "
                "Set USE_ELASTICSEARCH=false to use the default database-backed search.",
                code=ErrorCode.ELASTICSEARCH_NOT_IMPLEMENTED,
                http_status=501,
                context={"feature": "elasticsearch", "query": query, "domain": domain},
            )
        return search_terms(self.db, query, domain, limit)

    @staticmethod
    def _settings():
        from ..config import get_settings

        return get_settings()

    # ---------- 冲突治理（需求 1）----------
    def find_conflicts(self, domain: str | None = None) -> list[dict]:
        """找出同一 literal(+domain) 下的术语冲突。

        判定：按 ``(literal 忽略大小写, domain)`` 分组后，
        - target 去重后 > 1（同字面多译文），或
        - source 不一致（同字面同译文但来源不同）
        即视为冲突。返回冲突列表，每项为
        ``{literal, domain, candidates:[{target, source, confidence, count}]}``。
        """
        from sqlalchemy import select

        stmt = select(Term)
        if domain:
            stmt = stmt.where(Term.domain == domain)
        rows = list(self.db.execute(stmt).scalars().all())

        groups: dict[tuple[str, str], list[Term]] = defaultdict(list)
        for t in rows:
            groups[(t.literal.lower(), t.domain)].append(t)

        conflicts: list[dict] = []
        for (lit, dom), group in groups.items():
            if len(group) < 2:
                continue
            # 按 (target, source) 去重，聚合 count
            cand_map: dict[tuple[str, str], dict] = {}
            for t in group:
                key = (t.target, t.source)
                if key not in cand_map:
                    cand_map[key] = {
                        "target": t.target,
                        "source": t.source,
                        "confidence": t.confidence,
                        "count": 0,
                    }
                cand_map[key]["count"] += 1
            candidates = list(cand_map.values())
            distinct_targets = {c["target"] for c in candidates}
            distinct_sources = {c["source"] for c in candidates}
            if len(distinct_targets) > 1 or len(distinct_sources) > 1:
                conflicts.append({
                    "literal": lit,
                    "domain": dom,
                    "candidates": candidates,
                })
        return conflicts

    # ---------- 术语网络 ----------
    def add_relation(
        self, source_literal: str, target_literal: str, relation_type: str = "synonym",
        weight: float = 1.0, domain: str = "general", evidence: str = "",
    ) -> TermRelation:
        if relation_type not in REL_TYPES:
            raise ValidationError(
                f"invalid relation_type: {relation_type}", context={"allowed": REL_TYPES}
            )
        s = self._find(source_literal, domain)
        t = self._find(target_literal, domain)
        if s is None or t is None:
            raise NotFoundError("both terms must exist in domain before linking")
        if s.id == t.id:
            raise ConflictError("cannot relate a term to itself")
        # 幂等：重复关系更新权重
        existing = self.db.execute(
            select(TermRelation).where(
                TermRelation.source_term_id == s.id,
                TermRelation.target_term_id == t.id,
                TermRelation.relation_type == relation_type,
                TermRelation.domain == domain,
            )
        ).scalars().first()
        if existing is not None:
            existing.weight = weight
            existing.evidence = evidence
            self.db.commit()
            return existing
        rel = TermRelation(
            source_term_id=s.id, target_term_id=t.id, relation_type=relation_type,
            weight=weight, domain=domain, evidence=evidence,
        )
        self.db.add(rel)
        self.db.commit()
        self.db.refresh(rel)
        return rel

    def relations_of(self, term_id: int) -> list[TermRelation]:
        stmt = select(TermRelation).where(TermRelation.source_term_id == term_id)
        return list(self.db.execute(stmt).scalars().all())

    def relation_to_dict(self, rel: TermRelation) -> dict:
        """将关系解析为含字面量的人类可读字典。"""
        s = self.get(rel.source_term_id)
        t = self.get(rel.target_term_id)
        return {
            "id": rel.id,
            "relation_type": rel.relation_type,
            "weight": rel.weight,
            "domain": rel.domain,
            "evidence": rel.evidence,
            "source_literal": s.literal if s else None,
            "target_literal": t.literal if t else None,
        }

    def suggest_network(self, domain: str = "general") -> list[TermRelation]:
        """由语料自动建议术语关系（同译文=同义；同句共现=共现）。"""
        created: list[TermRelation] = []
        terms = self.list(domain=domain, enabled=True, limit=5000)
        by_target: dict[str, list[Term]] = defaultdict(list)
        for t in terms:
            by_target[t.target].append(t)
        # 同译文 -> 同义
        for target, group in by_target.items():
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    created.append(self.add_relation(
                        group[i].literal, group[j].literal, "synonym",
                        weight=1.0, domain=domain, evidence=f"shared_target:{target}",
                    ))

        # 同句共现 -> cooccurrence
        corpus = CorpusService(self.db)
        pair_limit = 2000
        cooc: dict[frozenset[int], int] = defaultdict(int)
        count = 0
        for row in corpus.iterate(domain=domain, batch=1000):
            ids_in = [t.id for t in terms if t.literal.lower() in row.src_text.lower()]
            for i in range(len(ids_in)):
                for j in range(i + 1, len(ids_in)):
                    cooc[frozenset((ids_in[i], ids_in[j]))] += 1
            count += 1
            if count >= pair_limit:
                break
        for pair, c in cooc.items():
            if c < 2:
                continue
            a, b = sorted(pair)
            ta = self.get(a)
            tb = self.get(b)
            if ta and tb:
                created.append(self.add_relation(
                    ta.literal, tb.literal, "cooccurrence",
                    weight=round(min(c / 10.0, 1.0), 3), domain=domain,
                    evidence=f"cooccur_in_corpus={c}",
                ))
        logger.info("suggest_network created %d relations for domain=%s", len(created), domain)
        return created

    # ---------- 抽取落库 ----------
    def extract_and_store(
        self, domain: str = "general", min_conf: float = 0.7, max_terms: int = 500
    ) -> list[Term]:
        corpus = CorpusService(self.db)
        pairs = [
            (r.src_text, r.tgt_text)
            for r in corpus.iterate(domain=domain, batch=2000)
        ]
        extractor = TermExtractor(min_freq=2, consistency=0.7)
        candidates = extractor.extract(pairs, domain=domain)
        stored: list[Term] = []
        for cand in candidates:
            if cand.confidence < min_conf:
                continue
            if self._find(cand.literal, domain) is not None:
                continue  # 不覆盖已有术语
            row = Term(
                literal=cand.literal, target=cand.target, domain=domain,
                confidence=cand.confidence, source="extracted", enabled=True,
            )
            self.db.add(row)
            stored.append(row)
            if len(stored) >= max_terms:
                break
        self.db.commit()
        for r in stored:
            self.db.refresh(r)
        logger.info("extract_and_store stored %d extracted terms", len(stored))
        return stored
