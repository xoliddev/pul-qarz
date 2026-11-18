"""Dispatcher wiring: rate limiting, user registration, error replies and the screen helper."""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import ExceptionTypeFilter
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, ErrorEvent, Message, TelegramObject, Update

from ..core.schedule import add_days
from ..i18n import day, t
from ..security import RateLimiter
from ..service import Refused, Service
from .notify import Notifier

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BotConfig:
    bot_username: str
    webapp_url: str = ""


async def show(event: CallbackQuery | Message, screen: tuple) -> None:
    """Show a screen: edit the message behind a button, or send a new message after typed input."""
    text, markup = screen
    if isinstance(event, CallbackQuery):
        await event.answer()
        if isinstance(event.message, Message):
            try:
                await event.message.edit_text(text, reply_markup=markup)
                return
            except TelegramBadRequest as err:
                if "not modified" in str(err):
                    return
        await event.bot.send_message(event.from_user.id, text, reply_markup=markup)
    else:
        await event.answer(text, reply_markup=markup)


def build_dispatcher(service: Service, bot: Bot, cfg: BotConfig, rate_per_minute: int = 30) -> Dispatcher:
    from . import handlers_create, handlers_debt, handlers_main

    dp = Dispatcher(storage=MemoryStorage())
    limiter = RateLimiter(rate_per_minute)
    notifier = Notifier(bot, service)

    async def context(handler, event: TelegramObject, data: dict[str, Any]):
        user = data.get("event_from_user")
        if user is None or user.is_bot:
            return None
        if not limiter.allow(user.id):
            inner = event.callback_query if isinstance(event, Update) else None
            if inner is not None:
                rec = await service.db.user(user.id)
                await inner.answer(t((rec or {}).get("lang", "uz"), "err.rate"))
            return None
        record = await service.touch_user(user.id, user.first_name or "", user.language_code)
        data.update(me=user.id, lang=record["lang"], svc=service, notifier=notifier, cfg=cfg)
        return await handler(event, data)

    dp.update.outer_middleware(context)

    async def refused(event: ErrorEvent) -> None:
        err: Refused = event.exception  # type: ignore[assignment]
        upd = event.update
        target = upd.callback_query or upd.message
        if target is None or target.from_user is None:
            return
        rec = await service.db.user(target.from_user.id)
        lang = (rec or {}).get("lang", "uz")
        example = day(add_days(service.today(), 30))
        text = t(lang, f"err.{err.code}", example=example)
        if text == f"err.{err.code}":
            text = t(lang, "err.generic")
        if isinstance(target, CallbackQuery):
            await target.answer(html.unescape(re.sub(r"<[^>]+>", "", text)), show_alert=True)
        else:
            await target.answer(text)

    dp.errors.register(refused, ExceptionTypeFilter(Refused))
    dp.include_routers(handlers_main.router, handlers_create.router, handlers_debt.router, handlers_main.fallback)
    return dp
