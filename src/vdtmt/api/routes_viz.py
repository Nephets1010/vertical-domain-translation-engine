"""可视化检索 API 与静态页面（术语网络图谱）。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.base import get_db
from ..db.models import Term, TermRelation

router = APIRouter(tags=["visualization"])

# 项目根目录下的 static/（兼容 src 布局与安装后布局）
_ROOT = Path(__file__).resolve().parents[3]
_STATIC = _ROOT / "static"


@router.get("/api/v1/viz/term-graph", response_model=dict)
def term_graph(
    domain: str = Query("general"),
    node_limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> dict:
    """返回术语网络图谱数据（节点=术语，边=关系）。"""
    terms = db.execute(
        select(Term).where(Term.domain == domain, Term.enabled.is_(True)).limit(node_limit)
    ).scalars().all()
    term_ids = {t.id for t in terms}
    nodes = [
        {
            "id": t.id, "label": t.literal, "target": t.target,
            "domain": t.domain, "confidence": t.confidence, "freq": t.freq,
        }
        for t in terms
    ]
    rels = db.execute(
        select(TermRelation).where(TermRelation.domain == domain)
    ).scalars().all()
    edges = [
        {
            "source": r.source_term_id, "target": r.target_term_id,
            "relation_type": r.relation_type, "weight": r.weight,
        }
        for r in rels
        if r.source_term_id in term_ids and r.target_term_id in term_ids
    ]
    return {"domain": domain, "nodes": nodes, "edges": edges}


@router.get("/viz", response_class=FileResponse)
def viz_page() -> FileResponse:
    """术语网络可视化检索页面（离线、无外部依赖）。"""
    html = _STATIC / "term_graph.html"
    if not html.exists():
        return JSONResponse({"error": "static page not found"}, status_code=404)
    return FileResponse(html)
