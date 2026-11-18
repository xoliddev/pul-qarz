"""Regenerate shared/test_vectors.json from the Python core.

    python scripts/make_vectors.py

The file is committed. pytest checks the Python core still produces it byte for byte, and
js-tests/parity.test.mjs checks the JS port produces the same hashes, balances and dates.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pulqarz.core import balance, ledger, money, schedule  # noqa: E402
from pulqarz.core.canon import canonical, entry_hash, sha256_hex  # noqa: E402

ALI, VALI, SARDOR = 1001, 1002, 1003
PAIR = ledger.pair_key(ALI, VALI)

CANON_INPUTS = [
    {"b": 2, "a": 1},
    {"note": "Qarz: \"to'y\" uchun\nyangi qator\tтаб", "z": [3, 2, 1], "emoji": "\U0001f4b8 ok"},
    {"nested": {"y": "ё", "x": -5}, "empty": "", "list": []},
    {"ctrl": "\u0001\u001f", "slash": "a/b\\c", "big": 9007199254740991},
]

STEPS = [
    {"kind": "debt", "by": ALI, "at": "2026-11-01T06:00:00Z", "lender": ALI, "borrower": VALI,
     "amount": 150000000, "cur": "UZS", "due": "2026-12-01", "note": "Telefon uchun"},
    {"kind": "confirm", "by": VALI, "at": "2026-11-01T06:05:00Z", "ref": 1},
    {"kind": "payment", "by": VALI, "at": "2026-11-10T10:00:00Z", "ref": 1, "amount": 50000000},
    {"kind": "confirm", "by": ALI, "at": "2026-11-10T10:30:00Z", "ref": 3},
    {"kind": "debt", "by": VALI, "at": "2026-11-12T08:00:00Z", "lender": VALI, "borrower": ALI,
     "amount": 2050, "cur": "USD", "due": "2026-11-20", "note": ""},
    {"kind": "reject", "by": ALI, "at": "2026-11-12T08:10:00Z", "ref": 5, "reason": "Summa noto'g'ri"},
    {"kind": "debt", "by": VALI, "at": "2026-11-12T09:00:00Z", "lender": VALI, "borrower": ALI,
     "amount": 2000, "cur": "USD", "due": "2026-12-31"},
    {"kind": "confirm", "by": ALI, "at": "2026-11-12T09:01:00Z", "ref": 7},
    {"kind": "correction", "by": ALI, "at": "2026-11-15T12:00:00Z", "ref": 1, "due": "2027-01-15"},
    {"kind": "confirm", "by": VALI, "at": "2026-11-15T12:30:00Z", "ref": 9},
    {"kind": "writeoff", "by": VALI, "at": "2026-11-16T12:00:00Z", "ref": 7},
]

INVALID = [  # (prefix length, body, expected error)
    (0, {"kind": "debt", "by": SARDOR, "at": "2026-11-01T06:00:00Z", "lender": ALI, "borrower": VALI,
         "amount": 100, "cur": "UZS", "due": "2026-12-01"}, "not_a_party"),
    (1, {"kind": "confirm", "by": ALI, "at": "2026-11-01T06:05:00Z", "ref": 1}, "own_proposal"),
    (2, {"kind": "payment", "by": VALI, "at": "2026-11-10T10:00:00Z", "ref": 1, "amount": 150000001}, "bad_amount"),
    (3, {"kind": "payment", "by": ALI, "at": "2026-11-10T10:00:00Z", "ref": 1, "amount": 5}, "change_pending"),
    (2, {"kind": "writeoff", "by": VALI, "at": "2026-11-10T10:00:00Z", "ref": 1}, "only_lender"),
    (0, {"kind": "debt", "by": ALI, "at": "2026-11-01T06:00:00Z", "lender": ALI, "borrower": VALI,
         "amount": 100, "cur": "EUR", "due": "2026-12-01"}, "bad_currency"),
    (0, {"kind": "debt", "by": ALI, "at": "2026-11-01T06:00:00Z", "lender": ALI, "borrower": VALI,
         "amount": 100, "cur": "UZS", "due": "2026-02-30"}, "bad_date"),
    (6, {"kind": "confirm", "by": VALI, "at": "2026-11-12T08:20:00Z", "ref": 5}, "not_pending"),
    (2, {"kind": "correction", "by": VALI, "at": "2026-11-12T08:20:00Z", "ref": 1}, "nothing_to_change"),
]

TAMPER = [  # (seq, field, new value) — expected result computed below
    (3, "amount", 5000000),
    (8, "by", VALI),
    (2, "prev", "f" * 64),
]

MONEY_PARSE = ["1 500 000", "1,500,000", "150.5", "150,50", "2000", "1 500 000 so'm", "$20.25",
               "0", "abc", "1.234", "12,3456", "-5", "1000000000000", "999 999 999 999,99"]


def main() -> None:
    state = ledger.new_state()
    entries = [ledger.append(state, PAIR, step) for step in STEPS]
    invalid = []
    for n, body, code in INVALID:
        st = ledger.fold(entries[:n])
        try:
            ledger.append(st, PAIR, body)
            raise SystemExit(f"expected {code}")
        except ledger.LedgerError as err:
            assert err.code == code, (err.code, code)
        invalid.append({"prefix": n, "body": body, "error": code})
    tamper = []
    for seq, field, value in TAMPER:
        bad = copy.deepcopy(entries)
        bad[seq - 1][field] = value
        tamper.append({"seq": seq, "field": field, "value": value, "result": ledger.verify_chain(bad)})
    other = ledger.new_state()
    pair2 = ledger.pair_key(ALI, SARDOR)
    sardor_entries = [
        ledger.append(other, pair2, {"kind": "debt", "by": SARDOR, "at": "2026-11-03T05:00:00Z", "lender": SARDOR,
                                     "borrower": ALI, "amount": 30000000, "cur": "UZS", "due": "2026-11-25"}),
        ledger.append(other, pair2, {"kind": "confirm", "by": ALI, "at": "2026-11-03T05:01:00Z", "ref": 1}),
    ]
    states = {VALI: state, SARDOR: other}
    parses = []
    for text in MONEY_PARSE:
        try:
            parses.append({"text": text, "minor": money.parse_amount(text)})
        except money.MoneyError:
            parses.append({"text": text, "error": "bad_amount"})
    reminders = [
        {"due": due, "today": today, "plan": schedule.reminder_plan(due, today)}
        for due, today in [("2026-12-01", "2026-11-18"), ("2026-11-20", "2026-11-18"),
                           ("2027-01-02", "2026-12-30"), ("2028-03-01", "2028-02-27"), ("2026-11-10", "2026-11-18")]
    ]
    out = {
        "canonical": [{"input": x, "canonical": canonical(x), "sha256": sha256_hex(canonical(x)),
                       "entry_hash": entry_hash("0" * 64, x)} for x in CANON_INPUTS],
        "chain": {"pair": PAIR, "steps": STEPS, "entries": entries, "verify": ledger.verify_chain(entries),
                  "debts": {str(s): balance.debt_view(d, ALI) for s, d in state["debts"].items()}},
        "invalid": invalid,
        "tamper": tamper,
        "balances": {"ali_vali": balance.pair_balance(state, ALI), "vali_ali": balance.pair_balance(state, VALI),
                     "ali_summary": json.loads(json.dumps(balance.summary(states, ALI))),
                     "ids": {"ali": ALI, "vali": VALI, "sardor": SARDOR},
                     "sardor_entries": sardor_entries},
        "reminders": reminders,
        "fire_at": [{"day": d, "utc": schedule.fire_at(d)} for d in ["2026-11-18", "2026-12-31", "2027-01-01"]],
        "money_parse": parses,
        "money_format": [{"minor": m, "text": money.format_number(m)}
                         for m in [0, 5, 100, 150000000, 150000050, 123456789012, -2050]],
    }
    text = json.dumps(out, ensure_ascii=False, indent=1) + "\n"
    (ROOT / "shared" / "test_vectors.json").write_text(text, encoding="utf-8", newline="\n")
    print("wrote shared/test_vectors.json")


if __name__ == "__main__":
    main()
