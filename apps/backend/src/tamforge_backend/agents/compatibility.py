"""Claude's runtime status: stored evidence plus configuration, nothing else.

#65 extends this module with the compatibility probe (installed SDK, subscription
login, resolved model, typed tool round-trip). This module only answers whether
Claude may run at all.
"""

from __future__ import annotations

import json
from typing import Literal, Protocol

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import InvalidProvenance
from .models import PrivacyAttestation
from .prompt_registry import verified
from .settings import AttestationRecord, claude_availability


class AttestationSource(Protocol):
    """What `claude_status` needs; `AttestationRepository` satisfies it structurally."""

    async def current(self, *, owner_id: int) -> AttestationRecord | None: ...


class AttestationRepository:
    """Reads the newest stored attestation. Never writes one."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def current(self, *, owner_id: int) -> AttestationRecord | None:
        if type(owner_id) is not int or owner_id <= 0:
            raise InvalidProvenance()
        try:
            async with self.session.begin():
                row = await self.session.scalar(
                    select(PrivacyAttestation)
                    .where(PrivacyAttestation.owner_id == owner_id)
                    .order_by(PrivacyAttestation.id.desc())
                    .limit(1)
                )
                if row is None:
                    return None
                payload = verified(row).canonical_json
        except SQLAlchemyError:
            raise InvalidProvenance() from None
        try:
            return AttestationRecord.model_validate(json.loads(payload))
        except (json.JSONDecodeError, ValidationError):
            # A broken attestation is not consent: treat it as none, not an error.
            return None


async def claude_status(
    *, repository: AttestationSource, owner_id: int, enabled: bool
) -> tuple[Literal["disabled", "ready"], str]:
    """Load the current attestation and delegate the decision to `claude_availability`."""
    stored = await repository.current(owner_id=owner_id)
    return claude_availability(enabled=enabled, stored=stored)
