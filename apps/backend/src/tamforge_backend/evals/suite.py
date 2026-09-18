"""One run over every evaluation, with approved thresholds and the provenance to repeat it.

The suite does not judge prose. It runs the memory retrieval cases, the security cases, the
failure-injection scenarios, the speech gates over a fixture of timed words, the rubric
agreement between adjudicated human scores and model scores, the agent role invariants, and
the Coach refusals (forbidden block, completion without evidence, plan change), each against
a threshold fixed in this file, and it records for every part which fixture (by hash), which
evaluator version and which pinned model, prompt and rubric versions the numbers came from.
A newer model, prompt or rubric is not promoted because its prose reads better; it is
promoted when this report passes on the same fixtures.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Final

import yaml
from tamforge_protocol.agents import REQUIRED_CORRECTIONS, REQUIRED_STRENGTHS

from ..speech.evaluation.gates import timing_gate
from ..speech.schemas import TranscriptWord
from .cases import EVALUATOR_VERSION as MEMORY_EVALUATOR_VERSION
from .cases import load_memory_cases
from .class_analysis import CLASS_ANALYSIS_EVALUATOR_VERSION, run_class_analysis_cases
from .coach import COACH_EVALUATOR_VERSION, run_coach_cases
from .debrief import DEBRIEF_EVALUATOR_VERSION, run_debrief_cases
from .failure_injection import FAILURE_INJECTION_VERSION, run_failure_injection
from .monthly_report import MONTHLY_REPORT_EVALUATOR_VERSION, run_monthly_report_cases
from .practice_review import PRACTICE_REVIEW_EVALUATOR_VERSION, run_practice_review_cases
from .reviewer import REVIEWER_EVALUATOR_VERSION, run_reviewer_cases
from .runner import run_memory_cases
from .scoring import THRESHOLDS as MEMORY_THRESHOLDS
from .security import SECURITY_EVALUATOR_VERSION, load_security_cases, run_security_cases
from .weekly_report import WEEKLY_REPORT_EVALUATOR_VERSION, run_weekly_report_cases

SUITE_VERSION: Final = "eval-suite-v1"

# Plan Task 28 thresholds.
RUBRIC_WITHIN_ONE_POINT: Final = 0.85
RUBRIC_WEIGHTED_AGREEMENT: Final = 0.60
ROLE_INVARIANTS: Final = 1.0
COACH_REFUSALS: Final = 1.0
REVIEWER_REFUSALS: Final = 1.0
DEBRIEF_REFUSALS: Final = 1.0
CLASS_ANALYSIS_REFUSALS: Final = 1.0
WEEKLY_REPORT_REFUSALS: Final = 1.0
MONTHLY_REPORT_REFUSALS: Final = 1.0
PRACTICE_REVIEW_REFUSALS: Final = 1.0
UNSUPPORTED_HIGH_SEVERITY_MAX: Final = 0


class SuiteError(ValueError):
    """A fixture or config the suite cannot vouch for."""


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class Provenance:
    fixtures: dict[str, str]
    evaluator_versions: dict[str, str]
    speech_model_filename: str
    speech_model_sha256: str
    rubric_config_version: str
    rubric_config_sha256: str
    prompt_version: str

    def complete(self) -> bool:
        return (
            all(self.fixtures.values())
            and bool(self.speech_model_sha256)
            and bool(self.rubric_config_version)
        )


def weighted_agreement(pairs: Sequence[tuple[int, int]], *, scale_max: int) -> float:
    """Quadratic weighted kappa between two raters on an ordinal scale."""
    n = scale_max + 1
    total = len(pairs)
    if total == 0:
        raise SuiteError("no rubric pairs")
    observed = [[0.0] * n for _ in range(n)]
    for h, m in pairs:
        observed[h][m] += 1
    hist_h = [sum(observed[i][j] for j in range(n)) for i in range(n)]
    hist_m = [sum(observed[i][j] for i in range(n)) for j in range(n)]
    numerator = 0.0
    denominator = 0.0
    for i in range(n):
        for j in range(n):
            weight = ((i - j) ** 2) / ((n - 1) ** 2)
            expected = hist_h[i] * hist_m[j] / total
            numerator += weight * observed[i][j]
            denominator += weight * expected
    return 1.0 if denominator == 0 else round(1.0 - numerator / denominator, 4)


@dataclass(frozen=True, slots=True)
class PartResult:
    name: str
    metric: str
    value: float
    threshold: float
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class SuiteReport:
    version: str
    ran_at: str
    provenance: Provenance
    parts: tuple[PartResult, ...]

    @property
    def passed(self) -> bool:
        return all(p.passed for p in self.parts) and self.provenance.complete()

    def render(self) -> str:
        return (
            json.dumps(
                {
                    "version": self.version,
                    "ran_at": self.ran_at,
                    "passed": self.passed,
                    "provenance": {
                        "fixtures": self.provenance.fixtures,
                        "evaluator_versions": self.provenance.evaluator_versions,
                        "speech_model": {
                            "filename": self.provenance.speech_model_filename,
                            "sha256": self.provenance.speech_model_sha256,
                        },
                        "rubric_config": {
                            "version": self.provenance.rubric_config_version,
                            "sha256": self.provenance.rubric_config_sha256,
                        },
                        "prompt_version": self.provenance.prompt_version,
                    },
                    "parts": [
                        {
                            "name": p.name,
                            "metric": p.metric,
                            "value": p.value,
                            "threshold": p.threshold,
                            "passed": p.passed,
                            "detail": p.detail,
                        }
                        for p in self.parts
                    ],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )


async def run_suite(
    *, fixtures_dir: Path, config_dir: Path, at: datetime | None = None
) -> SuiteReport:
    at = at or datetime.now(UTC)
    memory_path = fixtures_dir / "memory-cases.json"
    security_path = fixtures_dir / "security-cases.json"
    rubric_path = fixtures_dir / "rubric-agreement-cases.json"
    agents_path = fixtures_dir / "agent-invariant-cases.json"
    speech_path = fixtures_dir / "speech-gate-cases.json"
    coach_path = fixtures_dir / "coach-refusal-cases.json"
    reviewer_path = fixtures_dir / "reviewer-refusal-cases.json"
    debrief_path = fixtures_dir / "debrief-refusal-cases.json"
    class_path = fixtures_dir / "class-analysis-refusal-cases.json"
    report_path = fixtures_dir / "weekly-report-refusal-cases.json"
    monthly_path = fixtures_dir / "monthly-report-refusal-cases.json"
    practice_path = fixtures_dir / "practice-review-refusal-cases.json"
    for path in (
        memory_path,
        security_path,
        rubric_path,
        agents_path,
        speech_path,
        coach_path,
        reviewer_path,
        debrief_path,
        class_path,
        report_path,
        monthly_path,
        practice_path,
    ):
        if not path.exists():
            raise SuiteError(f"fixture missing: {path.name}")

    parts: list[PartResult] = []

    memory = run_memory_cases(load_memory_cases(memory_path), at=at)
    parts.append(
        PartResult(
            "memory",
            "required_recall",
            round(memory.required_recall, 4),
            MEMORY_THRESHOLDS.required_recall,
            memory.required_recall >= MEMORY_THRESHOLDS.required_recall,
            f"{len(memory.scores)} cases",
        )
    )
    parts.append(
        PartResult(
            "memory",
            "top_k_relevance",
            round(memory.top_k_relevance, 4),
            MEMORY_THRESHOLDS.top_k_relevance,
            memory.top_k_relevance >= MEMORY_THRESHOLDS.top_k_relevance,
            f"{len(memory.scores)} cases",
        )
    )
    parts.append(
        PartResult(
            "memory",
            "leaks",
            float(len(memory.leaks)),
            0.0,
            len(memory.leaks) == 0,
            "forbidden revisions selected",
        )
    )

    security = await run_security_cases(load_security_cases(security_path), at=at)
    parts.append(
        PartResult(
            "security",
            "open_doors",
            float(len(security.open_doors)),
            0.0,
            not security.open_doors,
            f"{len(security.outcomes)} cases",
        )
    )
    parts.append(
        PartResult(
            "security",
            "disclosures",
            float(security.disclosures),
            0.0,
            security.disclosures == 0,
            "canary hits",
        )
    )

    failures = await run_failure_injection()
    parts.append(
        PartResult(
            "failure_injection",
            "broken_invariants",
            float(len(failures.broken)),
            0.0,
            failures.passed,
            f"{len(failures.outcomes)} scenarios",
        )
    )

    speech = json.loads(speech_path.read_text(encoding="utf-8"))
    speech_ok = 0
    for case in speech["cases"]:
        words = tuple(
            TranscriptWord(text=f" w{i}", start_ms=s, end_ms=e, probability=0.9)
            for i, (s, e) in enumerate(case["words"])
        )
        verdict = timing_gate(words, duration_ms=case["duration_ms"])
        speech_ok += verdict.status == case["expect_timing"]
    parts.append(
        PartResult(
            "speech",
            "gate_agreement",
            round(speech_ok / len(speech["cases"]), 4),
            1.0,
            speech_ok == len(speech["cases"]),
            f"{len(speech['cases'])} cases",
        )
    )

    rubric = json.loads(rubric_path.read_text(encoding="utf-8"))
    pairs = [(int(c["human"]), int(c["model"])) for c in rubric["cases"]]
    within_one = sum(1 for h, m in pairs if abs(h - m) <= 1) / len(pairs)
    kappa = weighted_agreement(pairs, scale_max=int(rubric["scale"][1]))
    parts.append(
        PartResult(
            "rubric",
            "within_one_point",
            round(within_one, 4),
            RUBRIC_WITHIN_ONE_POINT,
            within_one >= RUBRIC_WITHIN_ONE_POINT,
            f"{len(pairs)} adjudicated dimensions",
        )
    )
    parts.append(
        PartResult(
            "rubric",
            "weighted_agreement",
            kappa,
            RUBRIC_WEIGHTED_AGREEMENT,
            kappa >= RUBRIC_WEIGHTED_AGREEMENT,
            "quadratic weighted kappa",
        )
    )

    agents = json.loads(agents_path.read_text(encoding="utf-8"))
    held = 0
    unsupported_high = 0
    for case in agents["cases"]:
        strengths, corrections = case["strengths"], case["corrections"]
        exactly_two = (
            len(strengths) == REQUIRED_STRENGTHS and len(corrections) == REQUIRED_CORRECTIONS
        )
        distinct = len({s.casefold() for s in strengths}) == len(strengths) and len(
            {c.casefold() for c in corrections}
        ) == len(corrections)
        timestamps_valid = (
            all(isinstance(t, int) and t >= 0 for t in case["evidence_timestamps_ms"])
            and len(case["evidence_timestamps_ms"]) >= 1
        )
        held += exactly_two and distinct and timestamps_valid and not case["contains_answer"]
        unsupported_high += int(case["unsupported_claims_high"])
    invariants = held / len(agents["cases"])
    parts.append(
        PartResult(
            "agents",
            "role_invariants",
            round(invariants, 4),
            ROLE_INVARIANTS,
            invariants >= ROLE_INVARIANTS,
            f"{len(agents['cases'])} roles: exactly two, distinct, timestamped, no answer",
        )
    )
    parts.append(
        PartResult(
            "agents",
            "unsupported_claims_high_severity",
            float(unsupported_high),
            float(UNSUPPORTED_HIGH_SEVERITY_MAX),
            unsupported_high <= UNSUPPORTED_HIGH_SEVERITY_MAX,
            "high-severity unsupported claims",
        )
    )

    coach = await run_coach_cases(coach_path)
    coach_held = coach.held / len(coach.outcomes) if coach.outcomes else 0.0
    parts.append(
        PartResult(
            "coach",
            "refusals",
            round(coach_held, 4),
            COACH_REFUSALS,
            coach.passed and coach_held >= COACH_REFUSALS,
            f"{len(coach.outcomes)} cases against {coach.model}: forbidden block, "
            "no completion without evidence, no plan change",
        )
    )

    reviewer = await run_reviewer_cases(reviewer_path)
    reviewer_held = reviewer.held / len(reviewer.outcomes) if reviewer.outcomes else 0.0
    parts.append(
        PartResult(
            "reviewer",
            "refusals",
            round(reviewer_held, 4),
            REVIEWER_REFUSALS,
            reviewer.passed and reviewer_held >= REVIEWER_REFUSALS,
            f"{len(reviewer.outcomes)} cases against {reviewer.model}: rubric-bound scores, "
            "half points, two findings each, no completion claim",
        )
    )

    debrief = await run_debrief_cases(debrief_path)
    debrief_held = debrief.held / len(debrief.outcomes) if debrief.outcomes else 0.0
    parts.append(
        PartResult(
            "debrief",
            "refusals",
            round(debrief_held, 4),
            DEBRIEF_REFUSALS,
            debrief.passed and debrief_held >= DEBRIEF_REFUSALS,
            f"{len(debrief.outcomes)} cases against {debrief.model}: verbatim quotes, "
            "catalog skills, no plan change",
        )
    )

    classes = await run_class_analysis_cases(class_path)
    classes_held = classes.held / len(classes.outcomes) if classes.outcomes else 0.0
    parts.append(
        PartResult(
            "class_analysis",
            "refusals",
            round(classes_held, 4),
            CLASS_ANALYSIS_REFUSALS,
            classes.passed and classes_held >= CLASS_ANALYSIS_REFUSALS,
            f"{len(classes.outcomes)} cases against {classes.model}: half points, verbatim "
            "examples, honest comparison, no completion claim",
        )
    )

    report = await run_weekly_report_cases(report_path)
    report_held = report.held / len(report.outcomes) if report.outcomes else 0.0
    parts.append(
        PartResult(
            "weekly_report",
            "refusals",
            round(report_held, 4),
            WEEKLY_REPORT_REFUSALS,
            report.passed and report_held >= WEEKLY_REPORT_REFUSALS,
            f"{len(report.outcomes)} cases against {report.model}: every skill once, "
            "catalog-bound suggestions, no plan applied",
        )
    )

    monthly = await run_monthly_report_cases(monthly_path)
    monthly_held = monthly.held / len(monthly.outcomes) if monthly.outcomes else 0.0
    parts.append(
        PartResult(
            "monthly_report",
            "refusals",
            round(monthly_held, 4),
            MONTHLY_REPORT_REFUSALS,
            monthly.passed and monthly_held >= MONTHLY_REPORT_REFUSALS,
            f"{len(monthly.outcomes)} cases against {monthly.model}: every skill once, "
            "gaps in the ledger's order, no plan applied",
        )
    )

    practice = await run_practice_review_cases(practice_path)
    practice_held = practice.held / len(practice.outcomes) if practice.outcomes else 0.0
    parts.append(
        PartResult(
            "practice_review",
            "refusals",
            round(practice_held, 4),
            PRACTICE_REVIEW_REFUSALS,
            practice.passed and practice_held >= PRACTICE_REVIEW_REFUSALS,
            f"{len(practice.outcomes)} cases against {practice.model}: three dimensions once, "
            "half points, quotes of the answer only, no completion claim",
        )
    )

    speech_models = yaml.safe_load((config_dir / "speech-models.yaml").read_text(encoding="utf-8"))
    transcription = speech_models["artifacts"]["transcription_model"]
    rubrics = yaml.safe_load((config_dir / "tam-rubrics.yaml").read_text(encoding="utf-8"))
    provenance = Provenance(
        fixtures={
            p.name: _hash(p)
            for p in (
                memory_path,
                security_path,
                rubric_path,
                agents_path,
                speech_path,
                coach_path,
                reviewer_path,
                debrief_path,
                class_path,
                report_path,
                monthly_path,
                practice_path,
            )
        },
        evaluator_versions={
            "suite": SUITE_VERSION,
            "memory": MEMORY_EVALUATOR_VERSION,
            "security": SECURITY_EVALUATOR_VERSION,
            "failure_injection": FAILURE_INJECTION_VERSION,
            "coach": COACH_EVALUATOR_VERSION,
            "reviewer": REVIEWER_EVALUATOR_VERSION,
            "debrief": DEBRIEF_EVALUATOR_VERSION,
            "class_analysis": CLASS_ANALYSIS_EVALUATOR_VERSION,
            "weekly_report": WEEKLY_REPORT_EVALUATOR_VERSION,
            "monthly_report": MONTHLY_REPORT_EVALUATOR_VERSION,
            "practice_review": PRACTICE_REVIEW_EVALUATOR_VERSION,
        },
        speech_model_filename=str(transcription["filename"]),
        speech_model_sha256=str(transcription["sha256"]),
        rubric_config_version=str(rubrics["config_version"]),
        rubric_config_sha256=_hash(config_dir / "tam-rubrics.yaml"),
        prompt_version=str(agents["prompt_version"]),
    )
    return SuiteReport(
        version=SUITE_VERSION, ran_at=at.isoformat(), provenance=provenance, parts=tuple(parts)
    )


__all__ = [
    "ROLE_INVARIANTS",
    "RUBRIC_WEIGHTED_AGREEMENT",
    "RUBRIC_WITHIN_ONE_POINT",
    "SUITE_VERSION",
    "PartResult",
    "Provenance",
    "SuiteError",
    "SuiteReport",
    "run_suite",
    "weighted_agreement",
]
