"""Bot screens: each function returns ``(html_text, inline_keyboard)``. Every screen has a Back button.
The browser demo (demo/bot.js) renders the same screens from the same locale keys."""

from __future__ import annotations

import html
from datetime import UTC, datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from ..core import schedule
from ..core.ledger import CURRENCIES
from ..i18n import Raw, day, money, t
from .cb import Ans, Debt, Nav, Per, Step, Why

Screen = tuple[str, InlineKeyboardMarkup]


def kb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def btn(text: str, data) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data.pack() if hasattr(data, "pack") else data)


def back(lang: str, data) -> list[InlineKeyboardButton]:
    return [btn(t(lang, "btn.back"), data)]


def local_day(at: str) -> str:
    """UTC timestamp -> Tashkent date (``DD.MM.YYYY``)."""
    dt = datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return day(schedule.local_today(dt))


def left(lang: str, due: str, today: str) -> str:
    n = schedule.days_left(due, today)
    if n > 0:
        return t(lang, "left.in", n=n)
    return t(lang, "left.today") if n == 0 else t(lang, "left.over", n=-n)


def amounts(lang: str, by_cur: dict[str, int]) -> str:
    parts = [money(lang, v, c) for c, v in by_cur.items() if v]
    return ", ".join(parts) if parts else "0"


def what(lang: str, prop: dict) -> str:
    if prop["kind"] in ("debt", "payment", "writeoff"):
        return t(lang, f"what.{prop['kind']}", amount=money(lang, prop["amount"], prop["cur"]))
    return t(lang, "what.correction")


def change(lang: str, prop: dict) -> str:
    parts = []
    if "amount" in prop:
        parts.append(t(lang, "change.amount", **{"from": money(lang, prop["from_amount"], prop["cur"]),
                                                 "to": money(lang, prop["amount"], prop["cur"])}))
    if "due" in prop:
        parts.append(t(lang, "change.due", **{"from": day(prop["from_due"]), "to": day(prop["due"])}))
    return Raw(", ".join(parts))


# ── screens ──
def main_menu(lang: str, pending: int, webapp_url: str = "", hello: bool = False) -> Screen:
    rows = [
        [btn(t(lang, "btn.lent"), Nav(to="lent")), btn(t(lang, "btn.borrowed"), Nav(to="borrowed"))],
        [btn(t(lang, "btn.balance"), Nav(to="balance")), btn(t(lang, "btn.people"), Nav(to="people"))],
    ]
    if pending:
        rows.insert(0, [btn(t(lang, "btn.pending", n=pending), Nav(to="pending"))])
    if webapp_url:
        rows.append([InlineKeyboardButton(text=t(lang, "btn.app"), web_app=WebAppInfo(url=webapp_url))])
    rows.append([btn(t(lang, "btn.lang"), Nav(to="lang"))])
    return t(lang, "start.hello" if hello else "start.menu"), kb(*rows)


def balance(lang: str, s: dict) -> Screen:
    lines = [t(lang, "balance.title")]
    if not any(s["owed_to_me"].values()) and not any(s["i_owe"].values()):
        lines.append(t(lang, "balance.none"))
    else:
        lines.append(t(lang, "balance.owed", list=Raw(amounts(lang, s["owed_to_me"]))))
        lines.append(t(lang, "balance.owe", list=Raw(amounts(lang, s["i_owe"]))))
        lines.append("")
        for uid, net in s["people"].items():
            for cur in CURRENCIES:
                v = net.get(cur, 0)
                if v:
                    key = "balance.they_owe" if v > 0 else "balance.you_owe"
                    lines.append(t(lang, key, name=s["names"][uid], amount=money(lang, abs(v), cur)))
    return "\n".join(lines), kb(back(lang, Nav(to="menu")))


def people(lang: str, s: dict) -> Screen:
    rows = []
    for uid, name in s["names"].items():
        net = s["people"].get(uid, {})
        label = name + (" · " + amounts(lang, {c: abs(v) for c, v in net.items()}) if net else "")
        rows.append([btn(label[:60], Per(uid=uid, view="open"))])
    text = t(lang, "people.title") if rows else t(lang, "people.empty")
    return text, kb(*rows, back(lang, Nav(to="menu")))


def person(lang: str, p: dict, today: str) -> Screen:
    uid = p["other"]
    lines = [f"<b>{html.escape(p['name'], quote=False)}</b>"]
    for cur in CURRENCIES:
        v = p["net"].get(cur, 0)
        if v:
            key = "balance.they_owe" if v > 0 else "balance.you_owe"
            lines.append(t(lang, key, name=p["name"], amount=money(lang, abs(v), cur)))
    if not p["net"]:
        lines.append(t(lang, "balance.even", name=p["name"]))
    open_debts = [d for d in p["debts"] if d["status"] in ("active", "pending")]
    lines += ["", t(lang, "person.open") if open_debts else t(lang, "person.none")]
    rows = []
    for d in open_debts[-8:]:
        lines.append(t(lang, "debt.line", seq=d["seq"], remaining=money(lang, d["remaining"], d["cur"]),
                       left=left(lang, d["due"], today) if d["status"] == "active" else t(lang, "status.pending")))
        rows.append([btn(t(lang, "btn.debt", seq=d["seq"], amount=money(lang, d["remaining"], d["cur"])),
                         Debt(uid=uid, seq=d["seq"], act="open"))])
    rows.append([btn(t(lang, "btn.history"), Per(uid=uid, view="hist")),
                 btn(t(lang, "btn.verify"), Per(uid=uid, view="verify"))])
    return "\n".join(lines), kb(*rows, back(lang, Nav(to="people")))


