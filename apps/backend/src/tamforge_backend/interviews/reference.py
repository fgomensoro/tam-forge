"""The answer bank and the story catalog, split into entries the roles can cite.

Every entry keeps the readiness label the document carried ("ready", "draft", a score) and
marks it unverified: it is what Frank believed when he wrote it, not what the ledger has
seen. A role cites an entry by heading and never treats it as demonstrated.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Final

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
READINESS = re.compile(
    r"^\s*(?:[-*]\s*)?\**(?:readiness|status|confidence)\**\s*:\s*\**\s*(.+?)\s*$", re.I
)
STOP_WORDS: Final = frozenset(
    "a an and are as at be by for from how in is it of on or that the this to was what when "
    "which who why with your you my we our".split()
)
MAX_ENTRIES = 500


@dataclass(frozen=True, slots=True)
class ReferenceEntry:
    heading: str
    body: str
    readiness_label: str

    @property
    def content_hash(self) -> bytes:
        normalized = f"{' '.join(self.heading.split()).casefold()}\n{' '.join(self.body.split())}"
        return hashlib.sha256(normalized.encode("utf-8")).digest()


def parse_reference_entries(markdown: str) -> tuple[ReferenceEntry, ...]:
    """Every heading below the title starts an entry; the title alone is not one."""
    entries: list[ReferenceEntry] = []
    heading: str | None = None
    body: list[str] = []
    readiness = ""

    def close() -> None:
        nonlocal heading, body, readiness
        if heading is not None and (body or readiness) and len(entries) < MAX_ENTRIES:
            text = "\n".join(body).strip()
            if text or readiness:
                entries.append(ReferenceEntry(heading[:512], text[:65536], readiness[:128]))
        heading, body, readiness = None, [], ""

    for raw in markdown.splitlines():
        match = HEADING.match(raw)
        if match is not None:
            level = len(match.group(1))
            if heading is None and not entries and level == 1 and not body:
                continue  # the document title
            close()
            heading = match.group(2).strip()
            continue
        label = READINESS.match(raw)
        if label is not None and heading is not None:
            readiness = label.group(1).strip()
            continue
        if heading is not None:
            body.append(raw.rstrip())
    close()
    return tuple(entries)


def _terms(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9][a-z0-9'-]{2,}", text.casefold())
        if word not in STOP_WORDS
    }


def rank_entries(
    entries: tuple[tuple[str, str, str], ...], text: str, limit: int = 3
) -> tuple[tuple[str, str, str], ...]:
    """The entries (heading, body, readiness) whose words overlap the text most."""
    wanted = _terms(text)
    if not wanted:
        return ()
    scored = []
    for entry in entries:
        heading_terms = _terms(entry[0])
        body_terms = _terms(entry[1][:2000])
        score = 3 * len(wanted & heading_terms) + len(wanted & body_terms)
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda item: (-item[0], item[1][0]))
    return tuple(entry for _, entry in scored[:limit])


def render_citation(heading: str, body: str, readiness: str, kind: str) -> str:
    excerpt = " ".join(body.split())[:400]
    label = f"; readiness '{readiness}' (unverified)" if readiness else "; readiness unverified"
    return f"[{kind}] {heading}{label}: {excerpt}"


__all__ = [
    "ReferenceEntry",
    "parse_reference_entries",
    "rank_entries",
    "render_citation",
]
