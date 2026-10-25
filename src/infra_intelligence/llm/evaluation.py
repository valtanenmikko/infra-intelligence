"""Evaluate LLM extractions against structured TED fields that were withheld from the model."""

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Metric:
    name: str
    value: float | None
    n: int
    description: str


def _ratio(hits: int, total: int) -> float | None:
    return hits / total if total else None


def region_metrics(pairs: Iterable[tuple[str | None, list[str]]]) -> list[Metric]:
    """pairs: (LLM region, TED NUTS regions). Only notices with exactly one TED region are scored, because the
    prompt asks for null when work spans several regions."""
    scored = [(pred, truth[0]) for pred, truth in pairs if len(truth) == 1]
    answered = [(p, t) for p, t in scored if p is not None]
    correct = sum(1 for p, t in answered if p == t)
    return [
        Metric("region_coverage", _ratio(len(answered), len(scored)), len(scored),
               "Share of single-region notices where the LLM gave a region"),
        Metric("region_precision", _ratio(correct, len(answered)), len(answered),
               "Share of given regions that match the TED NUTS region"),
        Metric("region_accuracy", _ratio(correct, len(scored)), len(scored),
               "Correct region over all single-region notices (null counts as wrong)"),
    ]


def value_metrics(pairs: Iterable[tuple[float | None, float | None]], tolerance: float = 0.05) -> list[Metric]:
    """pairs: (LLM mentioned value, TED value). Scored where both exist; hallucination = LLM value with no TED value."""
    pairs = list(pairs)
    both = [(p, t) for p, t in pairs if p is not None and t]
    within = sum(1 for p, t in both if abs(p - t) / t <= tolerance)
    llm_only = sum(1 for p, t in pairs if p is not None and not t)
    llm_given = sum(1 for p, _ in pairs if p is not None)
    return [
        Metric("value_match", _ratio(within, len(both)), len(both),
               f"LLM value within {tolerance:.0%} of the TED value, where both exist"),
        Metric("value_without_ted_value", _ratio(llm_only, llm_given), llm_given,
               "Share of LLM values where TED has no value (check these for hallucination)"),
    ]
