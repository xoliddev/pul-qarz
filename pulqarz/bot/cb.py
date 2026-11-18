"""Callback data. aiogram parses and type-checks every field (ints stay ints); handlers then filter the
allowed values, and anything else falls through to the "stale button" handler. Nothing in callback data is
trusted for authorization: the service re-checks that the user is a party of the debt on every action."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData

NAV_TARGETS = {"menu", "balance", "people", "pending", "lang", "lent", "borrowed"}
STEP_ACTIONS = {"back", "cancel", "skip", "send"}
PERSON_VIEWS = {"open", "hist", "verify"}
DEBT_ACTIONS = {"open", "pay", "payfull", "correct", "camount", "cdue", "ext7", "ext30", "dtype", "wo", "woyes"}
REASONS = {"amount", "none", "date", "type"}
CURRENCY = {"UZS", "USD"}
DUE_DAYS = {0, 7, 14, 30}


class Nav(CallbackData, prefix="n"):
    to: str


class Who(CallbackData, prefix="w"):
    uid: int  # 0 = a new person, invited by link


class Cur(CallbackData, prefix="c"):
    cur: str


class Due(CallbackData, prefix="d"):
    days: int  # 0 = "I'll type the date"


class Step(CallbackData, prefix="s"):
    act: str


class Per(CallbackData, prefix="p"):
    uid: int
    view: str


class Debt(CallbackData, prefix="b"):
    uid: int
    seq: int
    act: str


class Ans(CallbackData, prefix="a"):
    uid: int
    seq: int
    ok: int  # 1 = confirm, 0 = reject, 2 = show the question again


class Why(CallbackData, prefix="r"):
    uid: int
    seq: int
    code: str
