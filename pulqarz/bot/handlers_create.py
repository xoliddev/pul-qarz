"""Creating a debt, step by step with buttons: who -> (name) -> amount -> currency -> due -> note -> review.
"Back" returns to the previous step; typed input is only expected where a step asks for it."""

from __future__ import annotations

from urllib.parse import urlencode

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message

from ..core.money import MoneyError, parse_amount
from ..core.schedule import add_days
from ..i18n import day, money, t
from ..service import Refused, Service, check_due, clean_name, clean_note, parse_day
from . import views
from .cb import CURRENCY, DUE_DAYS, Cur, Due, Nav, Step, Who
from .handlers_main import menu_screen
from .notify import Notifier
from .setup import BotConfig, show

router = Router(name="create")


class CreateFlow(StatesGroup):
    name = State()
    amount = State()
    due = State()
    note = State()


TYPED = {"name": CreateFlow.name, "amount": CreateFlow.amount, "due_text": CreateFlow.due, "note": CreateFlow.note}


async def stage_screen(stage: str, data: dict, svc: Service, me: int, lang: str):
    b, cancel = views.btn, views.cancel_row(lang)
    if stage == "who":
        rows = [[b(name[:40], Who(uid=uid))] for uid, name in list((await svc.db.labels(me)).items())[:10]]
        rows.append([b(t(lang, "btn.new_person"), Who(uid=0))])
        return t(lang, f"create.who_{data['direction']}"), views.kb(*rows, views.back(lang, Nav(to="menu")))
    if stage == "cur":
        return t(lang, "create.currency"), views.kb([b(t(lang, f"btn.{c}"), Cur(cur=c)) for c in ("UZS", "USD")],
                                                    cancel)
    if stage == "due":
        rows = [[b(t(lang, f"btn.due{n}"), Due(days=n)) for n in (7, 14, 30)],
                [b(t(lang, "btn.due_type"), Due(days=0))]]
        return t(lang, "create.due"), views.kb(*rows, cancel)
    if stage == "note":
        return t(lang, "create.note"), views.kb([b(t(lang, "btn.skip"), Step(act="skip"))], cancel)
    if stage == "review":
        text = t(lang, "create.review", direction=t(lang, f"dir.{data['direction']}"), name=data["name"],
                 amount=money(lang, data["amount"], data["cur"]), due=day(data["due"]), note=data.get("note") or "—")
        return text, views.kb([b(t(lang, "btn.send"), Step(act="send"))], cancel)
    example = day(add_days(svc.today(), 30))
    key = {"name": "create.name", "amount": "create.amount", "due_text": "create.due_type"}[stage]
    return t(lang, key, example=example), views.kb(cancel)


async def go(event, state: FSMContext, stage: str, svc: Service, me: int, lang: str, push: bool = True) -> None:
    data = await state.get_data()
    trail = list(data.get("trail", []))
    if push:
        trail.append(stage)
    await state.set_state(TYPED.get(stage))
    await state.update_data(trail=trail)
    await show(event, await stage_screen(stage, {**data, "trail": trail}, svc, me, lang))


@router.callback_query(Nav.filter(F.to.in_({"lent", "borrowed"})))
async def begin(cq: CallbackQuery, callback_data: Nav, state: FSMContext, svc: Service, me: int, lang: str) -> None:
    await state.clear()
    await state.set_data({"direction": callback_data.to, "trail": []})
    await go(cq, state, "who", svc, me, lang)


@router.callback_query(Who.filter(F.uid >= 0))
async def who(cq: CallbackQuery, callback_data: Who, state: FSMContext, svc: Service, me: int, lang: str) -> None:
    if "direction" not in await state.get_data():
        raise Refused("stale")
    if callback_data.uid == 0:
        await state.update_data(other=None)
        await go(cq, state, "name", svc, me, lang)
        return
    labels = await svc.db.labels(me)
    if callback_data.uid not in labels:
        raise Refused("not_found")
    await state.update_data(other=callback_data.uid, name=labels[callback_data.uid])
    await go(cq, state, "amount", svc, me, lang)


