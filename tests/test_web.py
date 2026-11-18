"""Mini App API: initData HMAC + freshness, authorization, validation, rate limits and static files."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

from aiohttp.test_utils import TestClient, TestServer

from pulqarz.security import AuthError, sign_init_data, validate_init_data
from pulqarz.web import make_app

from .helpers import ALI, OLIM, VALI, service_env

TOKEN = "123456:TEST-ONLY-NOT-A-REAL-TOKEN"


def init_data(uid: int, clock, age: int = 0, token: str = TOKEN) -> str:
    fields = {"auth_date": str(int(clock().timestamp()) - age), "query_id": "AAE-test",
              "user": json.dumps({"id": uid, "first_name": f"U{uid}", "language_code": "uz"})}
    return sign_init_data(fields, token)


@asynccontextmanager
async def api(rate: int = 1000):
    async with service_env() as (svc, clock):
        app = make_app(svc, TOKEN, notifier=None, max_age=3600, rate_per_minute=rate, clock=clock)
        client = TestClient(TestServer(app))
        await client.start_server()

        def h(uid: int, age: int = 0) -> dict:
            return {"Authorization": "tma " + init_data(uid, clock, age)}

        try:
            yield client, svc, clock, h
        finally:
            await client.close()


async def test_initdata_signature_and_freshness():
    async with api() as (client, _, clock, h):
        assert (await client.get("/api/me")).status == 401
        assert (await client.get("/api/me", headers={"Authorization": "tma hash=00"})).status == 401
        assert (await client.get("/api/me", headers=h(ALI, age=7200))).status == 401  # too old
        assert (await client.get("/api/me", headers=h(ALI, age=-600))).status == 401  # from the future
        forged = init_data(ALI, clock, token="999:ANOTHER-BOT")
        assert (await client.get("/api/me", headers={"Authorization": "tma " + forged})).status == 401
        tampered = init_data(ALI, clock).replace("1001", "1002")
        assert (await client.get("/api/me", headers={"Authorization": "tma " + tampered})).status == 401
        r = await client.get("/api/me", headers=h(ALI))
        assert r.status == 200 and (await r.json())["me"]["id"] == ALI


def test_validate_init_data_rejects_duplicates_and_garbage():
    now = 1_800_000_000
    good = sign_init_data({"auth_date": str(now), "user": json.dumps({"id": 5})}, TOKEN)
    assert validate_init_data(good, TOKEN, 60, now=now)["id"] == 5
    for bad in ["", "%%%", good + "&user=%7B%22id%22%3A6%7D", "x" * 5000]:
        try:
            validate_init_data(bad, TOKEN, 60, now=now)
        except AuthError:
            continue
        raise AssertionError(bad)


async def test_create_answer_change_and_scoping():
    async with api() as (client, svc, _, h):
        r = await client.post("/api/debts", headers=h(ALI), json={
            "direction": "lent", "name": "Vali", "amount": "1 500 000", "cur": "UZS", "due": "2026-12-01",
            "note": "Telefon"})
        token = (await r.json())["token"]
        await svc.open_invite(VALI, token)
        me = await (await client.get("/api/me", headers=h(VALI))).json()
        assert [p["prop"]["kind"] for p in me["pending"]] == ["debt"]
        r = await client.post(f"/api/people/{ALI}/answer", headers=h(VALI), json={"seq": 1, "ok": True})
        assert (await r.json())["status"] == "confirmed"
        r = await client.post(f"/api/people/{ALI}/changes", headers=h(VALI),
                              json={"seq": 1, "kind": "payment", "amount": "500000"})
        assert r.status == 200
        p = await (await client.get(f"/api/people/{VALI}", headers=h(ALI))).json()
        assert p["verify"]["ok"] and len(p["entries"]) == 3 and p["props"][1]["mine"] is False
        ali = await (await client.get("/api/me", headers=h(ALI))).json()
        assert ali["owed_to_me"]["UZS"] == 150_000_000 and ali["people"][0]["name"] == "Vali"

        # Olim (a third person) can neither read nor act on Ali and Vali's debt
        for uid in (ALI, VALI):
            r = await client.get(f"/api/people/{uid}", headers=h(OLIM))
            assert r.status == 400 and (await r.json())["error"] == "not_found"
            r = await client.post(f"/api/people/{uid}/answer", headers=h(OLIM), json={"seq": 3, "ok": True})
            assert r.status == 400
            r = await client.post(f"/api/people/{uid}/changes", headers=h(OLIM),
                                  json={"seq": 1, "kind": "writeoff"})
            assert r.status == 400
        r = await client.post("/api/debts", headers=h(OLIM), json={
            "direction": "lent", "other": ALI, "amount": "5", "cur": "UZS", "due": "2026-12-01"})
        assert (await r.json())["error"] == "not_found"
        assert len(await svc.db.entries("1001:1002")) == 3


async def test_input_validation_and_limits():
    async with api(rate=5) as (client, _, _, h):
        bad = [{"direction": "lent", "name": "V", "amount": "abc", "cur": "UZS", "due": "2026-12-01"},
               {"direction": "lent", "name": "V" * 41, "amount": "5", "cur": "UZS", "due": "2026-12-01"},
               {"direction": "lent", "other": "1002", "amount": "5", "cur": "UZS", "due": "2026-12-01"},
               ["not", "an", "object"]]
        for body in bad:
            assert (await client.post("/api/debts", headers=h(ALI), json=body)).status == 400
        big = await client.post("/api/debts", headers=h(VALI), data="x" * 20_000)
        assert big.status == 413
        statuses = [(await client.get("/api/me", headers=h(ALI))).status for _ in range(3)]
        assert 429 in statuses


async def test_static_files_and_security_headers():
    async with api() as (client, _, _, _):
        r = await client.get("/webapp/index.html")
        assert r.status == 200 and "Pul Qarz" in await r.text()
        assert "frame-ancestors" in r.headers["Content-Security-Policy"]
        assert (await client.get("/shared/ledger.js")).status == 200
        assert (await client.get("/webapp/../pulqarz/config.py")).status in (403, 404)
        assert (await client.get("/healthz")).status == 200
