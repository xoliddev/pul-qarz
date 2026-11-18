"""End-to-end through the real aiogram handlers: create -> share link -> confirm -> partial payment -> confirm
-> reminders -> chain check, plus rejection, tampering, forged buttons and replayed links."""

from __future__ import annotations

from pulqarz import reminders
from pulqarz.bot.setup import BotConfig

from .helpers import ALI, OLIM, VALI, service_env
from .tg_sim import TgSim, fresh_dispatcher


async def ali_lends_vali_by_link(sim: TgSim) -> str:
    await sim.say(ALI, "/start")
    assert "Pul Qarz" in sim.last(ALI) and "Ilovani ochish" in sim.buttons(ALI)
    await sim.tap(ALI, "Qarz berdim")
    assert sim.last(ALI) == "Kimga qarz berdingiz?"
    await sim.tap(ALI, "Yangi odam")
    await sim.say(ALI, "Vali aka")
    assert "Summani yozing" in sim.last(ALI)
    await sim.say(ALI, "1,5 mln")  # not understood -> friendly error, still on the same step
    assert "tushunmadim" in sim.last(ALI)
    await sim.say(ALI, "1 500 000")
    await sim.tap(ALI, "So'm")
    await sim.tap(ALI, "2 haftada")
    await sim.say(ALI, "Telefon uchun")
    review = sim.last(ALI)
    assert "1 500 000 so'm" in review and "Vali aka" in review and "02.12.2026" in review
    assert "⬅️ Orqaga" in sim.buttons(ALI)
    await sim.tap(ALI, "Yuborish")
    assert "t.me/pulqarz_test_bot?start=d_" in sim.last(ALI)
    return sim.token_in(sim.last(ALI))


async def test_create_share_confirm_pay_remind_verify():
    async with service_env() as (svc, clock):
        sim = TgSim(svc)
        token = await ali_lends_vali_by_link(sim)
        await sim.say(VALI, f"/start d_{token}")
        assert "<b>Ali</b> qarz yozdi" in sim.last(VALI) and "Ali sizga qarz berdi" in sim.last(VALI)
        await sim.tap(VALI, "Tasdiqlayman")
        assert sim.last(VALI).startswith("Tasdiqlandi. Muhr:")
        seal = sim.last(VALI).split("<code>")[1][:9]
        assert "Vali aka</b> tasdiqladi" in sim.last(ALI) and seal in sim.last(ALI)

        await sim.say(OLIM, f"/start d_{token}")  # replayed link
        assert "ishlatilgan yoki muddati o'tgan" in sim.last(OLIM)

        # Vali records a partial payment; Ali must confirm it
        await sim.tap(VALI, "⬅️ Orqaga")
        await sim.tap(VALI, "Odamlar")
        await sim.tap(VALI, "Ali")
        await sim.tap(VALI, "#1")
        assert "Qoldiq: <b>1 500 000 so'm</b>" in sim.last(VALI) and seal in sim.last(VALI)
        await sim.tap(VALI, "To'lov yozish")
        await sim.say(VALI, "2 000 000")  # more than owed -> refused, can retry
        assert "qoldiqdan katta" in sim.last(VALI)
        await sim.say(VALI, "500 000")
        assert "To'lov yozildi" in sim.last(VALI)
        assert "to'lov yozdi: <b>500 000 so'm</b>" in sim.last(ALI)
        await sim.tap(ALI, "Tasdiqlayman")
        assert "tasdiqladi: to'lov 500 000 so'm" in sim.last(VALI)

        await sim.tap(ALI, "⬅️ Orqaga")
        await sim.tap(ALI, "Balans")
        assert "Menga qaytarilishi kerak: 1 000 000 so'm" in sim.last(ALI)
        assert "Vali aka: sizga 1 000 000 so'm qaytaradi" in sim.last(ALI)

        clock.skip(days=11)  # 2026-11-29 = 3 days before 2026-12-02
        sent = await reminders.run_due(svc, _notifier(sim).reminder)
        assert sent == 2
        assert "3 kun qoldi" in sim.last(ALI) and "Sizga qaytarilishi kerak: <b>1 000 000 so'm" in sim.last(ALI)
        assert "Siz qaytarishingiz kerak: <b>1 000 000 so'm" in sim.last(VALI)

        await sim.say(ALI, "/start")
        await sim.tap(ALI, "Odamlar")
        await sim.tap(ALI, "Vali aka")
        await sim.tap(ALI, "Zanjirni tekshirish")
        assert "Zanjir butun: 4 ta yozuv" in sim.last(ALI)
        await sim.tap(ALI, "⬅️ Orqaga")
        await sim.tap(ALI, "Tarix")
        assert sim.last(ALI).count("muhr ") == 2


