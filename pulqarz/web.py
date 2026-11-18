"""aiohttp server: the Mini App's static files and its JSON API.

Every /api call must carry ``Authorization: tma <initData>``; the HMAC and ``auth_date`` are checked, then the
call runs *as* that Telegram user through the same Service the bot uses."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from aiohttp import web

from .core import balance
from .core.money import MoneyError, parse_amount
from .security import AuthError, RateLimiter, validate_init_data
from .service import Refused, Service

log = logging.getLogger(__name__)
ME = web.RequestKey("me", int)
ROOT = Path(__file__).resolve().parent.parent
CSP = ("default-src 'self'; script-src 'self' https://telegram.org; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors https://web.telegram.org https://*.telegram.org; base-uri 'none'")


def _amount(value: object) -> int:
    try:
        return parse_amount(str(value))
    except MoneyError as err:
        raise Refused("amount") from err


def _uid(request: web.Request) -> int:
    try:
        uid = int(request.match_info["uid"])
    except ValueError as err:
        raise Refused("not_found") from err
    return uid


async def _body(request: web.Request) -> dict:
    try:
        data = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        raise Refused("generic") from err
    if not isinstance(data, dict):
        raise Refused("generic")
    return data


def make_app(service: Service, bot_token: str, notifier=None, max_age: int = 3600, rate_per_minute: int = 60,
             clock=None, bot_username: str = "") -> web.Application:
    limiter = RateLimiter(rate_per_minute)

    @web.middleware
    async def guard(request: web.Request, handler):
        try:
            if request.path.startswith("/api/"):
                header = request.headers.get("Authorization", "")
                if not header.startswith("tma "):
                    raise AuthError("missing")
                now = clock().timestamp() if clock else None
                user = validate_init_data(header[4:], bot_token, max_age, now=now)
                if not limiter.allow(user["id"]):
                    return web.json_response({"error": "rate"}, status=429)
                await service.touch_user(user["id"], user["first_name"], user["language_code"])
                request[ME] = user["id"]
            resp = await handler(request)
        except AuthError:
            resp = web.json_response({"error": "auth"}, status=401)
        except Refused as err:
            resp = web.json_response({"error": err.code}, status=400)
        resp.headers.update({"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff",
                             "Referrer-Policy": "no-referrer"})
        return resp

    async def me(request: web.Request) -> web.Response:
        uid = request[ME]
        s = await service.summary(uid)
        user = await service.db.user(uid)
        return web.json_response({
            "me": {"id": uid, "name": user["name"], "lang": user["lang"]}, "today": service.today(),
            "owed_to_me": s["owed_to_me"], "i_owe": s["i_owe"],
            "people": [{"id": o, "name": n, "net": s["people"].get(o, {})} for o, n in s["names"].items()],
            "pending": [{"other": p["other"], "name": p["name"], "prop": p["prop"],
                         "debt": balance.debt_view(p["debt"], uid)} for p in s["pending"]],
        })

    async def person(request: web.Request) -> web.Response:
        p = await service.person(request[ME], _uid(request))
        p["props"] = [{**x, "mine": x["by"] == request[ME]} for x in p["props"]]
        p["today"] = service.today()
        return web.json_response(p)

    async def create(request: web.Request) -> web.Response:
        d, uid = await _body(request), request[ME]
        other = d.get("other")
        if other is not None and (not isinstance(other, int) or isinstance(other, bool)):
            raise Refused("not_found")
        res = await service.propose_debt(uid, direction=str(d.get("direction")), amount=_amount(d.get("amount")),
                                         cur=str(d.get("cur")), due=str(d.get("due")), note=str(d.get("note") or ""),
                                         other=other, name=d.get("name"))
        if "token" in res:
            link = f"https://t.me/{bot_username}?start=d_{res['token']}"
            return web.json_response({"token": res["token"], "name": res["name"], "link": link})
        if notifier:
            _, _, st = await service.chain(uid, other)
            seq = res["entry"]["seq"]
            await notifier.ask(other, uid, st["props"][seq], st["debts"][seq])
        return web.json_response({"sent": True, "seq": res["entry"]["seq"]})

    async def answer(request: web.Request) -> web.Response:
        d, uid, other = await _body(request), request[ME], _uid(request)
        seq = d.get("seq")
        if not isinstance(seq, int) or not isinstance(d.get("ok"), bool):
            raise Refused("generic")
        out = await service.answer(uid, other, seq, confirm=d["ok"], reason=d.get("reason"))
        if notifier:
            await notifier.answered(other, uid, out["prop"])
        return web.json_response({"status": out["prop"]["status"], "seal": out["prop"].get("seal")})

    async def change(request: web.Request) -> web.Response:
        d, uid, other = await _body(request), request[ME], _uid(request)
        seq, kind = d.get("seq"), d.get("kind")
        if not isinstance(seq, int) or kind not in ("payment", "correction", "writeoff"):
            raise Refused("generic")
        amount = _amount(d["amount"]) if d.get("amount") not in (None, "") else None
        due = str(d["due"]) if d.get("due") else None
        out = await service.propose_change(uid, other, seq, kind, amount=amount, due=due)
        if notifier:
            await notifier.ask(other, uid, out["prop"], out["debt"])
        return web.json_response({"seq": out["entry"]["seq"]})

    async def lang(request: web.Request) -> web.Response:
        d = await _body(request)
        if d.get("lang") not in ("uz", "ru"):
            raise Refused("generic")
        await service.db.set_lang(request[ME], d["lang"])
        return web.json_response({"lang": d["lang"]})

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def index(_: web.Request) -> web.Response:
        raise web.HTTPFound("/webapp/")

    app = web.Application(middlewares=[guard], client_max_size=16 * 1024)
    app.router.add_get("/api/me", me)
    app.router.add_get(r"/api/people/{uid:-?\d{1,15}}", person)
    app.router.add_post("/api/debts", create)
    app.router.add_post(r"/api/people/{uid:-?\d{1,15}}/answer", answer)
    app.router.add_post(r"/api/people/{uid:-?\d{1,15}}/changes", change)
    app.router.add_post("/api/lang", lang)
    app.router.add_get("/healthz", health)
    app.router.add_get("/", index)
    app.router.add_static("/webapp/", ROOT / "webapp", append_version=False)
    app.router.add_static("/shared/", ROOT / "shared", append_version=False)
    return app
