"""/start (with share links), menu, balance, people, history, chain check and answering proposals."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..i18n import t
from ..service import Refused, Service, clean_note
from . import views
from .cb import PERSON_VIEWS, Ans, Nav, Per, Why
from .notify import Notifier
from .setup import BotConfig, show

router = Router(name="main")
fallback = Router(name="fallback")


class RejectFlow(StatesGroup):
    reason = State()


async def menu_screen(svc: Service, me: int, lang: str, cfg: BotConfig, hello: bool = False):
    pending = await svc.pending_for(me)
    return views.main_menu(lang, len(pending), cfg.webapp_url, hello=hello)


@router.message(CommandStart(deep_link=True))
async def start_link(msg: Message, command: CommandObject, state: FSMContext, svc: Service, me: int, lang: str,
                     notifier: Notifier, cfg: BotConfig) -> None:
    await state.clear()
    args = command.args or ""
    if not args.startswith("d_"):
        await show(msg, await menu_screen(svc, me, lang, cfg, hello=True))
        return
    opened = await svc.open_invite(me, args[2:])
    creator = opened["other"]
    _, _, st = await svc.chain(me, creator)
    prop = st["props"][opened["entry"]["seq"]]
    name = (await svc.db.labels(me)).get(creator, "")
    await show(msg, views.ask(lang, name, creator, prop, st["debts"][prop["ref"]]))


@router.message(CommandStart())
async def start(msg: Message, state: FSMContext, svc: Service, me: int, lang: str, cfg: BotConfig) -> None:
    await state.clear()
    await show(msg, await menu_screen(svc, me, lang, cfg, hello=True))


@router.callback_query(Nav.filter(F.to.in_({"menu", "balance", "people", "pending", "lang"})))
async def nav(cq: CallbackQuery, callback_data: Nav, state: FSMContext, svc: Service, me: int, lang: str,
              cfg: BotConfig) -> None:
    await state.clear()
    to = callback_data.to
    if to == "lang":
        lang = "ru" if lang == "uz" else "uz"
        await svc.db.set_lang(me, lang)
        to = "menu"
    if to == "menu":
        await show(cq, await menu_screen(svc, me, lang, cfg))
    elif to == "pending":
        await show(cq, views.pending(lang, await svc.pending_for(me)))
    else:
        s = await svc.summary(me)
        await show(cq, views.balance(lang, s) if to == "balance" else views.people(lang, s))


@router.callback_query(Per.filter(F.view.in_(PERSON_VIEWS)))
async def person(cq: CallbackQuery, callback_data: Per, state: FSMContext, svc: Service, me: int, lang: str) -> None:
    await state.clear()
    p = await svc.person(me, callback_data.uid)  # refuses anyone who is not my partner
    if callback_data.view == "hist":
        await show(cq, views.history(lang, p))
    elif callback_data.view == "verify":
        await show(cq, views.verify(lang, p["other"], p["verify"]))
    else:
        await show(cq, views.person(lang, p, svc.today()))


async def _pending_prop(svc: Service, me: int, other: int, seq: int) -> tuple[dict, dict, str]:
    _, _, st = await svc.chain(me, other)
    prop = st["props"].get(seq)
    if prop is None or prop["status"] != "pending":
        raise Refused("not_pending")
    if prop["by"] == me:
        raise Refused("own_proposal")
    name = (await svc.db.labels(me)).get(other, "")
    return prop, st["debts"][prop["ref"]], name


@router.callback_query(Ans.filter(F.ok.in_({0, 1, 2})))
async def answer(cq: CallbackQuery, callback_data: Ans, svc: Service, me: int, lang: str,
                 notifier: Notifier) -> None:
    other, seq = callback_data.uid, callback_data.seq
    prop, debt, name = await _pending_prop(svc, me, other, seq)
    if callback_data.ok == 2:
        await show(cq, views.ask(lang, name, other, prop, debt))
    elif callback_data.ok == 0:
        await show(cq, views.reasons(lang, other, seq))
    else:
        out = await svc.answer(me, other, seq, confirm=True)
        await show(cq, views.done(lang, t(lang, "done.confirmed", seal=out["prop"]["seal"])))
        await notifier.answered(other, me, out["prop"])


async def _reject(event, svc: Service, me: int, lang: str, notifier: Notifier, other: int, seq: int, reason: str):
    out = await svc.answer(me, other, seq, confirm=False, reason=reason)
    name = (await svc.db.labels(me)).get(other, "")
    await show(event, views.done(lang, t(lang, "done.rejected", name=name)))
    await notifier.answered(other, me, out["prop"])


@router.callback_query(Why.filter(F.code.in_({"amount", "none", "date", "type"})))
async def why(cq: CallbackQuery, callback_data: Why, state: FSMContext, svc: Service, me: int, lang: str,
              notifier: Notifier) -> None:
    other, seq = callback_data.uid, callback_data.seq
    await _pending_prop(svc, me, other, seq)
    if callback_data.code == "type":
        await state.set_state(RejectFlow.reason)
        await state.set_data({"uid": other, "seq": seq})
        await show(cq, (t(lang, "reject.type"), views.kb(views.back(lang, Ans(uid=other, seq=seq, ok=0)))))
        return
    await _reject(cq, svc, me, lang, notifier, other, seq, t(lang, f"reason.{callback_data.code}"))


@router.message(StateFilter(RejectFlow.reason), F.text)
async def why_typed(msg: Message, state: FSMContext, svc: Service, me: int, lang: str, notifier: Notifier) -> None:
    data = await state.get_data()
    reason = clean_note(msg.text, 200, "reason", required=True)
    await _reject(msg, svc, me, lang, notifier, int(data["uid"]), int(data["seq"]), reason)
    await state.clear()


@fallback.callback_query()
async def stale(cq: CallbackQuery, lang: str) -> None:
    await cq.answer(t(lang, "err.stale"), show_alert=True)


@fallback.message()
async def stray(msg: Message, svc: Service, me: int, lang: str, cfg: BotConfig) -> None:
    """Free text outside a flow: just show the menu (the bot is driven by buttons)."""
    await show(msg, await menu_screen(svc, me, lang, cfg))
