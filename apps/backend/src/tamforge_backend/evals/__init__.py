"""Deterministic evaluation harness: versioned cases, code-enforced thresholds, no live model."""

from __future__ import annotations

from .cases import EVALUATOR_VERSION, MemoryCase, MemoryCaseSet, load_memory_cases
from .runner import MemoryEvalReport, run_memory_cases
from .scoring import THRESHOLDS, CaseScore, Thresholds, score_case

__all__ = [
    "EVALUATOR_VERSION",
    "THRESHOLDS",
    "CaseScore",
    "MemoryCase",
    "MemoryCaseSet",
    "MemoryEvalReport",
    "Thresholds",
    "load_memory_cases",
    "run_memory_cases",
    "score_case",
]
