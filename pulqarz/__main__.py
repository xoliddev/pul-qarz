"""Run everything in one process: ``python -m pulqarz``.

* the Telegram bot (long polling),
* the aiohttp server with the Mini App and its API,
* the reminder loop (reminders are stored in SQLite, so a restart loses nothing).
"""

from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.types import MenuButtonWebApp, WebAppInfo
from aiohttp import web

from . import reminders
from .bot.notify import Notifier
from .bot.setup import BotConfig, build_dispatcher
from .config import Settings
from .db import Database
from .service import Service
from .web import make_app

log = logging.getLogger("pulqarz")


async def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Settings.from_env()
    db = await Database.open(cfg.db_path)
    service = Service(db, invite_days=cfg.invite_days)
    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    me = await bot.get_me()
    dp = build_dispatcher(service, bot, BotConfig(me.username or "", cfg.webapp_url), cfg.rate_per_minute)
    notifier = Notifier(bot, service)
    if cfg.webapp_url:
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Pul Qarz", web_app=WebAppInfo(
            url=cfg.webapp_url)))

    app = make_app(service, cfg.bot_token, notifier, cfg.initdata_max_age, cfg.rate_per_minute,
                   bot_username=me.username or "")
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, cfg.host, cfg.port).start()
    log.info("Mini App and API on http://%s:%s/webapp/  bot: @%s", cfg.host, cfg.port, me.username)
    remind = asyncio.create_task(reminders.loop(service, notifier.reminder, cfg.reminder_interval))
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        remind.cancel()
        await runner.cleanup()
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
