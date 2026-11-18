"""One debt: card, payment, correction (amount or due date) and write-off. Each change is a new proposal
that the other side must confirm."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..core.money import MoneyError, parse_amount
from ..core.schedule import add_days
from ..i18n import day, money, t
from ..service import Refused, Service, parse_day
from . import views
from .cb import DEBT_ACTIONS, Debt
from .notify import Notifier
from .setup import show

router = Router(name="debt")


class DebtFlow(StatesGroup):
    pay = State()
    amount = State()
    due = State()


async def load(svc: Service, me: int, uid: int, seq: int) -> tuple[dict, bool, str]:
    p = await svc.person(me, uid)  # refuses anyone who is not a party
    debt = next((d for d in p["debts"] if d["seq"] == seq), None)
    if debt is None:
        raise Refused("not_found")
    waiting = any(x["ref"] == seq and x["status"] == "pending" for x in p["props"])
    return debt, waiting, p["name"]


async def propose(event, svc: Service, me: int, lang: str, notifier: Notifier, uid: int, seq: int, kind: str,
                  **kw) -> None:
    out = await svc.propose_change(me, uid, seq, kind, **kw)
    name = (await svc.db.labels(me)).get(uid, "")
    key = {"payment": "pay.sent", "correction": "correct.sent", "writeoff": "writeoff.sent"}[kind]
    await show(event, (t(lang, key, name=name), views.kb(views.back(lang, Debt(uid=uid, seq=seq, act="open")))))
    await notifier.ask(uid, me, out["prop"], out["debt"])


@router.callback_query(Debt.filter(F.act.in_(DEBT_ACTIONS)))
async def debt_action(cq: CallbackQuery, callback_data: Debt, state: FSMContext, svc: Service, me: int, lang: str,
                      notifier: Notifier) -> None:
    uid, seq, act = callback_data.uid, callback_data.seq, callback_data.act
    await state.clear()
    debt, waiting, name = await load(svc, me, uid, seq)
    back = views.back(lang, Debt(uid=uid, seq=seq, act="open"))
    b = views.btn
    if act == "open":
        await show(cq, views.debt_card(lang, uid, debt, waiting, svc.today()))
        return
    if waiting or debt["status"] != "active":
        raise Refused("change_pending" if waiting else "debt_not_active")
    rem = money(lang, debt["remaining"], debt["cur"])
    if act == "pay":
        await state.set_state(DebtFlow.pay)
        await state.set_data({"uid": uid, "seq": seq})
        markup = views.kb([b(t(lang, "btn.pay_full", amount=rem), Debt(uid=uid, seq=seq, act="payfull"))], back)
        await show(cq, (t(lang, "pay.ask", remaining=rem), markup))
    elif act == "payfull":
        await propose(cq, svc, me, lang, notifier, uid, seq, "payment", amount=debt["remaining"])
    elif act == "correct":
        markup = views.kb([b(t(lang, "btn.correct_amount"), Debt(uid=uid, seq=seq, act="camount")),
                           b(t(lang, "btn.correct_due"), Debt(uid=uid, seq=seq, act="cdue"))], back)
        await show(cq, (t(lang, "correct.ask"), markup))
    elif act == "camount":
        await state.set_state(DebtFlow.amount)
        await state.set_data({"uid": uid, "seq": seq})
        text = t(lang, "correct.amount", amount=money(lang, debt["principal"], debt["cur"]),
                 paid=money(lang, debt["paid"], debt["cur"]))
        await show(cq, (text, views.kb(back)))
    elif act == "cdue":
        markup = views.kb([b(t(lang, "btn.ext7"), Debt(uid=uid, seq=seq, act="ext7")),
                           b(t(lang, "btn.ext30"), Debt(uid=uid, seq=seq, act="ext30"))],
                          [b(t(lang, "btn.due_type"), Debt(uid=uid, seq=seq, act="dtype"))], back)
        await show(cq, (t(lang, "correct.due", due=day(debt["due"])), markup))
    elif act in ("ext7", "ext30"):
        base = max(debt["due"], svc.today())
        new_due = add_days(base, 7 if act == "ext7" else 30)
        await propose(cq, svc, me, lang, notifier, uid, seq, "correction", due=new_due)
    elif act == "dtype":
        await state.set_state(DebtFlow.due)
        await state.set_data({"uid": uid, "seq": seq})
        await show(cq, (t(lang, "create.due_type", example=day(add_days(svc.today(), 30))), views.kb(back)))
    elif act == "wo":
        if debt["role"] != "lender":
            raise Refused("only_lender")
        markup = views.kb([b(t(lang, "btn.writeoff_yes"), Debt(uid=uid, seq=seq, act="woyes"))], back)
        await show(cq, (t(lang, "writeoff.ask", amount=rem, name=name), markup))
    elif act == "woyes":
        await propose(cq, svc, me, lang, notifier, uid, seq, "writeoff")


def _amount(text: str | None) -> int:
    try:
        return parse_amount(text or "")
    except MoneyError as err:
        raise Refused("amount") from err


@router.message(StateFilter(DebtFlow.pay), F.text)
async def typed_payment(msg: Message, state: FSMContext, svc: Service, me: int, lang: str, notifier: Notifier):
    data = await state.get_data()
    amount = _amount(msg.text)
    await propose(msg, svc, me, lang, notifier, int(data["uid"]), int(data["seq"]), "payment", amount=amount)
    await state.clear()


@router.message(StateFilter(DebtFlow.amount), F.text)
async def typed_new_amount(msg: Message, state: FSMContext, svc: Service, me: int, lang: str, notifier: Notifier):
    data = await state.get_data()
    amount = _amount(msg.text)
    await propose(msg, svc, me, lang, notifier, int(data["uid"]), int(data["seq"]), "correction", amount=amount)
    await state.clear()


@router.message(StateFilter(DebtFlow.due), F.text)
async def typed_new_due(msg: Message, state: FSMContext, svc: Service, me: int, lang: str, notifier: Notifier):
    data = await state.get_data()
    new_due = parse_day(msg.text or "")
    if new_due is None:
        raise Refused("date")
    await propose(msg, svc, me, lang, notifier, int(data["uid"]), int(data["seq"]), "correction", due=new_due)
    await state.clear()
