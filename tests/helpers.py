"""Shared helpers: an in-memory database and a clock the tests can move forward."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from pulqarz.db import Database
from pulqarz.service import Service

ALI, VALI, OLIM = 1001, 1002, 1003  # Olim is the curious third person


class Clock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 11, 18, 7, 0, tzinfo=UTC)  # 12:00 in Tashkent

    def __call__(self) -> datetime:
        return self.now

    def skip(self, days: float = 0, hours: float = 0) -> None:
        self.now += timedelta(days=days, hours=hours)


@asynccontextmanager
async def service_env(clock: Clock | None = None):
    clock = clock or Clock()
    db = await Database.open(":memory:")
    svc = Service(db, invite_days=7, clock=clock)
    for uid, name in ((ALI, "Ali"), (VALI, "Vali"), (OLIM, "Olim")):
        await svc.touch_user(uid, name, "uz")
    try:
        yield svc, clock
    finally:
        await db.close()


async def lend_via_link(svc: Service, amount: int = 150_000_000, due: str = "2026-12-01") -> dict:
    """Ali lends to Vali via a share link; Vali opens it and confirms. Returns the confirm result."""
    res = await svc.propose_debt(ALI, direction="lent", amount=amount, cur="UZS", due=due, note="Telefon", name="Vali")
    await svc.open_invite(VALI, res["token"])
    return await svc.answer(VALI, ALI, 1, confirm=True)
