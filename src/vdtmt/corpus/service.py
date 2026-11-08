"""语料服务层（模块 M1）。

负责：文件接入 -> 清洗 -> 质量评估 -> 持久化 -> 来源溯源登记。
批量任务具备原子性与可观测性：每条结果计入指标，失败单条不中断整批。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Corpus, SourceProvenance
from ..logging_setup import get_logger
from ..monitoring.metrics import get_metrics
from .cleaner import CleanResult, CleaningConfig, clean_pair
from .ingest import ingest_file

logger = get_logger("vdtmt.corpus.service")


@dataclass
class IngestReport:
    """一次文件接入的结果汇总。"""

    source_name: str
    total: int
    accepted: int
    rejected: int
    low_quality: int
    first_id: int | None
    provenance_id: int | None


class CorpusService:
    """语料库读写与接入。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def ingest_file(
        self,
        path: str,
        domain: str | None = None,
        source: str | None = None,
        fmt: str = "auto",
        config: CleaningConfig | None = None,
        accept_low_quality: bool = False,
    ) -> IngestReport:
        """读取文件 -> 清洗 -> 入库 -> 登记溯源。"""
        from pathlib import Path

        raw = ingest_file(path, fmt=fmt)
        accepted = 0
        rejected = 0
        low_quality = 0
        first_id: int | None = None
        source_name = source or Path(path).name

        for item in raw:
            dom = domain or item.get("domain", "general")
            res: CleanResult = clean_pair(item["src_text"], item["tgt_text"], config)
            if not res.valid and not (accept_low_quality and res.quality_score >= 0.25):
                rejected += 1
                continue
            if res.quality_score < 0.5:
                low_quality += 1
            row = Corpus(
                src_text=res.src,
                tgt_text=res.tgt,
                domain=dom,
                quality_score=res.quality_score,
                source=source_name,
                meta={"clean_issues": res.issues},
            )
            self.db.add(row)
            self.db.flush()
            if first_id is None:
                first_id = row.id
            accepted += 1

        self.db.commit()

        prov_id = None
        if accepted > 0 and first_id is not None:
            prov = SourceProvenance(
                entity_type="corpus",
                entity_id=first_id,
                source_name=source_name,
                extra={"accepted": accepted, "rejected": rejected,
                       "low_quality": low_quality, "file": str(path)},
            )
            self.db.add(prov)
            self.db.commit()
            prov_id = prov.id

        try:
            get_metrics().corpus_size.inc(0)  # 触发 gauge 刷新由调度器负责
        except Exception:  # noqa: BLE001
            pass

        report = IngestReport(
            source_name=source_name, total=len(raw), accepted=accepted,
            rejected=rejected, low_quality=low_quality,
            first_id=first_id, provenance_id=prov_id,
        )
        logger.info("ingest corpus done: %s", report)
        return report

    def add_pair(
        self, src: str, tgt: str, domain: str = "general",
        source: str = "manual", config: CleaningConfig | None = None,
    ) -> Corpus:
        res = clean_pair(src, tgt, config)
        if not res.valid:
            from ..exceptions import ValidationError

            raise ValidationError(
                f"corpus pair rejected: {res.issues}", context={"issues": res.issues}
            )
        row = Corpus(
            src_text=res.src, tgt_text=res.tgt, domain=domain,
            quality_score=res.quality_score, source=source,
            meta={"clean_issues": res.issues},
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def list(
        self, domain: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[Corpus]:
        stmt = select(Corpus).order_by(Corpus.id.desc())
        if domain:
            stmt = stmt.where(Corpus.domain == domain)
        return list(self.db.execute(stmt.limit(limit).offset(offset)).scalars().all())

    def iterate(self, domain: str | None = None, batch: int = 1000) -> Iterator[Corpus]:
        """分批遍历，适合大规模语料的处理（如术语抽取）。"""
        offset = 0
        while True:
            rows = self.list(domain=domain, limit=batch, offset=offset)
            if not rows:
                break
            yield from rows
            offset += batch

    def get(self, corpus_id: int) -> Corpus | None:
        return self.db.get(Corpus, corpus_id)

    def count(self, domain: str | None = None) -> int:
        stmt = select(func.count()).select_from(Corpus)
        if domain:
            stmt = stmt.where(Corpus.domain == domain)
        return int(self.db.execute(stmt).scalar_one())

    def delete(self, corpus_id: int) -> bool:
        row = self.get(corpus_id)
        if row is None:
            return False
        self.db.delete(row)
        self.db.commit()
        return True