def debt_card(lang: str, uid: int, d: dict, waiting: bool, today: str) -> Screen:
    text = t(lang, "debt.card", seq=d["seq"], role=t(lang, f"role.{d['role']}"),
             principal=money(lang, d["principal"], d["cur"]), paid=money(lang, d["paid"], d["cur"]),
             remaining=money(lang, d["remaining"], d["cur"]), due=day(d["due"]), left=left(lang, d["due"], today),
             note=d["note"] or "—", status=t(lang, f"status.{d['status']}"), seal=d["seal"] or "—")
    rows = []
    if waiting:
        text += "\n\n" + t(lang, "debt.waiting")
    elif d["status"] == "active":
        rows.append([btn(t(lang, "btn.pay"), Debt(uid=uid, seq=d["seq"], act="pay")),
                     btn(t(lang, "btn.correct"), Debt(uid=uid, seq=d["seq"], act="correct"))])
        if d["role"] == "lender":
            rows.append([btn(t(lang, "btn.writeoff"), Debt(uid=uid, seq=d["seq"], act="wo"))])
    return text, kb(*rows, back(lang, Per(uid=uid, view="open")))


def history(lang: str, p: dict) -> Screen:
    lines = [t(lang, "history.title", name=p["name"])]
    debts = {d["seq"]: d for d in p["debts"]}
    for prop in p["props"]:
        cur = prop["cur"]
        if prop["kind"] == "debt":
            body = t(lang, "hist.debt", ref=prop["ref"], amount=money(lang, prop["amount"], cur),
                     role=t(lang, f"role.{debts[prop['ref']]['role']}"))
        elif prop["kind"] == "correction":
            body = t(lang, "hist.correction", ref=prop["ref"], change=change(lang, prop))
        else:
            body = t(lang, f"hist.{prop['kind']}", ref=prop["ref"], amount=money(lang, prop["amount"], cur))
        if prop["status"] == "confirmed":
            status = t(lang, "hist.sealed", seal=prop["seal"])
        elif prop["status"] == "rejected":
            status = t(lang, "hist.rejected", reason=prop["reason"])
        else:
            status = t(lang, "hist.waiting")
        lines.append(f"{local_day(prop['at'])} · {body} · {status}")
    if not p["props"]:
        lines.append(t(lang, "history.empty"))
    if len(lines) > 41:  # Telegram messages are limited to 4096 characters: show the latest 40 events
        lines = lines[:1] + lines[-40:]
    return "\n".join(lines), kb(back(lang, Per(uid=p["other"], view="open")))


def verify(lang: str, uid: int, v: dict) -> Screen:
    if v["ok"]:
        text = t(lang, "verify.ok", count=v["count"], head=v["head"][:16] + "…")
    else:
        text = t(lang, "verify.bad", seq=v["seq"], reason=t(lang, f"verify.reason.{v['reason']}"))
    return text, kb(back(lang, Per(uid=uid, view="open")))


def pending(lang: str, items: list[dict]) -> Screen:
    rows = [[btn(t(lang, "pending.item", name=i["name"], what=what(lang, i["prop"]))[:60],
                 Ans(uid=i["other"], seq=i["prop"]["seq"], ok=2))] for i in items[:20]]
    text = t(lang, "pending.title") if rows else t(lang, "pending.empty")
    return text, kb(*rows, back(lang, Nav(to="menu")))


def ask(lang: str, name: str, uid: int, prop: dict, debt: dict) -> Screen:
    if prop["kind"] == "debt":
        line = t(lang, "ask.lent_to_you" if debt["lender"] == prop["by"] else "ask.borrowed_from_you", name=name)
        text = t(lang, "ask.debt", name=name, line=Raw(line), amount=money(lang, debt["principal"], debt["cur"]),
                 due=day(debt["due"]), note=debt["note"] or "—")
    elif prop["kind"] == "correction":
        text = t(lang, "ask.correction", name=name, ref=prop["ref"], change=change(lang, prop))
    else:
        text = t(lang, f"ask.{prop['kind']}", name=name, ref=prop["ref"],
                 amount=money(lang, prop["amount"], prop["cur"]))
    return text, kb([btn(t(lang, "btn.confirm"), Ans(uid=uid, seq=prop["seq"], ok=1)),
                     btn(t(lang, "btn.reject"), Ans(uid=uid, seq=prop["seq"], ok=0))],
                    back(lang, Nav(to="pending")))


def reasons(lang: str, uid: int, seq: int) -> Screen:
    rows = [[btn(t(lang, f"reason.{c}"), Why(uid=uid, seq=seq, code=c))] for c in ("amount", "none", "date")]
    rows.append([btn(t(lang, "btn.reason_type"), Why(uid=uid, seq=seq, code="type"))])
    return t(lang, "reject.why"), kb(*rows, back(lang, Ans(uid=uid, seq=seq, ok=2)))


def done(lang: str, text: str) -> Screen:
    return text, kb(back(lang, Nav(to="menu")))


def reminder(lang: str, name: str, debt: dict, kind: str, me: int, today: str) -> str:
    if kind.startswith("overdue"):
        title = t(lang, "remind.title.overdue", n=-schedule.days_left(debt["due"], today))
    else:
        title = t(lang, f"remind.title.{kind}")
    key = "remind.lender" if debt["lender"] == me else "remind.borrower"
    rem = debt["principal"] - debt["paid"]
    return t(lang, key, title=title, amount=money(lang, rem, debt["cur"]), name=name, due=day(debt["due"]))


def cancel_row(lang: str) -> list[InlineKeyboardButton]:
    return [btn(t(lang, "btn.back"), Step(act="back")), btn(t(lang, "btn.cancel"), Step(act="cancel"))]
