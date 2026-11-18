"""Balances from folded ledger states (pure).

Only confirmed, still-open debts count. Positive = the other person owes me, negative = I owe them.
"""

from __future__ import annotations

from .ledger import CURRENCIES


def remaining(debt: dict) -> int:
    return debt["principal"] - debt["paid"]


def pair_balance(state: dict, me: int) -> dict[str, int]:
    """Net per currency between ``me`` and the other side of this chain (zero currencies omitted)."""
    net: dict[str, int] = {}
    for debt in state["debts"].values():
        if debt["status"] != "active":
            continue
        sign = 1 if debt["lender"] == me else -1
        net[debt["cur"]] = net.get(debt["cur"], 0) + sign * remaining(debt)
    return {cur: v for cur, v in sorted(net.items()) if v != 0}


def summary(states: dict[int, dict], me: int) -> dict:
    """Totals across every person: ``{"people": {id: {cur: net}}, "owed_to_me": {...}, "i_owe": {...}}``.

    Totals are computed from per-person nets, so if Ali owes Vali 100 and Vali owes Ali 30, Ali sees
    "I owe 70", not both numbers.
    """
    people: dict[int, dict[str, int]] = {}
    owed = {cur: 0 for cur in CURRENCIES}
    owe = {cur: 0 for cur in CURRENCIES}
    for other in sorted(states):
        net = pair_balance(states[other], me)
        people[other] = net
        for cur, v in net.items():
            if v > 0:
                owed[cur] += v
            else:
                owe[cur] += -v
    return {"people": people, "owed_to_me": owed, "i_owe": owe}


def debt_view(debt: dict, me: int) -> dict:
    """A compact, JSON-friendly view of one debt from ``me``'s side."""
    return {
        "seq": debt["seq"],
        "role": "lender" if debt["lender"] == me else "borrower",
        "cur": debt["cur"],
        "principal": debt["principal"],
        "paid": debt["paid"],
        "remaining": remaining(debt),
        "due": debt["due"],
        "note": debt["note"],
        "status": debt["status"],
        "seal": debt["seal"],
    }
