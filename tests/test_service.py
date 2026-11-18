"""Use cases, authorization, invites and reminders against a real (in-memory) SQLite database."""

from __future__ import annotations

import aiosqlite
import pytest

from pulqarz import reminders
from pulqarz.core import ledger
from pulqarz.service import Refused, parse_day

from .helpers import ALI, OLIM, VALI, lend_via_link, service_env


async def test_full_flow_link_confirm_payment_and_chain():
    async with service_env() as (svc, clock):
        res = await svc.propose_debt(ALI, direction="lent", amount=150_000_000, cur="UZS", due="2026-12-01",
                                     note="Telefon uchun", name="Vali aka")
        assert len(res["token"]) >= 22
        opened = await svc.open_invite(VALI, res["token"])
        assert opened["other"] == ALI and opened["entry"]["by"] == ALI
        assert (await svc.summary(ALI))["owed_to_me"]["UZS"] == 0  # not valid until Vali confirms
        pending = await svc.pending_for(VALI)
        assert [p["prop"]["kind"] for p in pending] == ["debt"]
        done = await svc.answer(VALI, ALI, 1, confirm=True)
        assert done["debt"]["status"] == "active" and len(done["debt"]["seal"]) == 9
        assert (await svc.summary(ALI))["names"][VALI] == "Vali aka"  # Ali's own label for Vali

        clock.skip(days=3)
        await svc.propose_change(VALI, ALI, 1, "payment", amount=50_000_000)
        assert (await svc.summary(ALI))["owed_to_me"]["UZS"] == 150_000_000  # payment not confirmed yet
        await svc.answer(ALI, VALI, 3, confirm=True)
        s_ali, s_vali = await svc.summary(ALI), await svc.summary(VALI)
        assert s_ali["owed_to_me"]["UZS"] == 100_000_000
        assert s_vali["i_owe"]["UZS"] == 100_000_000
        person = await svc.person(ALI, VALI)
        assert person["verify"]["ok"] and person["verify"]["count"] == 4
        assert [p["status"] for p in person["props"]] == ["confirmed", "confirmed"]


async def test_rejection_with_reason():
    async with service_env() as (svc, _):
        res = await svc.propose_debt(VALI, direction="borrowed", amount=2000, cur="USD", due="2026-12-24", name="Ali")
        await svc.open_invite(ALI, res["token"])
        with pytest.raises(Refused) as err:
            await svc.answer(ALI, VALI, 1, confirm=False, reason="   ")
        assert err.value.code == "reason"
        out = await svc.answer(ALI, VALI, 1, confirm=False, reason="Summa noto'g'ri")
        assert out["debt"]["status"] == "rejected"
        assert (await svc.summary(ALI))["i_owe"]["USD"] == 0
        assert (await svc.verify(ALI, VALI))["ok"]


async def test_third_person_sees_and_confirms_nothing():
    async with service_env() as (svc, _):
        res = await svc.propose_debt(ALI, direction="lent", amount=100, cur="UZS", due="2026-12-01", name="Vali")
        await svc.open_invite(VALI, res["token"])
        s = await svc.summary(OLIM)
        assert s["people"] == {} and s["pending"] == []
        with pytest.raises(Refused):
            await svc.person(OLIM, ALI)
        for other in (ALI, VALI):
            with pytest.raises(Refused) as err:
                await svc.answer(OLIM, other, 1, confirm=True)
            assert err.value.code == "not_pending"
            with pytest.raises(Refused):
                await svc.propose_change(OLIM, other, 1, "payment", amount=1)
        with pytest.raises(Refused) as err:  # cannot write to a stranger chosen by ID
            await svc.propose_debt(OLIM, direction="lent", amount=100, cur="UZS", due="2026-12-01", other=ALI)
        assert err.value.code == "not_found"
        with pytest.raises(Refused) as err:  # Ali cannot confirm his own proposal
            await svc.answer(ALI, VALI, 1, confirm=True)
        assert err.value.code == "own_proposal"


async def test_invite_is_single_use_expires_and_is_not_for_its_creator():
    async with service_env() as (svc, clock):
        res = await svc.propose_debt(ALI, direction="lent", amount=100, cur="UZS", due="2026-12-01", name="Vali")
        with pytest.raises(Refused) as err:
            await svc.open_invite(ALI, res["token"])
        assert err.value.code == "own_link"
        await svc.open_invite(VALI, res["token"])
        with pytest.raises(Refused) as err:  # replay by the same or another person
            await svc.open_invite(OLIM, res["token"])
        assert err.value.code == "link_used"
        old = await svc.propose_debt(ALI, direction="lent", amount=100, cur="UZS", due="2026-12-20", name="Olim")
        clock.skip(days=7, hours=1)
        with pytest.raises(Refused) as err:
            await svc.open_invite(OLIM, old["token"])
        assert err.value.code == "link_used"
        for bad in ("", "x" * 10, "../../etc", "a" * 100):
            with pytest.raises(Refused):
                await svc.open_invite(OLIM, bad)


