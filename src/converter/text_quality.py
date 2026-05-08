from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TextQualityResult:
    is_usable: bool
    reason: str
    non_ws_chars: int
    alpha_ratio: float
    single_char_line_ratio: float


def evaluate_text_quality(
    text: str,
    *,
    min_text_chars: int,
    min_alpha_ratio: float,
    max_single_char_line_ratio: float,
) -> TextQualityResult:
    non_ws_chars = len(re.findall(r"\S", text))
    if non_ws_chars == 0:
        return TextQualityResult(
            is_usable=False,
            reason="empty_text",
            non_ws_chars=0,
            alpha_ratio=0.0,
            single_char_line_ratio=1.0,
        )

    alpha_chars = len(re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", text))
    alpha_ratio = alpha_chars / non_ws_chars

    non_empty_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not non_empty_lines:
        single_char_line_ratio = 1.0
    else:
        single_char_lines = sum(1 for line in non_empty_lines if len(line) == 1)
        single_char_line_ratio = single_char_lines / len(non_empty_lines)

    is_low_value = (
        non_ws_chars < min_text_chars
        or alpha_ratio < min_alpha_ratio
        or single_char_line_ratio > max_single_char_line_ratio
    )
    reason = "usable_text" if not is_low_value else "low_quality_text"
    return TextQualityResult(
        is_usable=not is_low_value,
        reason=reason,
        non_ws_chars=non_ws_chars,
        alpha_ratio=alpha_ratio,
        single_char_line_ratio=single_char_line_ratio,
    )
