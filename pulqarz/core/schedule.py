"""Reminder schedule (pure).

For a debt due on day D both sides get a reminder 3 days before, on the day, and then while overdue
(the next day, a week later, a month later). Reminders go out at 09:00 Tashkent time (UTC+5, no DST).
Each reminder has a stable key, so the scheduler can store them and send each one exactly once.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

TASHKENT = timezone(timedelta(hours=5))
SEND_HOUR = 9
OFFSETS = (("before3", -3), ("due", 0), ("overdue1", 1), ("overdue7", 7), ("overdue30", 30))


def add_days(day: str, n: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def reminder_plan(due: str, today: str) -> list[dict]:
    """Reminders for ``due`` that are still ahead (on or after ``today``)."""
    plan = []
    for kind, offset in OFFSETS:
        day = add_days(due, offset)
        if day >= today:
            plan.append({"kind": kind, "date": day, "key": f"{kind}@{due}"})
    return plan


def fire_at(day: str) -> str:
    """UTC timestamp (``YYYY-MM-DDTHH:MM:SSZ``) of 09:00 Tashkent time on ``day``."""
    local = datetime.combine(date.fromisoformat(day), datetime.min.time(), TASHKENT)
    utc = (local + timedelta(hours=SEND_HOUR)).astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def local_today(now_utc: datetime) -> str:
    return now_utc.astimezone(TASHKENT).date().isoformat()


def days_left(due: str, today: str) -> int:
    return (date.fromisoformat(due) - date.fromisoformat(today)).days
