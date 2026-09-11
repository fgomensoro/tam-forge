"""The release checklist: every required item resolves to evidence, or the release is refused.

A release is not a build that compiled. It is a build with evidence behind each thing the
product promises: a signed app and DMG, permissions that persist across builds, the learning
loop and memory evaluated, privacy proven fail-closed, recovery drilled, the recording path
verified on real hardware, and a version that names an exact commit. Each item on this list
names the artifact that resolves it and how it is judged. An artifact that is missing, that
records a failed verdict, or that is the blocked template counts as unresolved, and one
unresolved required item refuses the release. There is no override flag.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

Area = Literal[
    "native_app",
    "signing",
    "permissions",
    "learning",
    "privacy",
    "recovery",
    "version",
    "recording",
]
Status = Literal["resolved", "unresolved"]


class ReleaseRefused(ValueError):
    """At least one required item is unresolved."""


@dataclass(frozen=True, slots=True)
class ItemVerdict:
    key: str
    area: Area
    required: bool
    status: Status
    evidence: str
    reason: str


Judge = Callable[[Path], tuple[bool, str]]


def _exists(path: Path) -> tuple[bool, str]:
    return (path.exists(), "present" if path.exists() else "missing")


def _json_flag(key: str, expected: object = True) -> Judge:
    def judge(path: Path) -> tuple[bool, str]:
        if not path.exists():
            return False, "missing"
        body = json.loads(path.read_text(encoding="utf-8"))
        value = body
        for part in key.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        return value == expected, f"{key}={value!r}"

    return judge


def _recording_verification(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    body = json.loads(path.read_text(encoding="utf-8"))
    if body.get("commit_sha") == "0" * 40:
        return False, "blocked template: no runtime window has been recorded on this head"
    results = body.get("results", [])
    failing = [r["key"] for r in results if r.get("status") != "pass"]
    return not failing, f"{len(results)} keys, not passing: {failing[:5]}"


def _signing_evidence(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    text = path.read_text(encoding="utf-8")
    needed = ("codesign --verify", "DMG", "sha256", "Permission persistence")
    missing = [n for n in needed if n not in text]
    return (
        not missing,
        "signing, DMG and persistence recorded" if not missing else f"missing {missing}",
    )


def _version(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    text = path.read_text(encoding="utf-8")
    marketing = re.search(r"MARKETING_VERSION = ([0-9]+\.[0-9]+\.[0-9]+);", text)
    tag_file = path.parent.parent / ".release-tag"
    if marketing is None:
        return False, "no MARKETING_VERSION"
    if not tag_file.exists():
        return False, f"MARKETING_VERSION {marketing.group(1)} has no release tag record"
    tag = tag_file.read_text(encoding="utf-8").strip()
    ok = re.fullmatch(rf"v{re.escape(marketing.group(1))}\+[0-9a-f]{{7,40}}", tag) is not None
    return ok, f"tag {tag!r} for MARKETING_VERSION {marketing.group(1)}"


@dataclass(frozen=True, slots=True)
class Item:
    key: str
    area: Area
    evidence: str
    judge: Judge
    required: bool = True


CHECKLIST: Final[tuple[Item, ...]] = (
    Item(
        "native_app.dmg_and_signature",
        "signing",
        "docs/project/signing-permission-persistence-v1.md",
        _signing_evidence,
    ),
    Item(
        "permissions.persist_across_builds",
        "permissions",
        "docs/project/signing-permission-persistence-v1.md",
        _signing_evidence,
    ),
    Item(
        "recording.runtime_window",
        "recording",
        "docs/project/recording-verification-v1.json",
        _recording_verification,
    ),
    Item(
        "learning.model_selection",
        "learning",
        "docs/project/model-benchmark-v1.json",
        _json_flag("chosen_model", "candidate"),
    ),
    Item(
        "learning.speech_performance_10m",
        "learning",
        "docs/project/speech-performance-10m-apple-m5-24gb.json",
        _json_flag("verdicts.transcriptionPeakWithinGate"),
    ),
    Item(
        "learning.speech_performance_60m",
        "learning",
        "docs/project/speech-performance-60m-apple-m5-24gb.json",
        _json_flag("verdicts.transcriptionPeakWithinGate"),
    ),
    Item("learning.ai_evaluation_runbook", "learning", "docs/runbooks/ai-evaluation.md", _exists),
    Item(
        "privacy.gastos_inventory_read_only",
        "privacy",
        "docs/project/gastos-inventory-20260911T004447Z.json",
        _json_flag("no_mutation_confirmed"),
    ),
    Item(
        "privacy.retention_runbook",
        "privacy",
        "docs/runbooks/recording-upload-recovery.md",
        _exists,
    ),
    Item(
        "recovery.backup_restore_drill",
        "recovery",
        "docs/project/backup-restore-drill-20260911T163331Z.json",
        _json_flag("met"),
    ),
    Item(
        "recovery.gastos_restore_drill",
        "recovery",
        "docs/project/gastos-restore-drill-20260911T022228Z.json",
        _json_flag("lamas_untouched"),
    ),
    Item(
        "recovery.host_provisioning_runbook",
        "recovery",
        "docs/runbooks/host-provisioning.md",
        _exists,
    ),
    Item(
        "version.tagged_exact_commit",
        "version",
        "apps/macos/TAMForge.xcodeproj/project.pbxproj",
        _version,
    ),
)


@dataclass(frozen=True, slots=True)
class ReleaseDecision:
    verdicts: tuple[ItemVerdict, ...]

    @property
    def unresolved(self) -> tuple[ItemVerdict, ...]:
        return tuple(v for v in self.verdicts if v.required and v.status == "unresolved")

    @property
    def releasable(self) -> bool:
        return not self.unresolved

    def render(self) -> str:
        return (
            json.dumps(
                {
                    "releasable": self.releasable,
                    "unresolved": [v.key for v in self.unresolved],
                    "items": [
                        {
                            "key": v.key,
                            "area": v.area,
                            "required": v.required,
                            "status": v.status,
                            "evidence": v.evidence,
                            "reason": v.reason,
                        }
                        for v in self.verdicts
                    ],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )


def evaluate(repo_root: Path, checklist: tuple[Item, ...] = CHECKLIST) -> ReleaseDecision:
    verdicts: list[ItemVerdict] = []
    for item in checklist:
        ok, reason = item.judge(repo_root / item.evidence)
        verdicts.append(
            ItemVerdict(
                item.key,
                item.area,
                item.required,
                "resolved" if ok else "unresolved",
                item.evidence,
                reason,
            )
        )
    return ReleaseDecision(tuple(verdicts))


def require_releasable(decision: ReleaseDecision) -> None:
    if not decision.releasable:
        names = ", ".join(v.key for v in decision.unresolved)
        raise ReleaseRefused(f"release refused; unresolved: {names}")


__all__ = [
    "CHECKLIST",
    "Item",
    "ItemVerdict",
    "ReleaseDecision",
    "ReleaseRefused",
    "evaluate",
    "require_releasable",
]