@router.message(StateFilter(CreateFlow.name), F.text)
async def typed_name(msg: Message, state: FSMContext, svc: Service, me: int, lang: str) -> None:
    await state.update_data(name=clean_name(msg.text))
    await go(msg, state, "amount", svc, me, lang)


@router.message(StateFilter(CreateFlow.amount), F.text)
async def typed_amount(msg: Message, state: FSMContext, svc: Service, me: int, lang: str) -> None:
    try:
        amount = parse_amount(msg.text)
    except MoneyError as err:
        raise Refused("amount") from err
    await state.update_data(amount=amount)
    await go(msg, state, "cur", svc, me, lang)


@router.callback_query(Cur.filter(F.cur.in_(CURRENCY)))
async def currency(cq: CallbackQuery, callback_data: Cur, state: FSMContext, svc: Service, me: int, lang: str):
    if "amount" not in await state.get_data():
        raise Refused("stale")
    await state.update_data(cur=callback_data.cur)
    await go(cq, state, "due", svc, me, lang)


@router.callback_query(Due.filter(F.days.in_(DUE_DAYS)))
async def due(cq: CallbackQuery, callback_data: Due, state: FSMContext, svc: Service, me: int, lang: str) -> None:
    if "cur" not in await state.get_data():
        raise Refused("stale")
    if callback_data.days == 0:
        await go(cq, state, "due_text", svc, me, lang)
        return
    await state.update_data(due=add_days(svc.today(), callback_data.days))
    await go(cq, state, "note", svc, me, lang)


@router.message(StateFilter(CreateFlow.due), F.text)
async def typed_due(msg: Message, state: FSMContext, svc: Service, me: int, lang: str) -> None:
    await state.update_data(due=check_due(parse_day(msg.text), svc.today()))
    await go(msg, state, "note", svc, me, lang)


@router.message(StateFilter(CreateFlow.note), F.text)
async def typed_note(msg: Message, state: FSMContext, svc: Service, me: int, lang: str) -> None:
    await state.update_data(note=clean_note(msg.text))
    await go(msg, state, "review", svc, me, lang)


@router.callback_query(Step.filter(F.act.in_({"back", "cancel", "skip", "send"})))
async def step(cq: CallbackQuery, callback_data: Step, state: FSMContext, svc: Service, me: int, lang: str,
               notifier: Notifier, cfg: BotConfig) -> None:
    data = await state.get_data()
    act = callback_data.act
    if act == "cancel" or "direction" not in data:
        await state.clear()
        await show(cq, await menu_screen(svc, me, lang, cfg))
    elif act == "back":
        trail = list(data.get("trail", []))[:-1]
        if not trail:
            await state.clear()
            await show(cq, await menu_screen(svc, me, lang, cfg))
            return
        await state.update_data(trail=trail)
        await go(cq, state, trail[-1], svc, me, lang, push=False)
    elif act == "skip":
        await state.update_data(note="")
        await go(cq, state, "review", svc, me, lang)
    elif {"amount", "cur", "due", "name"} <= data.keys():
        await state.clear()
        await send(cq, data, svc, me, lang, notifier, cfg)
    else:
        raise Refused("stale")


async def send(cq: CallbackQuery, data: dict, svc: Service, me: int, lang: str, notifier: Notifier,
               cfg: BotConfig) -> None:
    res = await svc.propose_debt(me, direction=data["direction"], amount=data["amount"], cur=data["cur"],
                                 due=data["due"], note=data.get("note", ""), other=data.get("other"), name=data["name"])
    back = views.back(lang, Nav(to="menu"))
    if "token" in res:
        link = f"https://t.me/{cfg.bot_username}?start=d_{res['token']}"
        share = "https://t.me/share/url?" + urlencode({"url": link, "text": t(lang, "share.text")})
        markup = views.kb([InlineKeyboardButton(text=t(lang, "btn.share"), url=share)], back)
        await show(cq, (t(lang, "create.link", name=res["name"], link=link), markup))
        return
    await show(cq, (t(lang, "create.sent", name=data["name"]), views.kb(back)))
    entry = res["entry"]
    _, _, st = await svc.chain(me, res["other"])
    await notifier.ask(res["other"], me, st["props"][entry["seq"]], st["debts"][entry["seq"]])
