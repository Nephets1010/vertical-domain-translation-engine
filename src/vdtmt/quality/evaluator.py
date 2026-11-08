"""翻译质量评估（模块 M5）。

- COMET 为可选适配：``comet_enabled`` 且安装 ``unbabel-comet`` 时调用，否则回退到
  「词法近似打分」（基于参考译文/术语的字符级 Jaccard），保证离线可跑、可测试。
- 术语命中率由翻译阶段透传，这里仅做聚合与错误类型判定。
- 所有打分确定性、可复现。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import get_settings
from ..logging_setup import get_logger

logger = get_logger("vdtmt.quality.evaluator")


@dataclass
class EvalResult:
    comet_score: float | None
    term_hit_rate: float
    error_type: str
    risk_score: float
    warnings: list[str]


def lexical_similarity(a: str, b: str) -> float:
    """字符级 Jaccard 相似度（对中文译文近似有效，且确定性）。"""
    sa, sb = set(a or ""), set(b or "")
    union = sa | sb
    if not union:
        return 1.0
    return len(sa & sb) / len(union)


def _comet_available() -> bool:
    try:
        import comet  # noqa: F401
        return True
    except Exception:
        return False


class Evaluator:
    def __init__(self, settings=None) -> None:
        self.settings = settings or get_settings()

    def comet_score(self, src: str, tgt: str, ref: str | None = None) -> float | None:
        """返回 COMET 分（启用且可用时）或词法近似分。"""
        if self.settings.comet_enabled and _comet_available():
            try:
                from comet import download_model, load_from_checkpoint  # type: ignore

                model_path = download_model(self.settings.comet_model)
                model = load_from_checkpoint(model_path)
                data = [{"src": src, "mt": tgt, "ref": ref or tgt}]
                preds = model.predict(data, batch_size=1, gpus=0)
                return float(preds["scores"][0])
            except Exception as exc:  # 评估失败不应阻断翻译
                logger.warning("comet eval failed, fallback lexical: %s", exc)
        # 回退：若有参考译文，用词法近似；否则返回 None（由规则引擎跳过该维度）
        if ref:
            return lexical_similarity(tgt, ref)
        return None

    def evaluate(
        self, src: str, tgt: str, ref: str | None = None,
        term_hit_rate: float = 0.0, warnings: list[str] | None = None,
    ) -> EvalResult:
        cs = self.comet_score(src, tgt, ref)
        warnings = warnings or []
        # 错误类型判定（优先级）
        if term_hit_rate < 1.0:
            error_type = "term_miss"
        elif cs is not None and cs < self.settings.risk_comet_low:
            error_type = "low_quality"
        else:
            error_type = "none"
        risk_score = 0.0  # 由 RiskEngine 计算后回填（见 QualityService）
        return EvalResult(
            comet_score=cs, term_hit_rate=term_hit_rate,
            error_type=error_type, risk_score=risk_score, warnings=warnings,
        )
