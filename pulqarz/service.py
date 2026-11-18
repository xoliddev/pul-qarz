"""Use cases shared by the bot and the Mini App API. Every call is made *as* a user (``me``) and can only
reach the chain between ``me`` and one partner, so a third person can never read or answer someone else's
debt. All input is validated here; the ledger rules themselves live in ``core.ledger``."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from .core import balance, ledger, schedule
from .db import Database
from .security import TOKEN_RE, new_invite_token, token_digest

NAME_MAX = 40
_CONTROL = re.compile(r"[\x00-\x09\x0b-\x1f\x7f​-‏‪-‮⁦-⁩]")


class Refused(Exception):
    """A request was refused; ``code`` maps to an ``err.<code>`` text."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def utcnow() -> datetime:
    return datetime.now(UTC)


def stamp(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_name(text: object) -> str:
    name = " ".join(_CONTROL.sub(" ", str(text or "")).split())
    if not 1 <= len(name) <= NAME_MAX:
        raise Refused("name")
    return name


def clean_note(text: object, limit: int = ledger.NOTE_MAX, code: str = "note", required: bool = False) -> str:
    note = _CONTROL.sub(" ", str(text or "")).strip()
    if len(note) > limit or (required and not note):
        raise Refused(code)
    return note


def check_due(due: object, today: str) -> str:
    if not isinstance(due, str) or not ledger._is_date(due):
        raise Refused("date")
    if not today <= due <= schedule.add_days(today, 3660):
        raise Refused("date")
    return due


def check_amount(amount: object) -> int:
    if not isinstance(amount, int) or isinstance(amount, bool) or not 0 < amount <= ledger.MAX_AMOUNT:
        raise Refused("bad_amount")
    return amount


class Service:
    def __init__(self, db: Database, invite_days: int = 7, clock: Callable[[], datetime] = utcnow) -> None:
        self.db, self.invite_days, self.clock = db, invite_days, clock

    def today(self) -> str:
        return schedule.local_today(self.clock())

    async def touch_user(self, uid: int, first_name: str, lang_code: str | None) -> dict:
        user = await self.db.user(uid)
        if user is None:
            lang = "ru" if (lang_code or "").startswith("ru") else "uz"
            name = " ".join(_CONTROL.sub(" ", first_name or "").split())[:NAME_MAX] or f"#{uid}"
            await self.db.upsert_user(uid, name, lang, stamp(self.clock()))
            user = await self.db.user(uid)
        return user

    async def chain(self, me: int, other: int) -> tuple[str, list[dict], dict]:
        pair = ledger.pair_key(me, other)
        entries = await self.db.entries(pair)
        return pair, entries, ledger.fold(entries)

    async def _append(self, me: int, other: int, body: dict) -> tuple[dict, dict]:
        """Validate against the current chain and store, under the write lock."""
        async with self.db.lock:
            pair, _, state = await self.chain(me, other)
            try:
                entry = ledger.append(state, pair, {**body, "at": stamp(self.clock())})
            except ledger.LedgerError as err:
                raise Refused(err.code) from err
            await self.db.insert_entry(entry)
        return entry, state

    # ── creating debts ──
    async def propose_debt(self, me: int, *, direction: str, amount: int, cur: str, due: str, note: str = "",
                           other: int | None = None, name: str | None = None) -> dict:
        if direction not in ("lent", "borrowed"):
            raise Refused("generic")
        if cur not in ledger.CURRENCIES:
            raise Refused("bad_amount")
        body = {"kind": "debt", "amount": check_amount(amount), "cur": cur, "due": check_due(due, self.today()),
                "note": clean_note(note)}
        if other is None:
            label = clean_name(name)
            token = new_invite_token()
            now = self.clock()
            await self.db.add_invite(token_digest(token), me, {**body, "direction": direction, "name": label},
                                     stamp(now), stamp(now + timedelta(days=self.invite_days)))
            return {"token": token, "name": label}
        if other not in await self.db.partners(me):
            raise Refused("not_found")
        lender, borrower = (me, other) if direction == "lent" else (other, me)
        entry, _ = await self._append(me, other, {**body, "by": me, "lender": lender, "borrower": borrower})
        return {"entry": entry, "other": other}

    async def open_invite(self, me: int, token: str) -> dict:
        """The counterparty opened ``t.me/<bot>?start=d_<token>``: the debt enters their shared chain."""
        if not isinstance(token, str) or not TOKEN_RE.match(token):
            raise Refused("link_used")
        digest = token_digest(token)
        if await self.db.invite_creator(digest) == me:
            raise Refused("own_link")
        invite = await self.db.take_invite(digest, me, stamp(self.clock()))
        if invite is None:
            raise Refused("link_used")
        creator, p = invite["creator"], invite["payload"]
        lender, borrower = (creator, me) if p["direction"] == "lent" else (me, creator)
        body = {k: p[k] for k in ("kind", "amount", "cur", "due", "note")}
        entry, _ = await self._append(creator, me, {**body, "by": creator, "lender": lender, "borrower": borrower})
        await self.db.set_label(creator, me, p["name"])
        return {"entry": entry, "other": creator}

    # ── answering and changing ──
    async def answer(self, me: int, other: int, ref: int, confirm: bool, reason: str | None = None) -> dict:
        body: dict = {"kind": "confirm" if confirm else "reject", "by": me, "ref": int(ref)}
        if not confirm:
            body["reason"] = clean_note(reason, ledger.REASON_MAX, "reason", required=True)
        entry, state = await self._append(me, other, body)
        prop = state["props"][int(ref)]
        debt = state["debts"][prop["ref"]]
        if confirm and debt["status"] == "active" and prop["kind"] in ("debt", "correction"):
            await self.schedule_reminders(entry["pair"], debt)
        return {"entry": entry, "prop": prop, "debt": debt}

    async def propose_change(self, me: int, other: int, debt_seq: int, kind: str, *, amount: int | None = None,
                             due: str | None = None) -> dict:
        if kind not in ("payment", "correction", "writeoff"):
            raise Refused("generic")
        body: dict = {"kind": kind, "by": me, "ref": int(debt_seq)}
        if amount is not None:
            body["amount"] = check_amount(amount)
        if due is not None:
            body["due"] = check_due(due, self.today())
        entry, state = await self._append(me, other, body)
        return {"entry": entry, "prop": state["props"][entry["seq"]], "debt": state["debts"][int(debt_seq)]}

    async def schedule_reminders(self, pair: str, debt: dict) -> None:
        rows = []
        for r in schedule.reminder_plan(debt["due"], self.today()):
            for uid in (debt["lender"], debt["borrower"]):
                rows.append((pair, debt["seq"], r["key"], uid, schedule.fire_at(r["date"])))
        await self.db.add_reminders(rows)

    # ── reading ──
    async def summary(self, me: int) -> dict:
        labels = await self.db.labels(me)
        states = {}
        for other in labels:
            states[other] = (await self.chain(me, other))[2]
        out = balance.summary(states, me)
        out["names"] = labels
        out["pending"] = await self.pending_for(me, states=states, labels=labels)
        return out

    async def pending_for(self, me: int, states: dict | None = None, labels: dict | None = None) -> list[dict]:
        labels = labels if labels is not None else await self.db.labels(me)
        items = []
        for other, name in labels.items():
            state = states[other] if states else (await self.chain(me, other))[2]
            for prop in state["props"].values():
                if prop["status"] == "pending" and prop["by"] != me:
                    items.append({"other": other, "name": name, "prop": prop, "debt": state["debts"][prop["ref"]]})
        return sorted(items, key=lambda x: x["prop"]["at"])

    async def person(self, me: int, other: int) -> dict:
        labels = await self.db.labels(me)
        if other not in labels:
            raise Refused("not_found")
        _, entries, state = await self.chain(me, other)
        return {
            "other": other, "name": labels[other], "net": balance.pair_balance(state, me),
            "debts": [balance.debt_view(d, me) for d in state["debts"].values()],
            "props": list(state["props"].values()), "verify": ledger.verify_chain(entries), "entries": entries,
        }

    async def verify(self, me: int, other: int) -> dict:
        _, entries, _ = await self.chain(me, other)
        return ledger.verify_chain(entries)


def parse_day(text: str) -> str | None:
    """``25.12.2026`` / ``25/12/2026`` / ``2026-12-25`` -> ISO date, or None."""
    m = re.fullmatch(r"\s*(\d{1,2})[./-](\d{1,2})[./-](\d{4})\s*", text or "")
    try:
        if m:
            return date(int(m[3]), int(m[2]), int(m[1])).isoformat()
        return date.fromisoformat((text or "").strip()).isoformat()
    except ValueError:
        return None
