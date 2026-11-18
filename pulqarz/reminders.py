"""Reminder scheduler. Due reminders live in the ``reminders`` table, so a restart loses nothing: the loop
simply picks up whatever is due. Each row is claimed (marked sent) before delivery, so it fires at most once.
A reminder whose debt was paid, written off or moved to a new due date is skipped silently."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from .core import ledger
from .db import Database
from .service import Service, stamp

log = logging.getLogger(__name__)

Deliver = Callable[[int, int, dict, str], Awaitable[None]]  # (user_id, other_id, debt, kind)


async def run_due(service: Service, deliver: Deliver) -> int:
    """Send everything that is due now. Returns how many reminders were delivered."""
    db: Database = service.db
    now = stamp(service.clock())
    sent = 0
    for row in await db.due_reminders(now):
        if not await db.claim_reminder(row, now):
            continue  # another worker took it
        kind, _, due = row["key"].partition("@")
        state, _ = ledger.fold_trusted(await db.entries(row["pair"]))
        debt = state["debts"].get(row["debt_seq"])
        if not debt or debt["status"] != "active" or debt["due"] != due:
            continue
        a, b = ledger.parties(row["pair"])
        other = b if row["user_id"] == a else a
        try:
            await deliver(row["user_id"], other, debt, kind)
            sent += 1
        except Exception:  # a blocked bot or a network error must not stop the loop
            log.exception("reminder delivery failed for user %s", row["user_id"])
    return sent


async def loop(service: Service, deliver: Deliver, interval: float = 60.0) -> None:
    while True:
        try:
            await run_due(service, deliver)
        except Exception:
            log.exception("reminder loop iteration failed")
        await asyncio.sleep(interval)