async def test_input_validation():
    async with service_env() as (svc, _):
        base = {"direction": "lent", "amount": 100, "cur": "UZS", "due": "2026-12-01", "name": "Vali"}
        for patch, code in [({"amount": 0}, "bad_amount"), ({"amount": 1.5}, "bad_amount"),
                            ({"cur": "EUR"}, "bad_amount"), ({"due": "2026-11-01"}, "date"),
                            ({"due": "2040-01-01"}, "date"), ({"name": "x" * 41}, "name"), ({"name": "  "}, "name"),
                            ({"note": "n" * 201}, "note"), ({"direction": "gift"}, "generic")]:
            with pytest.raises(Refused) as err:
                await svc.propose_debt(ALI, **{**base, **patch})
            assert err.value.code == code, patch
    assert parse_day("25.12.2026") == "2026-12-25" and parse_day("31.02.2026") is None


async def test_entries_are_append_only_and_tampering_is_detected():
    async with service_env() as (svc, _):
        await lend_via_link(svc)
        with pytest.raises(aiosqlite.IntegrityError):
            await svc.db.conn.execute("UPDATE entries SET body = '{}' WHERE seq = 1")
        with pytest.raises(aiosqlite.IntegrityError):
            await svc.db.conn.execute("DELETE FROM entries")
        # an attacker with raw DB access drops the guard and halves the amount
        await svc.db.conn.execute("DROP TRIGGER entries_no_update")
        await svc.db.conn.execute(
            "UPDATE entries SET body = replace(body, '\"amount\":150000000', '\"amount\":75000000') WHERE seq = 1")
        await svc.db.conn.commit()
        assert await svc.verify(VALI, ALI) == {"ok": False, "seq": 1, "reason": "hash"}
        # balances never come from forged entries, and nothing can be stacked on a broken chain
        assert (await svc.summary(ALI))["owed_to_me"]["UZS"] == 0
        with pytest.raises(Refused) as err:
            await svc.propose_change(VALI, ALI, 1, "payment", amount=1)
        assert err.value.code == "chain_broken"


async def test_reminders_fire_once_survive_restart_and_skip_closed_debts():
    async with service_env() as (svc, clock):
        await lend_via_link(svc, due="2026-11-25")
        got: list[tuple] = []

        async def deliver(uid, other, debt, kind):
            got.append((clock.now.date().isoformat(), uid, kind))

        assert await reminders.run_due(svc, deliver) == 0
        clock.skip(days=4)  # 2026-11-22, 12:00 Tashkent -> "3 days before" is due
        assert await reminders.run_due(svc, deliver) == 2
        assert await reminders.run_due(svc, deliver) == 0  # idempotent
        clock.skip(days=3)  # due day; a new Service on the same DB = a restart
        from pulqarz.service import Service

        restarted = Service(svc.db, clock=clock)
        assert await reminders.run_due(restarted, deliver) == 2
        clock.skip(days=1)
        assert await reminders.run_due(restarted, deliver) == 2
        assert {k for _, _, k in got} == {"before3", "due", "overdue1"}
        assert {u for _, u, _ in got} == {ALI, VALI}
        await svc.propose_change(VALI, ALI, 1, "payment", amount=150_000_000)
        await svc.answer(ALI, VALI, 3, confirm=True)
        clock.skip(days=10)
        assert await reminders.run_due(svc, deliver) == 0  # paid: overdue7 is skipped


async def test_moving_the_due_date_reschedules_reminders():
    async with service_env() as (svc, clock):
        await lend_via_link(svc, due="2026-11-25")
        await svc.propose_change(VALI, ALI, 1, "correction", due="2026-12-10")
        await svc.answer(ALI, VALI, 3, confirm=True)
        kinds = []

        async def deliver(uid, other, debt, kind):
            kinds.append((debt["due"], kind))

        clock.skip(days=4)
        await reminders.run_due(svc, deliver)
        assert kinds == []  # the old "3 days before 25th" no longer applies
        clock.skip(days=18)  # 2026-12-10, noon: both "3 days before" and "due day" are now due
        await reminders.run_due(svc, deliver)
        assert ("2026-12-10", "before3") in kinds and ("2026-12-10", "due") in kinds


def test_pair_key_rejects_self():
    with pytest.raises(ledger.LedgerError):
        ledger.pair_key(ALI, ALI)
