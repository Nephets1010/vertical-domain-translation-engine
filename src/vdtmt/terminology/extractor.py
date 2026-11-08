"""术语抽取（模块 M2）。

策略：基于平行语料的「源 n-gram 与目标 n-gram 共现一致性」启发式抽取候选术语。
- 源端：英文按词切分，取 1~N 元词组；过滤停用词。
- 目标端：中文按字取 2~M 元字串（覆盖如「并购协议」这类 4 字术语）。
- 对每条平行句对统计 (源词组, 目标字串) 共现；同一源词组在 >=min_freq 个句对中出现，
  且最常共现目标占比 >= consistency 时，判定为候选术语，置信度 = 一致占比。
- 确定性、可复现、可回归：不依赖外部模型，便于单测与审计。

局限（见 ADR-0004）：纯共现法对低频/长术语召回有限，真实生产应叠加对齐模型与词典；
本引擎以「提供的术语词典」为权威，抽取仅作补充与语料频率验证。
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from ..logging_setup import get_logger

logger = get_logger("vdtmt.terminology.extractor")

_STOPWORDS = {
    "a", "an", "the", "of", "to", "in", "on", "for", "and", "or", "is", "are",
    "was", "were", "be", "been", "being", "with", "by", "at", "that", "this",
    "it", "its", "their", "they", "as", "from", "may", "can", "will", "would",
    "has", "have", "had", "not", "no", "but", "if", "then", "than", "into",
    "such", "any", "all", "each", "both", "under", "over", "upon", "which",
}

_WORD_RE = re.compile(r"[a-z][a-z'+-]*")


@dataclass
class CandidateTerm:
    literal: str
    target: str
    domain: str
    freq: int
    confidence: float
    evidence: str


def _src_ngrams(text: str, max_n: int) -> list[str]:
    words = _WORD_RE.findall(text.lower())
    grams: list[str] = []
    for n in range(1, max_n + 1):
        for i in range(len(words) - n + 1):
            gram = " ".join(words[i : i + n])
            toks = gram.split()
            # 过滤：单停用词；或 n-gram 首尾为停用词（如 "the merger agreement"）
            if toks[0] in _STOPWORDS or toks[-1] in _STOPWORDS:
                continue
            grams.append(gram)
    return grams


def _tgt_ngrams(text: str, max_n: int) -> list[str]:
    # 中文按字取 n 元（2~max_n），同时保留整句便于匹配长短语
    chars = [c for c in text if c.strip()]
    grams: list[str] = []
    for n in range(2, max_n + 1):
        for i in range(len(chars) - n + 1):
            grams.append("".join(chars[i : i + n]))
    return grams


class TermExtractor:
    def __init__(
        self,
        src_max_n: int = 3,
        tgt_max_n: int = 4,
        min_freq: int = 2,
        consistency: float = 0.7,
    ) -> None:
        self.src_max_n = src_max_n
        self.tgt_max_n = tgt_max_n
        self.min_freq = min_freq
        self.consistency = consistency

    def extract(
        self, pairs: list[tuple[str, str]], domain: str = "general"
    ) -> list[CandidateTerm]:
        """从平行句对中抽取候选术语。"""
        cooc: dict[tuple[str, str], int] = defaultdict(int)
        src_total: dict[str, int] = defaultdict(int)

        for src, tgt in pairs:
            s_grams = set(_src_ngrams(src, self.src_max_n))
            t_grams = set(_tgt_ngrams(tgt, self.tgt_max_n))
            if not s_grams or not t_grams:
                continue
            for s in s_grams:
                src_total[s] += 1
                for t in t_grams:
                    cooc[(s, t)] += 1

        # 每个源词组选最佳目标：共现数高者优先；同票取更长目标（信息更完整）
        best: dict[str, tuple[str, int]] = {}
        for (s, t), c in cooc.items():
            if s not in best:
                best[s] = (t, c)
            else:
                cur_t, cur_c = best[s]
                if c > cur_c or (c == cur_c and len(t) > len(cur_t)):
                    best[s] = (t, c)

        candidates: list[CandidateTerm] = []
        for s, (t, c) in best.items():
            freq = src_total[s]
            if freq < self.min_freq:
                continue
            confidence = c / freq
            if confidence < self.consistency:
                continue
            if len(t) < 2:
                continue
            candidates.append(CandidateTerm(
                literal=s, target=t, domain=domain, freq=freq,
                confidence=round(confidence, 3),
                evidence=f"co_occurs={c}/{freq}",
            ))

        # 精炼：保留更具术语性的候选，剔除片段与冗余
        # 规则：
        # 1) 单 token 且目标长度>2 字 -> 多为片段（如单词映射到 4 字术语），丢弃；
        # 2) 若候选字面是已保留候选（同目标）的短语子串或其超串 -> 丢弃（保留更凝练者）。
        candidates.sort(
            key=lambda x: (len(x.literal.split()), -x.confidence, -len(x.target))
        )
        chosen: list[CandidateTerm] = []
        chosen_literals: list[str] = []
        for cand in candidates:
            if len(cand.literal.split()) == 1 and len(cand.target) > 2:
                continue
            redundant = False
            for kept in chosen_literals:
                if kept == cand.literal:
                    redundant = True
                    break
                if cand.domain == cand.domain and (
                    cand.literal in kept or kept in cand.literal
                ):
                    redundant = True
                    break
            if redundant:
                continue
            chosen.append(cand)
            chosen_literals.append(cand.literal)
        return chosen

    def score_dictionary(
        self, pairs: list[tuple[str, str]], dictionary: list[tuple[str, str]]
    ) -> list[CandidateTerm]:
        """用语料验证给定词典：返回每个词典术语在语料中的出现频次与一致性。"""
        out: list[CandidateTerm] = []
        for literal, target in dictionary:
            freq = 0
            match = 0
            for src, tgt in pairs:
                if literal.lower() in src.lower():
                    freq += 1
                    if target in tgt:
                        match += 1
            confidence = round(match / freq, 3) if freq else 0.0
            out.append(CandidateTerm(
                literal=literal, target=target, domain="general",
                freq=freq, confidence=confidence,
                evidence=f"corpus_freq={freq},target_match={match}",
            ))
        return out
