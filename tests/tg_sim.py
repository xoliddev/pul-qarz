"""A tiny Telegram simulator: real aiogram Dispatcher and handlers, mocked Bot API session.

Every outgoing call (sendMessage, editMessageText, answerCallbackQuery) is recorded, and each user's chat
is kept as a list of messages, so tests can "press" buttons by their visible text like a real person.
"""

from __future__ import annotations

import importlib
import itertools
import re
from datetime import UTC, datetime

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage, TelegramMethod
from aiogram.types import Chat, Message, Update, User

from pulqarz.bot import handlers_create, handlers_debt, handlers_main
from pulqarz.bot.setup import BotConfig, build_dispatcher
from pulqarz.service import Service

BOT_USER = User(id=4242, is_bot=True, first_name="Pul Qarz", username="pulqarz_test_bot")


class MockSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod] = []
        self.ids = itertools.count(1)
        self.chats: dict[int, list[dict]] = {}

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        self.calls.append(method)
        if isinstance(method, SendMessage):
            mid = next(self.ids)
            self.chats.setdefault(int(method.chat_id), []).append(
                {"id": mid, "text": method.text, "markup": method.reply_markup})
            return self._message(int(method.chat_id), mid, method.text)
        if isinstance(method, EditMessageText):
            for msg in self.chats.get(int(method.chat_id), []):
                if msg["id"] == method.message_id:
                    msg.update(text=method.text, markup=method.reply_markup)
            return self._message(int(method.chat_id), method.message_id, method.text)
        return True

    @staticmethod
    def _message(chat_id: int, mid: int, text: str) -> Message:
        return Message(message_id=mid, date=datetime.now(UTC), chat=Chat(id=chat_id, type="private"),
                       from_user=BOT_USER, text=text)

    async def close(self) -> None:
        return None

    async def stream_content(self, *args, **kwargs):  # pragma: no cover - not used
        raise NotImplementedError


def fresh_dispatcher(svc: Service, bot: Bot, cfg: BotConfig, rate_per_minute: int = 1000):
    """aiogram routers attach to one dispatcher only; tests build many, so reload the handler modules."""
    for mod in (handlers_main, handlers_create, handlers_debt):
        importlib.reload(mod)
    return build_dispatcher(svc, bot, cfg, rate_per_minute=rate_per_minute)


class TgSim:
    def __init__(self, svc: Service, webapp_url: str = "https://pulqarz.example/webapp/") -> None:
        self.session = MockSession()
        self.bot = Bot("4242:TEST-ONLY-TOKEN", session=self.session, default=DefaultBotProperties(parse_mode="HTML"))
        self.dp = fresh_dispatcher(svc, self.bot, BotConfig("pulqarz_test_bot", webapp_url))
        self.svc = svc
        self.updates = itertools.count(1)
        self.names = {1001: "Ali", 1002: "Vali", 1003: "Olim"}

    def user(self, uid: int) -> dict:
        return {"id": uid, "is_bot": False, "first_name": self.names.get(uid, "User"), "language_code": "uz"}

    async def feed(self, payload: dict) -> None:
        upd = Update.model_validate({"update_id": next(self.updates), **payload}, context={"bot": self.bot})
        await self.dp.feed_update(self.bot, upd)

    async def say(self, uid: int, text: str) -> None:
        msg = {"message_id": 10_000 + next(self.updates), "date": int(datetime.now(UTC).timestamp()),
               "chat": {"id": uid, "type": "private"}, "from": self.user(uid), "text": text}
        if text.startswith("/"):
            msg["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        await self.feed({"message": msg})

    async def tap_data(self, uid: int, data: str, message_id: int = 1) -> None:
        cq = {"id": str(next(self.updates)), "from": self.user(uid), "chat_instance": "ci", "data": data,
              "message": {"message_id": message_id, "date": int(datetime.now(UTC).timestamp()),
                          "chat": {"id": uid, "type": "private"}, "from": BOT_USER.model_dump(), "text": "…"}}
        await self.feed({"callback_query": cq})

    async def tap(self, uid: int, label: str) -> None:
        """Press the newest visible button whose text starts with ``label``."""
        for msg in reversed(self.session.chats.get(uid, [])):
            for row in getattr(msg["markup"], "inline_keyboard", []) or []:
                for b in row:
                    if b.text.startswith(label) and b.callback_data:
                        await self.tap_data(uid, b.callback_data, msg["id"])
                        return
        raise AssertionError(f"no button {label!r} for {uid}; last: {self.last(uid)!r}")

    def last(self, uid: int) -> str:
        msgs = self.session.chats.get(uid, [])
        return msgs[-1]["text"] if msgs else ""

    def texts(self, uid: int) -> list[str]:
        return [m["text"] for m in self.session.chats.get(uid, [])]

    def alerts(self) -> list[str]:
        return [c.text for c in self.session.calls if isinstance(c, AnswerCallbackQuery) and c.text]

    def buttons(self, uid: int) -> list[str]:
        msgs = self.session.chats.get(uid, [])
        rows = getattr(msgs[-1]["markup"], "inline_keyboard", []) if msgs else []
        return [b.text for row in rows or [] for b in row]

    @staticmethod
    def token_in(text: str) -> str:
        m = re.search(r"start=d_([A-Za-z0-9_-]+)", text)
        assert m, text
        return m.group(1)
