"""Which of the two installed Claude subscription tokens the worker uses.

Both tokens live only on the host, in root-owned env files the Claude worker loads. This
table holds nothing but the owner's choice, "a" or "b", so the API can switch slots
without ever carrying a token.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from datetime import datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Text, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from ..auth.models import Owner
from ..database import transaction_scope
from ..models.base import Base, utc_now
from .settings import SUBSCRIPTION_TOKEN_VAR

if TYPE_CHECKING:
    from .sdk_runtime import AgentSdkRuntime

TokenSlot = Literal["a", "b"]
DEFAULT_SLOT: TokenSlot = "a"

# Slot A keeps the variable the host had before slots existed, so the installed
# claude-oauth.env works unchanged; slot B has its own file and variable.
SLOT_TOKEN_VARS: Mapping[TokenSlot, str] = MappingProxyType(
    {"a": SUBSCRIPTION_TOKEN_VAR, "b": "CLAUDE_CODE_OAUTH_TOKEN_B"}
)


class ClaudeTokenSlot(Base):
    __tablename__ = "claude_token_slots"
    __table_args__ = (CheckConstraint("slot IN ('a', 'b')", name="slot_allowed"),)

    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("owners.id", ondelete="RESTRICT"), primary_key=True
    )
    slot: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


async def read_active_slot(session: AsyncSession, *, owner_id: int) -> TokenSlot:
    stored = await session.scalar(
        select(ClaudeTokenSlot.slot).where(ClaudeTokenSlot.owner_id == owner_id)
    )
    return "b" if stored == "b" else DEFAULT_SLOT


async def read_deployment_slot(session: AsyncSession) -> TokenSlot:
    """The first owner's choice; the API and the Claude worker both serve that owner."""
    owner_id = await session.scalar(select(func.min(Owner.id)))
    return DEFAULT_SLOT if owner_id is None else await read_active_slot(session, owner_id=owner_id)


async def follow_deployment_slot(
    sessions: async_sessionmaker[AsyncSession],
    runtime: AgentSdkRuntime,
    tokens: Mapping[TokenSlot, str],
) -> None:
    """Point a long-lived runtime at the active slot's token; the API does this every beat."""
    async with sessions() as session:
        slot = await read_deployment_slot(session)
        await session.rollback()
    runtime.use_slot(slot, tokens)


async def choose_slot(session: AsyncSession, *, owner_id: int, slot: TokenSlot) -> None:
    async with transaction_scope(session):
        statement = insert(ClaudeTokenSlot).values(
            owner_id=owner_id, slot=slot, updated_at=utc_now()
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[ClaudeTokenSlot.owner_id],
                set_={"slot": statement.excluded.slot, "updated_at": statement.excluded.updated_at},
            )
        )


def installed_tokens(environ: Mapping[str, str]) -> dict[TokenSlot, str]:
    return {slot: environ.get(variable, "") for slot, variable in SLOT_TOKEN_VARS.items()}


def install_slot_token(
    slot: TokenSlot, *, tokens: Mapping[TokenSlot, str], environ: MutableMapping[str, str]
) -> None:
    """Point the one variable every Claude call reads at the chosen slot's token."""
    token = tokens.get(slot, "").strip()
    if token:
        environ[SUBSCRIPTION_TOKEN_VAR] = token
    else:
        environ.pop(SUBSCRIPTION_TOKEN_VAR, None)
