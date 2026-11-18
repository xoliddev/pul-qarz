"""Messages the bot sends to the *other* side: a question to confirm, the answer, and reminders.
Used by both the bot handlers and the Mini App API, so both paths notify in the same words."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from ..i18n import t
from ..service import Service
from . import views

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, bot: Bot, service: Service) -> None:
        self.bot, self.svc = bot, service

    async def _who(self, to: int, about: int) -> tuple[str, str]:
        """Recipient's language, and the name the recipient uses for ``about``."""
        user = await self.svc.db.user(to)
        names = await self.svc.db.labels(to)
        return (user or {}).get("lang", "uz"), names.get(about, f"#{about}")

    async def _send(self, to: int, text: str, markup=None) -> None:
        try:
            await self.bot.send_message(to, text, reply_markup=markup)
        except TelegramAPIError:  # the user blocked the bot or never started it: the ledger is still correct
            log.warning("could not notify user %s", to)

    async def ask(self, to: int, sender: int, prop: dict, debt: dict) -> None:
        lang, name = await self._who(to, sender)
        text, markup = views.ask(lang, name, sender, prop, debt)
        await self._send(to, text, markup)

    async def answered(self, to: int, sender: int, prop: dict, reason: str | None = None) -> None:
        lang, name = await self._who(to, sender)
        what = views.what(lang, prop)
        if prop["status"] == "confirmed":
            text = t(lang, "notify.confirmed", name=name, what=views.Raw(what), seal=prop["seal"])
        else:
            text = t(lang, "notify.rejected", name=name, what=views.Raw(what), reason=prop.get("reason", reason))
        await self._send(to, text, views.kb(views.back(lang, views.Nav(to="menu"))))

    async def reminder(self, to: int, other: int, debt: dict, kind: str) -> None:
        lang, name = await self._who(to, other)
        text = views.reminder(lang, name, debt, kind, to, self.svc.today())
        markup = views.kb([views.btn(t(lang, "btn.open"), views.Debt(uid=other, seq=debt["seq"], act="open"))])
        await self.bot.send_message(to, text, reply_markup=markup)
