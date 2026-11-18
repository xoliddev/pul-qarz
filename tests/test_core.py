"""The pure core against the shared test vectors (the JS port is checked against the same file)."""

from __future__ import annotations

import copy
import subprocess
import sys

import pytest

from pulqarz.core import balance, ledger, money, schedule
from pulqarz.core.canon import GENESIS, canonical, entry_hash, seal, sha256_hex

from .conftest import ROOT


def test_vectors_file_is_up_to_date():
    """Regenerating the vectors from the Python core must give the committed file byte for byte."""
    before = (ROOT / "shared" / "test_vectors.json").read_bytes()
    subprocess.run([sys.executable, str(ROOT / "scripts" / "make_vectors.py")], check=True, capture_output=True)
    assert (ROOT / "shared" / "test_vectors.json").read_bytes() == before


def test_canonical(vectors):
    for case in vectors["canonical"]:
        assert canonical(case["input"]) == case["canonical"]
        assert sha256_hex(case["canonical"]) == case["sha256"]
        assert entry_hash(GENESIS, case["input"]) == case["entry_hash"]


@pytest.mark.parametrize("bad", [1.5, True, {"a": None}, {1: "x"}, 2**60])
def test_canonical_refuses_floats_bools_and_unsafe_ints(bad):
    with pytest.raises((TypeError, ValueError)):
        canonical(bad)


def test_chain_replays_to_the_same_hashes(vectors):
    chain = vectors["chain"]
    state = ledger.new_state()
    for step, expected in zip(chain["steps"], chain["entries"], strict=True):
        assert ledger.append(state, chain["pair"], step) == expected
    assert ledger.verify_chain(chain["entries"]) == chain["verify"]
    views = {str(s): balance.debt_view(d, 1001) for s, d in state["debts"].items()}
    assert views == chain["debts"]
    assert views["1"]["seal"] == seal(chain["entries"][1]["hash"])


def test_invalid_operations_are_refused_and_leave_state_untouched(vectors):
    entries = vectors["chain"]["entries"]
    for case in vectors["invalid"]:
        state = ledger.fold(entries[: case["prefix"]])
        snapshot = copy.deepcopy(state)
        with pytest.raises(ledger.LedgerError) as err:
            ledger.append(state, vectors["chain"]["pair"], case["body"])
        assert err.value.code == case["error"]
        assert state == snapshot


def test_tampering_is_detected(vectors):
    for case in vectors["tamper"]:
        bad = copy.deepcopy(vectors["chain"]["entries"])
        bad[case["seq"] - 1][case["field"]] = case["value"]
        assert ledger.verify_chain(bad) == case["result"]
        assert case["result"]["ok"] is False


def test_rewritten_chain_with_valid_hashes_but_broken_rules_is_caught(vectors):
    """Someone with DB access recomputes every hash so that Ali "confirms" his own debt."""
    steps = copy.deepcopy(vectors["chain"]["steps"][:2])
    steps[1]["by"] = 1001
    forged, prev = [], GENESIS
    for i, step in enumerate(steps, start=1):
        body = {**step, "v": 1, "pair": "1001:1002", "seq": i, "prev": prev}
        prev = entry_hash(prev, body)
        forged.append({**body, "hash": prev})
    assert ledger.verify_chain(forged) == {"ok": False, "seq": 2, "reason": "rule"}


def test_balances(vectors):
    b = vectors["balances"]
    chain = vectors["chain"]
    vali_state = ledger.fold(chain["entries"])
    sardor_state = ledger.fold(b["sardor_entries"])
    assert balance.pair_balance(vali_state, 1001) == b["ali_vali"]
    assert balance.pair_balance(vali_state, 1002) == b["vali_ali"]
    got = balance.summary({1002: vali_state, 1003: sardor_state}, 1001)
    got["people"] = {str(k): v for k, v in got["people"].items()}
    assert got == b["ali_summary"]
    # the pending write-off does not count until Ali confirms it
    assert b["ali_vali"]["USD"] == -2000


def test_both_sides_see_mirror_balances(vectors):
    state = ledger.fold(vectors["chain"]["entries"])
    ali, vali = balance.pair_balance(state, 1001), balance.pair_balance(state, 1002)
    assert {k: -v for k, v in ali.items()} == vali


def test_reminders(vectors):
    for case in vectors["reminders"]:
        assert schedule.reminder_plan(case["due"], case["today"]) == case["plan"]
    for case in vectors["fire_at"]:
        assert schedule.fire_at(case["day"]) == case["utc"]


def test_money(vectors):
    for case in vectors["money_parse"]:
        if "error" in case:
            with pytest.raises(money.MoneyError):
                money.parse_amount(case["text"])
        else:
            assert money.parse_amount(case["text"]) == case["minor"]
    for case in vectors["money_format"]:
        assert money.format_number(case["minor"]) == case["text"]


def test_payment_closes_debt_and_correction_changes_due():
    st = ledger.new_state()
    pair = ledger.pair_key(5, 7)
    ledger.append(st, pair, {"kind": "debt", "by": 7, "at": "2026-01-01T00:00:00Z", "lender": 7, "borrower": 5,
                             "amount": 1000, "cur": "UZS", "due": "2026-02-01"})
    ledger.append(st, pair, {"kind": "confirm", "by": 5, "at": "2026-01-01T00:00:01Z", "ref": 1})
    ledger.append(st, pair, {"kind": "correction", "by": 5, "at": "2026-01-02T00:00:00Z", "ref": 1,
                             "due": "2026-03-01", "amount": 1200})
    ledger.append(st, pair, {"kind": "confirm", "by": 7, "at": "2026-01-02T00:00:01Z", "ref": 3})
    assert (st["debts"][1]["principal"], st["debts"][1]["due"]) == (1200, "2026-03-01")
    ledger.append(st, pair, {"kind": "payment", "by": 5, "at": "2026-01-03T00:00:00Z", "ref": 1, "amount": 1200})
    ledger.append(st, pair, {"kind": "confirm", "by": 7, "at": "2026-01-03T00:00:01Z", "ref": 5})
    assert st["debts"][1]["status"] == "closed"
    assert balance.pair_balance(st, 5) == {}
    with pytest.raises(ledger.LedgerError):
        ledger.append(st, pair, {"kind": "payment", "by": 5, "at": "2026-01-04T00:00:00Z", "ref": 1, "amount": 1})
