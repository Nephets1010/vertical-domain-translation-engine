"""示例数据灌库工具（离线，无需启动服务）。

用法：
    python -m vdtmt.tools.seed --corpus sample_data/corpus/en_zh_sample.jsonl \
        --terms sample_data/corpus/terms.csv

也可只灌其一。默认初始化库表（SQLite/PostgreSQL 通用）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..db.base import init_db, get_session_local
from ..corpus.ingest import read_csv_terms
from ..logging_setup import configure_logging, get_logger

logger = get_logger("vdtmt.tools.seed")


def seed(corpus_path: str | None, terms_path: str | None, domain: str | None) -> dict:
    init_db()
    db = get_session_local()()
    report: dict = {}
    try:
        if corpus_path:
            from ..corpus.service import CorpusService

            rep = CorpusService(db).ingest_file(corpus_path, domain=domain, fmt="auto")
            report["corpus"] = {
                "accepted": rep.accepted, "rejected": rep.rejected,
                "low_quality": rep.low_quality,
            }
        if terms_path:
            from ..terminology.service import TermService

            terms = read_csv_terms(terms_path)
            n = TermService(db).bulk_add(terms, source="sample")
            report["terms"] = n
    finally:
        db.close()
    return report


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="Seed VDT-MT with sample data")
    parser.add_argument("--corpus", default="sample_data/corpus/en_zh_sample.jsonl")
    parser.add_argument("--terms", default="sample_data/corpus/terms.csv")
    parser.add_argument("--domain", default=None)
    parser.add_argument("--no-default-paths", action="store_true",
                        help="若文件不存在则跳过而非报错")
    args = parser.parse_args(argv)

    paths = []
    for p in (args.corpus, args.terms):
        if p and Path(p).exists():
            paths.append(p)
        elif p and not args.no_default_paths:
            logger.warning("skip missing path: %s", p)

    report = seed(
        args.corpus if Path(args.corpus).exists() else None,
        args.terms if Path(args.terms).exists() else None,
        args.domain,
    )
    print("SEED_REPORT:", report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
