"""Audit service — append-only, hash-chained, transaction-bound.

The chain invariant:
    hash = SHA-256(prev_hash | at | actor | role | action | entity | entity_id
                   | old_values | new_values | reason)

``verify_chain`` rebuilds the whole chain and reports the first broken row, which
is exactly what a GMP inspector would ask for.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import request_id_ctx
from app.models.audit import AuditLog

GENESIS_HASH = "0" * 64

#: Advisory lock key for the audit chain. Any writer that appends must hold this
#: for the rest of its transaction, otherwise two writers can read the same head,
#: both chain onto it, and fork the chain into two branches that each verify alone
#: and fail together.
AUDIT_CHAIN_LOCK_KEY = 0x5BD3A0D1

#: How long a writer waits for the lock before giving up. Appends are microsecond
#: operations, so contention is genuinely exceptional and a timeout is a real
#: error rather than a reason to write an unchained row.
AUDIT_CHAIN_LOCK_TIMEOUT = "10s"


def _canonical(value: Any) -> str:
    """Decimal-safe, key-sorted JSON so the hash is reproducible across engines."""
    def default(o: Any) -> Any:
        if hasattr(o, "isoformat"):
            return o.isoformat()
        if isinstance(o, (bytes, bytearray)):
            return o.hex()
        return str(o)

    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=default)


def compute_hash(
    *,
    prev_hash: str,
    at: str,
    actor_label: str,
    role_label: str | None,
    action: str,
    entity_type: str,
    entity_id: str,
    old_values: Any,
    new_values: Any,
    reason: str | None,
) -> str:
    payload = "|".join(
        [
            prev_hash,
            at,
            actor_label,
            role_label or "",
            action,
            entity_type,
            entity_id,
            _canonical(old_values),
            _canonical(new_values),
            reason or "",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _head(self) -> tuple[str, int]:
        """Serialise and return (head hash, next chain position).

        The advisory lock is transaction-scoped: it is released by COMMIT or
        ROLLBACK, so the caller *must* commit for the append to publish. Taking it
        here rather than in ``record`` means the head cannot move between the read
        and the insert.
        """
        await self.session.execute(
            text("SELECT set_config('lock_timeout', :t, true)"), {"t": AUDIT_CHAIN_LOCK_TIMEOUT}
        )
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:k)"), {"k": AUDIT_CHAIN_LOCK_KEY}
        )
        row = (
            await self.session.execute(
                select(AuditLog.hash, AuditLog.chain_seq)
                .order_by(AuditLog.chain_seq.desc().nullslast())
                .limit(1)
            )
        ).first()
        if row is None:
            return GENESIS_HASH, 1
        head_hash, head_seq = row
        return head_hash or GENESIS_HASH, (head_seq or 0) + 1

    async def _head_hash(self) -> str:
        head, _ = await self._head()
        return head

    async def record(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: str | uuid.UUID,
        actor_label: str,
        actor_id: uuid.UUID | None = None,
        role_label: str | None = None,
        department_id: uuid.UUID | None = None,
        old_values: Any = None,
        new_values: Any = None,
        reason: str | None = None,
        ip_address: str | None = None,
    ) -> AuditLog:
        at = datetime.now(timezone.utc)
        prev_hash, chain_seq = await self._head()
        at_iso = at.isoformat()
        digest = compute_hash(
            prev_hash=prev_hash,
            at=at_iso,
            actor_label=actor_label,
            role_label=role_label,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            old_values=old_values,
            new_values=new_values,
            reason=reason,
        )
        entry = AuditLog(
            at=at,
            department_id=department_id,
            user_id=actor_id,
            actor_label=actor_label,
            role_label=role_label,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            old_values=old_values,
            new_values=new_values,
            reason=reason,
            ip_address=ip_address,
            request_id=request_id_ctx.get(),
            prev_hash=prev_hash,
            hash=digest,
            chain_seq=chain_seq,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    @staticmethod
    async def verify_chain(session: AsyncSession, *, limit: int | None = None) -> dict[str, Any]:
        # Order by the chain position, not by wall-clock time: the hash covers
        # ``at`` with microsecond precision, but two rows can still share a
        # timestamp, and ordering those by a random UUID reported honest entries as
        # a broken chain.
        stmt = select(AuditLog).order_by(
            AuditLog.chain_seq.asc().nullsfirst(), AuditLog.at.asc(), AuditLog.id.asc()
        )
        if limit:
            stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        prev = GENESIS_HASH
        for row in rows:
            if row.prev_hash != prev:
                return {"ok": False, "broken_at": str(row.id), "reason": "prev_hash mismatch", "total": len(rows)}
            expected = compute_hash(
                prev_hash=row.prev_hash,
                at=row.at.isoformat(),
                actor_label=row.actor_label,
                role_label=row.role_label,
                action=row.action,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                old_values=row.old_values,
                new_values=row.new_values,
                reason=row.reason,
            )
            if expected != row.hash:
                return {"ok": False, "broken_at": str(row.id), "reason": "hash mismatch", "total": len(rows)}
            prev = row.hash
        return {"ok": True, "total": len(rows), "head": prev}
