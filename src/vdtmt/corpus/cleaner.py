"""语料清洗管线（模块 M1）。

企业级设计要点：
- 确定性、可复现：相同输入永远得到相同输出，便于回归测试与审计。
- 多维度质量评估：Unicode 归一化、HTML/控制符剥离、空白折叠、长度比校验、
  语言字符一致性、残留噪声检测，综合给出 0~1 质量分。
- 不抛异常吞数据：对单条脏数据返回 ``CleanResult.valid=False`` 与原因列表，
  由调用方决定丢弃或降级，保证批量任务不因单条坏数据中断。
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field

from ..logging_setup import get_logger

logger = get_logger("vdtmt.corpus.cleaner")

# 常见噪声模式
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_SPACE_RE = re.compile(r"\s+")
_ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_URL_RE = re.compile(r"https?://\S+")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# 语言字符集（粗略判定）
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_LATIN_RE = re.compile(r"[A-Za-z]")


@dataclass
class CleaningConfig:
    """清洗与质量评估阈值。可在配置层覆盖。"""

    strip_html: bool = True
    normalize_unicode: bool = True
    fold_whitespace: bool = True
    remove_urls: bool = False
    remove_emails: bool = False
    min_src_len: int = 1
    min_tgt_len: int = 1
    max_src_len: int = 8000
    max_tgt_len: int = 8000
    min_length_ratio: float = 0.05
    max_length_ratio: float = 6.0
    # 长度比合理平台区（en->zh 字符比常见区间），区间外线性衰减
    ideal_ratio_lo: float = 0.2
    ideal_ratio_hi: float = 2.5
    # 质量分中各项权重
    w_length_ratio: float = 0.30
    w_noise_free: float = 0.25
    w_char_consistency: float = 0.25
    w_balanced_punct: float = 0.20


@dataclass
class CleanResult:
    """单条清洗结果。"""

    src: str
    tgt: str
    quality_score: float
    valid: bool
    issues: list[str] = field(default_factory=list)


def normalize_text(text: str, config: CleaningConfig) -> tuple[str, list[str]]:
    """基础文本归一化，返回 (清洗后文本, 发现的问题)。"""
    issues: list[str] = []
    if config.normalize_unicode:
        text = unicodedata.normalize("NFKC", text)
    text = _ZERO_WIDTH_RE.sub("", text)
    if config.strip_html and _HTML_TAG_RE.search(text):
        issues.append("html_tags_stripped")
        text = _HTML_TAG_RE.sub("", text)
        text = html.unescape(text)
    if config.remove_urls and _URL_RE.search(text):
        issues.append("url_removed")
        text = _URL_RE.sub("", text)
    if config.remove_emails and _EMAIL_RE.search(text):
        issues.append("email_removed")
        text = _EMAIL_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    if config.fold_whitespace:
        text = _MULTI_SPACE_RE.sub(" ", text).strip()
    return text, issues


def _char_consistency(src: str, tgt: str) -> float:
    """字符集一致性（粗略）：源拉丁/目标 CJK 为合理；两者皆拉丁=未翻译。"""

    def ratios(s: str) -> tuple[float, float]:
        n = max(len(s), 1)
        return (len(_LATIN_RE.findall(s)) / n, len(_CJK_RE.findall(s)) / n)

    s_lat, s_cjk = ratios(src)
    t_lat, t_cjk = ratios(tgt)
    # 源、目标都以拉丁为主 -> 高度疑似未翻译
    if s_lat > 0.5 and t_lat > 0.5:
        return 0.0
    # 源拉丁为主、目标几乎无 CJK（漏译/未译）
    if s_lat > 0.5 and t_cjk < 0.1 and t_lat > 0.3:
        return 0.2
    # 源含大量 CJK 但期望源为拉丁（翻译方向可能反了）
    if s_cjk > 0.4 and s_lat < 0.3:
        return 0.5
    return 1.0


def _balanced_punct(src: str, tgt: str) -> float:
    """标点平衡：目标不应显著缺失或多余成对标点。"""
    pairs = [("(", ")"), ("（", "）"), ('"', '"'), ("“", "”")]
    penalty = 0.0
    for a, b in pairs:
        sa, sb = src.count(a), src.count(b)
        ta, tb = tgt.count(a), tgt.count(b)
        if (sa > 0) != (ta > 0) or (sb > 0) != (tb > 0):
            penalty += 0.05
    return max(0.0, 1.0 - penalty)


def score_quality(src: str, tgt: str, config: CleaningConfig) -> tuple[float, list[str]]:
    """综合质量评分 0~1，并返回扣分项说明。"""
    issues: list[str] = []
    # 长度比：合理平台区得满分，平台外线性衰减至 [min,max] 边界归零
    ratio = (len(tgt) / len(src)) if len(src) > 0 else 0.0
    if config.ideal_ratio_lo <= ratio <= config.ideal_ratio_hi:
        length_score = 1.0
    elif ratio < config.ideal_ratio_lo:
        span = max(config.ideal_ratio_lo - config.min_length_ratio, 1e-6)
        length_score = max(0.0, (ratio - config.min_length_ratio) / span)
    else:
        span = max(config.max_length_ratio - config.ideal_ratio_hi, 1e-6)
        length_score = max(0.0, (config.max_length_ratio - ratio) / span)
    if not (config.min_length_ratio <= ratio <= config.max_length_ratio):
        issues.append(
            f"length_ratio_out_of_range:{ratio:.2f} "
            f"outside [{config.min_length_ratio},{config.max_length_ratio}]"
        )

    noise_free_score = 1.0
    if _CONTROL_RE.search(src) or _CONTROL_RE.search(tgt):
        noise_free_score -= 0.5
        issues.append("residual_control_chars")
    if config.strip_html and (_HTML_TAG_RE.search(src) or _HTML_TAG_RE.search(tgt)):
        noise_free_score -= 0.3
        issues.append("residual_html_tags")

    char_score = _char_consistency(src, tgt)
    if char_score < 1.0:
        issues.append("char_consistency_warning")

    punct_score = _balanced_punct(src, tgt)
    if punct_score < 1.0:
        issues.append("punctuation_imbalance")

    score = (
        config.w_length_ratio * length_score
        + config.w_noise_free * noise_free_score
        + config.w_char_consistency * char_score
        + config.w_balanced_punct * punct_score
    )
    return max(0.0, min(1.0, score)), issues


def clean_pair(
    src: str, tgt: str, config: CleaningConfig | None = None
) -> CleanResult:
    """清洗并评估一条平行句对。

    不抛异常：遇到空/超长/不可清洗的情况返回 ``valid=False``。
    """
    config = config or CleaningConfig()
    issues: list[str] = []
    valid = True

    if not isinstance(src, str) or not isinstance(tgt, str):
        return CleanResult(src="", tgt="", quality_score=0.0, valid=False,
                           issues=["non_string_input"])

    src, i1 = normalize_text(src, config)
    tgt, i2 = normalize_text(tgt, config)
    issues.extend(i1)
    issues.extend(i2)

    # 源与目标完全相同（归一化后）：几乎必然未翻译，直接判无效
    if src and src == tgt:
        issues.append("identical_src_tgt")
        return CleanResult(src=src, tgt=tgt, quality_score=0.0, valid=False, issues=issues)

    if len(src) < config.min_src_len or len(tgt) < config.min_tgt_len:
        issues.append("too_short")
        valid = False
    if len(src) > config.max_src_len or len(tgt) > config.max_tgt_len:
        issues.append("too_long")
        valid = False

    quality, q_issues = score_quality(src, tgt, config)
    issues.extend(q_issues)
    # 字符一致性为 0（源与目标同属拉丁语系，几乎必然未翻译）-> 硬失效
    char_score = _char_consistency(src, tgt)
    if char_score == 0.0:
        issues.append("untranslated_same_script")
        valid = False
    elif char_score < 1.0:
        issues.append("char_consistency_warning")
    # 质量过低也视为不可直接入库，但保留结果供人工校核
    if quality < 0.25:
        issues.append("low_quality")
        valid = False

    return CleanResult(src=src, tgt=tgt, quality_score=quality, valid=valid, issues=issues)


def clean_pairs(items, config: CleaningConfig | None = None):
    """批量清洗。``items`` 为 (src, tgt) 可迭代。返回生成器。"""
    config = config or CleaningConfig()
    for src, tgt in items:
        yield clean_pair(src, tgt, config)
