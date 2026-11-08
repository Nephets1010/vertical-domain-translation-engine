"""术语检索（模块 M2）。

默认基于数据库 ``LIKE`` 子串匹配（PostgreSQL/SQLite 通用）。
若开启 ``use_elasticsearch``，可切换至 ES 适配层（见 ``ElasticTermSearch`` 占位实现），
生产环境用 pg_trgm 或 ES 做模糊/向量检索。检索本身不抛异常：空查询返回空列表。
"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db.models import Term
from ..logging_setup import get_logger

logger = get_logger("vdtmt.terminology.search")


def search_terms(
    db: Session, query: str, domain: str | None = None, limit: int = 50
) -> list[Term]:
    """按字面或译文子串检索术语（大小写不敏感）。"""
    if not query or not query.strip():
        return []
    q = query.strip().lower()
    stmt = select(Term).where(Term.enabled.is_(True))
    if domain:
        stmt = stmt.where(Term.domain == domain)
    stmt = stmt.where(
        or_(
            func.lower(Term.literal).like(f"%{q}%"),
            func.lower(Term.target).like(f"%{q}%"),
        )
    )
    return list(db.execute(stmt.limit(limit)).scalars().all())


class ElasticTermSearch:
    """可选 ES 适配层（占位）。

    真实接入时在 ``__init__`` 中建立 Elasticsearch 客户端（凭据取自环境变量），
    ``index`` 与 ``search`` 实现布尔/模糊/向量混合检索。默认未启用，不阻断主流程。
    """

    def __init__(self, enabled: bool = False, url: str = "", index: str = "") -> None:
        self.enabled = enabled
        self.url = url
        self.index = index

    def available(self) -> bool:
        return self.enabled

    def search(self, query: str, domain: str | None = None, limit: int = 50) -> list[dict]:
        raise NotImplementedError(
            "Elasticsearch adapter not enabled; set use_elasticsearch=true and "
            "implement client in ElasticTermSearch.search."
        )
