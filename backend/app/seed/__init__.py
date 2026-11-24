"""Idempotent database seeding.

Usage:
    python -m app.seed            # all steps
    python -m app.seed rbac protocol
    python -m app.seed --check    # report only, change nothing
"""

from __future__ import annotations

import asyncio
import sys

from app.core.database import SessionFactory
from app.core.logging import configure_logging, get_logger
from app.seed.seed_assets import seed_assets
from app.seed.seed_protocol import seed_protocol
from app.seed.seed_rbac import seed_rbac
from app.seed.seed_users import seed_users

log = get_logger("sbdma.seed")

STEPS = {
    "rbac": seed_rbac,
    "protocol": seed_protocol,
    "assets": seed_assets,
    "users": seed_users,
}
ORDER = ("rbac", "protocol", "assets", "users")


async def run(steps: list[str]) -> dict[str, dict[str, int]]:
    report: dict[str, dict[str, int]] = {}
    async with SessionFactory() as session:
        for name in steps:
            report[name] = await STEPS[name](session)
        await session.commit()
    return report


async def main(argv: list[str]) -> int:
    configure_logging("INFO", as_json=False)
    steps = [a for a in argv if a in STEPS] or list(ORDER)
    report = await run(steps)
    for name in steps:
        print(f"{name}: {report[name]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
