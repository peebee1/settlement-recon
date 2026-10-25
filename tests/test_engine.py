from datetime import date, timedelta

from recon.engine import Policy, reconcile
from recon.model import Expectation, SettlementRow

DAY = date(2026, 9, 1)
FEE = 150


def exp(ref: str, net: int, currency: str = "EUR", day: date = DAY) -> Expectation:
    return Expectation(ref=ref, currency=currency, gross=net + FEE, fee=FEE, value_date=day)


def row(ref: str, net: int, currency: str = "EUR", day: date = DAY, row_id: str = "") -> SettlementRow:
    return SettlementRow(
        row_id=row_id or f"R-{ref}-{net}-{day}",
        ref=ref, currency=currency, gross=net + FEE, fee=FEE, value_date=day,
    )


def test_exact_match_leaves_no_residual():
    result = reconcile([exp("A", 10_000)], [row("A", 10_000)])
    assert len(result.matches) == 1
    assert result.breaks == []
    assert result.matches[0].flags == frozenset()
    assert result.balances() and result.every_line_accounted()
    assert sum(result.residual().values()) == 0


def test_one_minor_unit_is_tolerated_two_is_a_break():
    inside = reconcile([exp("A", 10_000)], [row("A", 10_001)])
    assert inside.breaks == []
    assert "amount_tolerance" in inside.matches[0].flags

    outside = reconcile([exp("A", 10_000)], [row("A", 10_002)])
    assert [b.kind for b in outside.breaks] == ["amount_mismatch"]
    assert outside.breaks[0].contributions == {"EUR": -2}


def test_missing_settlement_is_a_break_of_the_expected_amount():
    result = reconcile([exp("A", 9_850)], [])
    assert [b.kind for b in result.breaks] == ["missing_in_settlement"]
    assert result.breaks[0].contributions == {"EUR": 9_850}
    assert result.balances() and result.every_line_accounted()


def test_unknown_settlement_is_blamed_at_the_row_amount():
    result = reconcile([], [row("GHOST", 100)])
    assert [b.kind for b in result.breaks] == ["unknown_in_settlement"]
    assert result.breaks[0].contributions == {"EUR": -100}
    assert result.balances() and result.every_line_accounted()


def test_duplicate_line_matches_once_and_blames_the_extra():
    result = reconcile(
        [exp("A", 10_000)],
        [row("A", 10_000, row_id="R1"), row("A", 10_000, row_id="R2")],
    )
    assert len(result.matches) == 1
    assert [b.kind for b in result.breaks] == ["duplicate_settlement"]
    assert result.breaks[0].row_ids == ("R2",)
    assert result.balances() and result.every_line_accounted()


def test_split_settlement_is_a_match_not_a_break():
    result = reconcile(
        [exp("A", 10_000)],
        [row("A", 6_000, row_id="R1"), row("A", 4_000, row_id="R2")],
    )
    assert result.breaks == []
    assert "split_settlement" in result.matches[0].flags
    assert result.matches[0].settled_net == 10_000
    assert result.balances() and result.every_line_accounted()


def test_split_that_does_not_add_up_is_composite():
    result = reconcile(
        [exp("A", 10_000)],
        [row("A", 6_000, row_id="R1"), row("A", 3_000, row_id="R2")],
    )
    assert [b.kind for b in result.breaks] == ["composite_mismatch"]
    assert result.breaks[0].contributions == {"EUR": 1_000}
    assert result.balances() and result.every_line_accounted()


def test_currency_mismatch_keeps_both_sides_visible():
    result = reconcile([exp("A", 10_000, "EUR")], [row("A", 10_000, "USD")])
    assert [b.kind for b in result.breaks] == ["currency_mismatch"]
    assert result.breaks[0].contributions == {"EUR": 10_000, "USD": -10_000}
    assert result.residual() == {"EUR": 10_000, "USD": -10_000}
    assert result.balances() and result.every_line_accounted()


def test_late_settlement_still_matches_but_is_flagged():
    result = reconcile([exp("A", 10_000)], [row("A", 10_000, day=DAY + timedelta(days=9))])
    assert result.breaks == []
    assert "late_settlement" in result.matches[0].flags


def test_settlement_inside_the_window_is_not_flagged():
    result = reconcile([exp("A", 10_000)], [row("A", 10_000, day=DAY + timedelta(days=3))])
    assert result.matches[0].flags == frozenset()


def test_window_is_a_policy_not_a_constant():
    loose = Policy(date_window_days=30)
    result = reconcile([exp("A", 10_000)], [row("A", 10_000, day=DAY + timedelta(days=9))], loose)
    assert result.matches[0].flags == frozenset()


def test_partition_holds_across_a_mixed_day():
    expectations = [exp(f"A{i}", 1_000 + i) for i in range(5)]
    rows = [
        row("A0", 1_000),
        row("A1", 1_001),
        row("A2", 500, row_id="X1"), row("A2", 503, row_id="X2"),
        row("A3", 2_000, row_id="Y1"),
        row("A4", 1_004, row_id="Z1"), row("A4", 1_004, row_id="Z2"),
        row("GHOST", 700),
    ]
    result = reconcile(expectations, rows)
    assert result.every_line_accounted()
    assert result.balances()
