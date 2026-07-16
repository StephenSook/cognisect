"""Independent semantic oracle for tests only.

This module intentionally does not import the production interpreter and does not
share a template-to-function mapping with it.
"""

from __future__ import annotations

from typing import Literal

OracleTemplateId = Literal[
    "add_subtrahend",
    "ignore_subtrahend_sign",
    "absolute_difference",
    "subtract_magnitudes",
    "keep_minuend_sign",
    "negative_magnitude_sum",
]


def oracle_result(template_id: OracleTemplateId, a: int, b: int) -> int:
    """Evaluate one registry rule independently of production code."""
    if template_id == "add_subtrahend":
        return a + b
    if template_id == "ignore_subtrahend_sign":
        return a - abs(b)
    if template_id == "absolute_difference":
        return abs(abs(a) - abs(b))
    if template_id == "subtract_magnitudes":
        return abs(a) - abs(b)
    if template_id == "keep_minuend_sign":
        sign = -1 if a < 0 else 1
        return sign * abs(abs(a) - abs(b))
    if template_id == "negative_magnitude_sum":
        return -(abs(a) + abs(b))
    raise AssertionError(template_id)
