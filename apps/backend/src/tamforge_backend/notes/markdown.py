"""Render a study note as the Markdown Frank reads in Obsidian; the app stays the source.

The front matter keeps the keys his vault template uses (`type`, `status`,
`future-app-source`, `flashcard-source`) and adds `assistance` and `assessment`, both
recorded by the app from what happened. `flashcard-source` is true only for an approved
note that carries flashcards, matching the vault rule that cards come from validated notes.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

_UNSAFE = re.compile(r"[^A-Za-z0-9 ._-]+")


@dataclass(frozen=True, slots=True)
class NoteDocument:
    title: str
    stable_id: str
    local_date: date
    status: str
    assistance: str
    assessment_status: str
    drafted_by: str
    rule: str
    explanation: str
    example: str
    misconceptions: Sequence[str]
    validated_queries: Sequence[Mapping[str, object]]
    sources: Sequence[str]
    flashcards: Sequence[Mapping[str, object]]


def note_filename(document: NoteDocument) -> str:
    stem = _UNSAFE.sub("", document.title).strip() or document.stable_id
    return f"{document.local_date.isoformat()} - {stem[:120]}.md"


def _yaml_text(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_note_markdown(document: NoteDocument) -> str:
    approved = document.status == "approved"
    front = [
        "---",
        "type: polished-study-note",
        f"status: {'validated' if approved else 'draft'}",
        f"topic: {_yaml_text(document.title)}",
        f"date: {document.local_date.isoformat()}",
        f"activity: {_yaml_text(document.stable_id)}",
        f"assistance: {document.assistance}",
        f"assessment: {document.assessment_status}",
        f"drafted-by: {document.drafted_by}",
        "future-app-source: true",
        f"flashcard-source: {'true' if approved and document.flashcards else 'false'}",
        "---",
    ]
    body = [f"# {document.title}", ""]
    body += ["## Rule", "", document.rule.strip() or "—", ""]
    body += ["## Explanation", "", document.explanation.strip() or "—", ""]
    body += ["## Example", "", document.example.strip() or "—", ""]
    body += ["## Corrected misconceptions", ""]
    body += [f"- {item}" for item in document.misconceptions] or ["- —"]
    body.append("")
    body += ["## Validated queries", ""]
    if document.validated_queries:
        for item in document.validated_queries:
            body += ["```sql", str(item.get("query", "")).strip(), "```", ""]
            body += ["Result: " + str(item.get("result", "")).strip(), ""]
    else:
        body += ["—", ""]
    body += ["## Sources", ""]
    body += [f"- {item}" for item in document.sources] or ["- —"]
    body.append("")
    body += ["## Card-ready Q/A", ""]
    if document.flashcards:
        for item in document.flashcards:
            body += [
                f"**Q:** {str(item.get('question', '')).strip()}",
                f"**A:** {str(item.get('answer', '')).strip()}",
                "",
            ]
    else:
        body += ["—", ""]
    body += [
        "## Assistance and assessment",
        "",
        f"- Assistance: {document.assistance}",
        f"- Assessment status: {document.assessment_status}",
        f"- Drafted by: {document.drafted_by}",
        "",
    ]
    return "\n".join(front + [""] + body)


__all__ = ["NoteDocument", "note_filename", "render_note_markdown"]
