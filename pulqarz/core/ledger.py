"""The append-only ledger between two people (pure, no I/O).

A pair of users shares one hash chain. Every action is a new entry; nothing is ever edited:

* proposals: ``debt``, ``payment``, ``correction``, ``writeoff``
* answers:   ``confirm`` or ``reject`` (by the other side only)

A proposal changes balances only after the other side confirms it. The confirm entry's hash becomes the
visible seal ("muhr"). ``fold`` replays the chain and enforces every rule, so a chain that was rewritten
with valid hashes but broken rules is still rejected.
"""

from __future__ import annotations

import copy
import re
from datetime import date

from .canon import GENESIS, entry_hash, seal

CURRENCIES = ("UZS", "USD")
PROPOSALS = ("debt", "payment", "correction", "writeoff")
ANSWERS = ("confirm", "reject")
MAX_AMOUNT = 10**15  # minor units
NOTE_MAX = 200
REASON_MAX = 200
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class LedgerError(ValueError):
    """A rule was broken. ``code`` is a stable key used for localized messages."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def pair_key(a: int, b: int) -> str:
    if a == b:
        raise LedgerError("same_person")
    lo, hi = sorted((int(a), int(b)))
    return f"{lo}:{hi}"


def parties(pair: str) -> tuple[int, int]:
    lo, hi = pair.split(":")
    return int(lo), int(hi)


def _is_date(value: object) -> bool:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _amount(value: object, upto: int = MAX_AMOUNT) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0 or value > upto:
        raise LedgerError("bad_amount")
    return value


def new_state() -> dict:
    return {"debts": {}, "props": {}, "pending": {}, "head": GENESIS, "seq": 0}


def _active_debt(state: dict, ref: object) -> dict:
    debt = state["debts"].get(ref) if isinstance(ref, int) else None
    if debt is None or debt["status"] != "active":
        raise LedgerError("debt_not_active")
    if ref in state["pending"]:
        raise LedgerError("change_pending")
    return debt


def apply(state: dict, entry: dict) -> None:
    """Apply one entry to ``state`` (mutates). Raises ``LedgerError`` if any rule is broken."""
    kind, by, seq = entry.get("kind"), entry.get("by"), entry["seq"]
    if by not in parties(entry["pair"]):
        raise LedgerError("not_a_party")
    if not isinstance(entry.get("at"), str) or not _TIME_RE.match(entry["at"]):
        raise LedgerError("bad_time")
    if kind == "debt":
        lender, borrower = entry.get("lender"), entry.get("borrower")
        if {lender, borrower} != set(parties(entry["pair"])) or by not in (lender, borrower):
            raise LedgerError("bad_parties")
        if entry.get("cur") not in CURRENCIES:
            raise LedgerError("bad_currency")
        if not _is_date(entry.get("due")):
            raise LedgerError("bad_date")
        note = entry.get("note", "")
        if not isinstance(note, str) or len(note) > NOTE_MAX:
            raise LedgerError("bad_note")
        state["debts"][seq] = {
            "seq": seq, "lender": lender, "borrower": borrower, "cur": entry["cur"],
            "principal": _amount(entry.get("amount")), "paid": 0, "due": entry["due"], "note": note,
            "status": "pending", "seal": None, "at": entry["at"], "by": by,
        }
        state["props"][seq] = {"seq": seq, "kind": kind, "by": by, "ref": seq, "status": "pending"}
        state["pending"][seq] = seq
    elif kind in ("payment", "correction", "writeoff"):
        ref = entry.get("ref")
        debt = _active_debt(state, ref)
        prop = {"seq": seq, "kind": kind, "by": by, "ref": ref, "status": "pending"}
        if kind == "payment":
            prop["amount"] = _amount(entry.get("amount"), debt["principal"] - debt["paid"])
        elif kind == "correction":
            amount, due = entry.get("amount"), entry.get("due")
            if amount is None and due is None:
                raise LedgerError("nothing_to_change")
            if amount is not None:
                if _amount(amount) <= debt["paid"] or amount == debt["principal"]:
                    raise LedgerError("bad_amount")
                prop["amount"] = amount
            if due is not None:
                if not _is_date(due) or due == debt["due"]:
                    raise LedgerError("bad_date")
                prop["due"] = due
        elif by != debt["lender"]:
            raise LedgerError("only_lender")
        state["props"][seq] = prop
        state["pending"][ref] = seq
    elif kind in ANSWERS:
        _answer(state, entry)
    else:
        raise LedgerError("bad_kind")


def _answer(state: dict, entry: dict) -> None:
    ref = entry.get("ref")
    prop = state["props"].get(ref) if isinstance(ref, int) else None
    if prop is None or prop["status"] != "pending":
        raise LedgerError("not_pending")
    if entry["by"] == prop["by"]:
        raise LedgerError("own_proposal")
    debt = state["debts"][prop["ref"]]
    del state["pending"][prop["ref"]]
    if entry["kind"] == "reject":
        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > REASON_MAX:
            raise LedgerError("bad_reason")
        prop["status"], prop["reason"], prop["answer"] = "rejected", reason, entry["seq"]
        if prop["kind"] == "debt":
            debt["status"] = "rejected"
        return
    prop["status"], prop["answer"] = "confirmed", entry["seq"]
    prop["seal"] = seal(entry["hash"])
    if prop["kind"] == "debt":
        debt["status"], debt["seal"] = "active", prop["seal"]
    elif prop["kind"] == "payment":
        debt["paid"] += prop["amount"]
        if debt["paid"] == debt["principal"]:
            debt["status"] = "closed"
    elif prop["kind"] == "correction":
        debt["principal"] = prop.get("amount", debt["principal"])
        debt["due"] = prop.get("due", debt["due"])
    else:
        debt["status"] = "written_off"


def make_entry(state: dict, pair: str, body: dict) -> dict:
    """Build the next entry for this chain (adds v, pair, seq, prev and hash)."""
    full = {k: v for k, v in body.items() if v is not None}
    full.update({"v": 1, "pair": pair, "seq": state["seq"] + 1, "prev": state["head"]})
    full["hash"] = entry_hash(full["prev"], {k: v for k, v in full.items() if k != "hash"})
    return full


def append(state: dict, pair: str, body: dict) -> dict:
    """Validate and apply a new entry; returns it. ``state`` is left unchanged on error."""
    entry = make_entry(state, pair, body)
    trial = fold_from(state, [entry])
    state.clear()
    state.update(trial)
    return entry


def fold_from(state: dict, entries: list[dict]) -> dict:
    out = copy.deepcopy(state)
    for e in entries:
        apply(out, e)
        out["head"], out["seq"] = e["hash"], e["seq"]
    return out


def fold(entries: list[dict]) -> dict:
    """Replay a whole chain (assumes ``verify_chain`` passed)."""
    return fold_from(new_state(), entries)


def verify_chain(entries: list[dict]) -> dict:
    """Check links, hashes and rules. Returns ``{"ok": True, "count": n, "head": h}`` or the broken link."""
    state, prev = new_state(), GENESIS
    pair = entries[0].get("pair") if entries else None
    for i, e in enumerate(entries, start=1):
        body = {k: v for k, v in e.items() if k != "hash"}
        try:
            if e.get("seq") != i or e.get("pair") != pair or e.get("v") != 1:
                return {"ok": False, "seq": i, "reason": "order"}
            if e.get("prev") != prev:
                return {"ok": False, "seq": i, "reason": "link"}
            if entry_hash(prev, body) != e.get("hash"):
                return {"ok": False, "seq": i, "reason": "hash"}
            apply(state, e)
        except (LedgerError, TypeError, ValueError, KeyError):
            return {"ok": False, "seq": i, "reason": "rule"}
        prev = e["hash"]
        state["head"], state["seq"] = prev, i
    return {"ok": True, "count": len(entries), "head": prev}
