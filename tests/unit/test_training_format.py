"""训练数据格式化单元测试（无 DB 依赖）。"""

from __future__ import annotations

from vdtmt.training.format import detect_term_hints, format_pair


def test_format_pair_without_hints():
    rec = format_pair("The board approved the plan.", "董事会批准了该计划。", "legal")
    assert rec["src"] == "The board approved the plan."
    assert rec["tgt"] == "董事会批准了该计划。"
    assert rec["term_hints"] == []
    assert rec["messages"][0]["role"] == "system"
    assert rec["messages"][1]["role"] == "user"
    assert "[TERMS]" not in rec["messages"][1]["content"]


def test_format_pair_with_hints():
    hints = [{"literal": "merger agreement", "target": "并购协议"}]
    rec = format_pair(
        "We signed the merger agreement.", "我们签署了并购协议。",
        "legal", term_hints=hints,
    )
    assert rec["term_hints"] == hints
    assert "[TERMS]" in rec["messages"][1]["content"]
    assert "merger agreement->并购协议" in rec["messages"][1]["content"]


def test_detect_term_hints_substring():
    class _T:
        def __init__(self, lit, tgt):
            self.literal = lit
            self.target = tgt

    terms = [_T("merger agreement", "并购协议"), _T("warrant", "认股权证")]
    hints = detect_term_hints("The merger agreement was signed.", terms)
    assert hints == [{"literal": "merger agreement", "target": "并购协议"}]