def _notifier(sim: TgSim):
    from pulqarz.bot.notify import Notifier

    return Notifier(sim.bot, sim.svc)


async def test_rejection_with_reason_and_tamper_alarm():
    async with service_env() as (svc, _):
        sim = TgSim(svc)
        token = await ali_lends_vali_by_link(sim)
        await sim.say(VALI, f"/start d_{token}")
        await sim.tap(VALI, "Tasdiqlayman")
        # Vali now writes that he lent Ali $20 — Ali says no such debt exists
        await sim.say(VALI, "/start")
        await sim.tap(VALI, "Qarz berdim")
        await sim.tap(VALI, "Ali")
        await sim.say(VALI, "20")
        await sim.tap(VALI, "Dollar")
        await sim.tap(VALI, "1 haftada")
        await sim.tap(VALI, "Izohsiz")
        await sim.tap(VALI, "Yuborish")
        assert sim.last(VALI) == "Yuborildi. Ali tasdiqlashini kutyapmiz."
        assert "$20" in sim.last(ALI)
        await sim.tap(ALI, "Rad etaman")
        assert sim.last(ALI) == "Nima sababdan rad etasiz?"
        await sim.tap(ALI, "Bunday qarz yo'q")
        assert "Rad etildi" in sim.last(ALI)
        assert "rad etdi: qarz $20" in sim.last(VALI) and "Sabab: Bunday qarz yo'q" in sim.last(VALI)
        s = await svc.summary(ALI)
        assert s["i_owe"]["USD"] == 0

        await svc.db.conn.execute("DROP TRIGGER entries_no_update")
        await svc.db.conn.execute("UPDATE entries SET body = replace(body, '150000000', '15000000') WHERE seq = 1")
        await svc.db.conn.commit()
        await sim.say(VALI, "/start")
        await sim.tap(VALI, "Odamlar")
        await sim.tap(VALI, "Ali")
        await sim.tap(VALI, "Zanjirni tekshirish")
        assert "Zanjir #1-yozuvda uzilgan (mazmuni o'zgartirilgan)" in sim.last(VALI)


async def test_forged_and_stale_buttons_are_refused():
    async with service_env() as (svc, _):
        sim = TgSim(svc)
        token = await ali_lends_vali_by_link(sim)
        await sim.say(VALI, f"/start d_{token}")
        await sim.say(OLIM, "/start")
        before = len(await svc.db.entries("1001:1002"))
        for data in ("a:1001:1:1", "a:1002:1:1", "b:1001:1:payfull", "p:1001:open", "p:1002:hist", "b:1002:1:woyes"):
            await sim.tap_data(OLIM, data)
        for data in ("a:x:1:1", "n:admin", "b:1001:1:drop_table", "zzz", "w:-5", "d:3", "c:EUR"):
            await sim.tap_data(OLIM, data)
        assert len(await svc.db.entries("1001:1002")) == before  # Olim changed nothing
        alerts = sim.alerts()
        assert sum("Bu tugma eskirgan" in a for a in alerts) >= 6
        assert sum(a in ("Topilmadi.", "Bu yozuv allaqachon ko'rib chiqilgan.") for a in alerts) >= 5
        assert all("Ali" not in t and "1 500 000" not in t for t in sim.texts(OLIM))
        # Ali cannot confirm his own proposal by forging Vali's button
        await sim.tap_data(ALI, "a:1002:1:1")
        assert "O'z yozuvingizni o'zingiz tasdiqlay olmaysiz." in sim.alerts()


async def test_language_switch_and_rate_limit():
    async with service_env() as (svc, _):
        sim = TgSim(svc)
        await sim.say(ALI, "/start")
        await sim.tap(ALI, "Русский")
        assert sim.last(ALI).startswith("Главное меню") and "⬅️ Назад" not in sim.buttons(ALI)
        assert "Я дал в долг" in sim.buttons(ALI)
        sim.dp = fresh_dispatcher(svc, sim.bot, BotConfig("pulqarz_test_bot"), rate_per_minute=5)
        for _ in range(8):
            await sim.tap_data(ALI, "n:balance")
        assert sum("Слишком быстро" in a for a in sim.alerts()) == 3
