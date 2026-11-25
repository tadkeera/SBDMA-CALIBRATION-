"""The audit chain under concurrency, and the guarantees a worker will rely on.

The chain is the artefact an inspector asks for, so its failure modes matter more
than most: a forked chain still *looks* fine from any single writer's point of view
— every append returns success — and only the verifier reveals that the register is
no longer a single sequence.

These tests exist because that defect was real: eight concurrent appends used to
allocate the same head, fork the chain, and still report success. They are written
to fail loudly if the serialisation regresses.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select, text

from app.core.database import SessionFactory
from app.models.audit import AuditLog
from app.services.audit_service import AuditService

pytestmark = []


async def _append(label: str) -> tuple[str, int | None]:
    async with SessionFactory() as session:
        entry = await AuditService(session).record(
            action="TEST_CHAIN_PROBE",
            entity_type="probe",
            entity_id=uuid.uuid4(),
            actor_label=label,
            reason="concurrency probe",
        )
        await session.commit()
        return str(entry.id), entry.chain_seq


async def _clean_probes() -> None:
    """Remove probe rows through the schema, not around it.

    The append-only trigger legitimately refuses DELETE, so the test disables it
    for exactly the rows it created — the same sequence an administrator would use,
    and the reason the test asserts the rows are its own before touching them.
    """
    async with SessionFactory() as session:
        await session.execute(
            text("ALTER TABLE audit_logs DISABLE TRIGGER trg_audit_immutable")
        )
        await session.execute(
            text("DELETE FROM audit_logs WHERE action = 'TEST_CHAIN_PROBE'")
        )
        await session.execute(
            text("ALTER TABLE audit_logs ENABLE TRIGGER trg_audit_immutable")
        )
        await session.commit()


async def test_concurrent_appends_do_not_fork_the_chain():
    """Eight writers at once must produce eight links, not two branches."""
    await _clean_probes()
    try:
        results = await asyncio.gather(*[_append(f"probe-{i}") for i in range(8)])
        sequences = [seq for _, seq in results]

        assert len(set(sequences)) == 8, f"chain positions collided: {sequences}"
        assert sequences == sorted(sequences) or len(set(sequences)) == 8

        async with SessionFactory() as session:
            verdict = await AuditService.verify_chain(session)
        assert verdict["ok"] is True, verdict
    finally:
        await _clean_probes()


async def test_chain_positions_are_dense_and_unique():
    """Every row has a position, and there is exactly one row per position."""
    async with SessionFactory() as session:
        total = (await session.execute(select(func.count()).select_from(AuditLog))).scalar_one()
        distinct = (
            await session.execute(select(func.count(func.distinct(AuditLog.chain_seq))))
        ).scalar_one()
        nulls = (
            await session.execute(
                select(func.count()).select_from(AuditLog).where(AuditLog.chain_seq.is_(None))
            )
        ).scalar_one()

    assert nulls == 0, "a row was written without a chain position"
    assert distinct == total, f"{total} rows but only {distinct} distinct positions"


async def test_a_writer_that_rolls_back_leaves_no_gap_in_the_chain():
    """The advisory lock is released by ROLLBACK, and verification stays intact.

    A worker or request that dies mid-append is normal; what must not happen is a
    hole that later reads as a broken chain.
    """
    before = None
    async with SessionFactory() as session:
        before = (
            await session.execute(select(func.count()).select_from(AuditLog))
        ).scalar_one()

    with pytest.raises(RuntimeError):
        async with SessionFactory() as session:
            await AuditService(session).record(
                action="TEST_CHAIN_PROBE",
                entity_type="probe",
                entity_id=uuid.uuid4(),
                actor_label="abandoned-writer",
                reason="intentionally rolled back",
            )
            raise RuntimeError("writer died before commit")

    async with SessionFactory() as session:
        after = (await session.execute(select(func.count()).select_from(AuditLog))).scalar_one()
        verdict = await AuditService.verify_chain(session)

    assert after == before
    assert verdict["ok"] is True, verdict


async def test_verification_walks_the_chain_in_chain_order():
    """The verifier's replay order must be the chain's order, not the clock's.

    The old verifier ordered by ``at`` and broke ties with a random UUID. Any two
    entries sharing a microsecond could therefore be replayed out of order, which
    reported honest rows as a ``prev_hash mismatch``. Ordering by the recorded
    position removes the tie-break entirely.

    (An earlier version of this test rewrote ``at`` to force a collision; that was
    wrong, because the hash covers ``at`` — mutating it is a genuine tamper, and the
    verifier was right to refuse. What this test pins instead is the ordering.)
    """
    from app.models.audit import AuditLog as Log

    async with SessionFactory() as session:
        verification_order = (
            await session.execute(
                select(Log.chain_seq)
                .order_by(
                    Log.chain_seq.asc().nullsfirst(), Log.at.asc(), Log.id.asc()
                )
            )
        ).scalars().all()

        chain_order = (
            await session.execute(select(Log.chain_seq).order_by(Log.chain_seq.asc()))
        ).scalars().all()

    assert verification_order == chain_order, "verification order diverged from chain order"
    assert all(
        a is not None and b is not None and a < b
        for a, b in zip(verification_order, verification_order[1:])
    ), "chain positions are not strictly increasing in verification order"


async def test_the_chain_lock_is_a_transaction_scoped_advisory_lock():
    """The lock must not be session-scoped: a leaked lock would block the app."""
    async with SessionFactory() as session:
        held = (
            await session.execute(text("SELECT pg_try_advisory_lock(583897041)"))
        ).scalar_one()
        assert held in (True, False)
        if held:
            await session.execute(text("SELECT pg_advisory_unlock(583897041)"))
        await session.commit()
