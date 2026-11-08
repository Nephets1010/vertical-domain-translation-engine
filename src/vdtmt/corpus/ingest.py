"""多源语料接入（模块 M1）。

支持来源：
- JSONL 平行语料（每行 ``{"src_text","tgt_text","domain","source"}``）
- TSV/CSV 平行语料（两列：源/目标）
- 术语 CSV（``literal,target,domain,...``）-> 转术语条目，供 terminology 模块消费
- 网页/纯文本（best-effort，需联网；失败抛 ``UnavailableError`` 而非静默）

所有读取均带超时与异常隔离，避免单源故障拖垮批量任务。
"""

from __future__ import annotations

import csv
import json
import urllib.request
from pathlib import Path

from ..exceptions import NotFoundError, UnavailableError, ValidationError
from ..logging_setup import get_logger

logger = get_logger("vdtmt.corpus.ingest")

_SUPPORTED_TEXT_EXT = {".txt", ".jsonl", ".json", ".tsv", ".csv", ".tmx"}


def _detect_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".jsonl", ".json"):
        return "jsonl"
    if suffix == ".tsv":
        return "tsv"
    if suffix == ".csv":
        return "csv"
    if suffix == ".tmx":
        return "tmx"
    if suffix == ".txt":
        return "txt"
    return "auto"


def read_jsonl(path: str | Path) -> list[dict]:
    """读取 JSONL 平行语料，返回标准化字典列表。"""
    p = Path(path)
    if not p.exists():
        raise NotFoundError(f"corpus file not found: {p}")
    out: list[dict] = []
    with p.open("r", encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("skip invalid jsonl line %d: %s", ln, exc)
                continue
            src = obj.get("src_text") or obj.get("source") or obj.get("src") or ""
            tgt = obj.get("tgt_text") or obj.get("target") or obj.get("tgt") or ""
            if not src or not tgt:
                continue
            out.append({
                "src_text": str(src),
                "tgt_text": str(tgt),
                "domain": obj.get("domain", "general"),
                "source": obj.get("source", p.name),
            })
    return out


def read_tsv(path: str | Path, delimiter: str = "\t") -> list[dict]:
    """读取 TSV/CSV 平行语料（无表头或含表头）。"""
    p = Path(path)
    if not p.exists():
        raise NotFoundError(f"corpus file not found: {p}")
    out: list[dict] = []
    with p.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        for row in reader:
            if len(row) < 2:
                continue
            # 跳过表头
            if row[0].lower() in ("src_text", "source", "src", "源文", "原文"):
                continue
            out.append({
                "src_text": row[0].strip(),
                "tgt_text": row[1].strip(),
                "domain": row[2].strip() if len(row) > 2 else "general",
                "source": p.name,
            })
    return out


def read_csv_terms(path: str | Path) -> list[dict]:
    """读取术语 CSV（literal,target,domain,confidence,source）。"""
    p = Path(path)
    if not p.exists():
        raise NotFoundError(f"term file not found: {p}")
    out: list[dict] = []
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            literal = (row.get("literal") or "").strip()
            target = (row.get("target") or "").strip()
            if not literal or not target:
                continue
            out.append({
                "literal": literal,
                "target": target,
                "domain": (row.get("domain") or "general").strip(),
                "confidence": float(row.get("confidence") or 1.0),
                "source": (row.get("source") or p.name).strip(),
            })
    return out


def parse_tmx(path: str | Path) -> list[dict]:
    """解析 TMX 翻译记忆交换文件（best-effort，仅取 en/zh 句对）。"""
    p = Path(path)
    if not p.exists():
        raise NotFoundError(f"tmx file not found: {p}")
    import xml.etree.ElementTree as ET

    try:
        tree = ET.parse(p)
    except ET.ParseError as exc:
        raise ValidationError(f"invalid tmx xml: {exc}")
    root = tree.getroot()
    out: list[dict] = []
    for tu in root.iter("tu"):
        texts: dict[str, str] = {}
        for tuv in tu.iter("tuv"):
            lang = tuv.get("xml:lang") or tuv.get("lang") or ""
            lang = lang.lower()
            seg = tuv.find("seg")
            if seg is not None and seg.text:
                texts[lang] = seg.text.strip()
        if "en" in texts and "zh" in texts:
            out.append({
                "src_text": texts["en"], "tgt_text": texts["zh"],
                "domain": "general", "source": p.name,
            })
    return out


def fetch_web_text(url: str, timeout: float = 15.0) -> str:
    """抓取网页纯文本（best-effort）。网络/解析失败抛 ``UnavailableError``。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "VDT-MT/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:  # 网络层
        raise UnavailableError(f"fetch web failed: {exc}")
    # 简易去标签
    import re

    raw = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.I)
    raw = re.sub(r"<style[\s\S]*?</style>", " ", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def ingest_file(path: str | Path, fmt: str = "auto") -> list[dict]:
    """统一入口：按格式读取为标准化语料字典列表。"""
    p = Path(path)
    fmt = fmt if fmt != "auto" else _detect_format(p)
    if fmt == "jsonl":
        return read_jsonl(p)
    if fmt == "tsv":
        return read_tsv(p, delimiter="\t")
    if fmt == "csv":
        return read_tsv(p, delimiter=",")
    if fmt == "tmx":
        return parse_tmx(p)
    if fmt == "txt":
        # 纯文本：按段落拆分，无法构成平行句对，返回空（提示用户用平行格式）
        logger.warning("txt has no parallel pairs; use jsonl/tsv for parallel corpus")
        return []
    raise ValidationError(f"unsupported corpus format: {fmt}")
