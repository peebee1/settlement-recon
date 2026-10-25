"""Synthetic settlement days with known breaks.

The point is ground truth. If you inject the break yourself, you can measure whether the
matcher finds it, and whether it invents breaks that are not there.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from .model import Expectation, SettlementRow

BREAK_CLASSES = (
    "missing_in_settlement",
    "unknown_in_settlement",
    "amount_mismatch",
    "duplicate_settlement",
    "currency_mismatch",
    "late_settlement",
)

CURRENCIES = ("EUR", "EUR", "EUR", "USD", "INR")


@dataclass
class Day:
    """One synthetic settlement day: what we expected, and what the PSP sent."""

    expectations: list[Expectation]
    rows: list[SettlementRow]
    truth: dict[str, set[str]] = field(default_factory=dict)


def make_clean(seed: int = 7, count: int = 400) -> Day:
    rng = random.Random(seed)
    base = date(2026, 9, 1)
    expectations: list[Expectation] = []
    rows: list[SettlementRow] = []
    row_seq = 0

    for i in range(count):
        ref = f"ORD-{i:05d}"
        currency = CURRENCIES[i % len(CURRENCIES)]
        gross = rng.randrange(500, 250_000)
        fee = round(gross * 0.014) + 25
        expected_day = base + timedelta(days=i // 25)
        exp = Expectation(ref=ref, currency=currency, gross=gross, fee=fee, value_date=expected_day)
        expectations.append(exp)

        settle_day = expected_day + timedelta(days=rng.choice([0, 0, 1, 1, 2]))
        if i % 17 == 3:
            # A legitimate split: the PSP pays the same money in two lines.
            first = round(exp.net * 0.6)
            for amount in (first, exp.net - first):
                row_seq += 1
                rows.append(SettlementRow(
                    row_id=f"R{row_seq:06d}", ref=ref, currency=currency,
                    gross=amount + exp.fee, fee=exp.fee, value_date=settle_day,
                ))
            continue

        amount = exp.net
        if i % 29 == 5:
            amount += 1  # one minor unit of rounding, inside tolerance
        row_seq += 1
        rows.append(SettlementRow(
            row_id=f"R{row_seq:06d}", ref=ref, currency=currency,
            gross=amount + exp.fee, fee=exp.fee, value_date=settle_day,
        ))

    rng.shuffle(rows)
    return Day(expectations=expectations, rows=rows)


def inject(day: Day, seed: int = 11, per_class: int = 12) -> Day:
    """Return a new day with breaks of every class, plus the truth set for each.

    Refs are chosen from classes of line that can carry exactly one clean label:
    a single settlement line, in the expected currency, matching the expected net.
    Labels therefore cannot leak between classes, which is what makes precision
    meaningful rather than decorative.
    """
    rng = random.Random(seed)
    expectations = list(day.expectations)
    rows = list(day.rows)
    exp_by_ref = {e.ref: e for e in expectations}
    counts = Counter(row.ref for row in rows)

    single_refs = sorted(
        row.ref for row in rows
        if counts[row.ref] == 1
        and row.ref in exp_by_ref
        and row.currency == exp_by_ref[row.ref].currency
        and row.net == exp_by_ref[row.ref].net
    )
    all_refs = sorted(counts)

    def take(pool: list[str], used: set[str]) -> list[str]:
        available = [ref for ref in pool if ref not in used]
        if len(available) < per_class:
            raise ValueError(f"not enough clean refs: needed {per_class}, have {len(available)}")
        picked = available[:per_class]
        used.update(picked)
        return picked

    used: set[str] = set()
    chosen = {
        "missing_in_settlement": take(all_refs, used),
        "unknown_in_settlement": take(single_refs, used),
        "amount_mismatch": take(single_refs, used),
        "duplicate_settlement": take(single_refs, used),
        "currency_mismatch": take(single_refs, used),
        "late_settlement": take(single_refs, used),
    }
    truth: dict[str, set[str]] = {kind: set(refs) for kind, refs in chosen.items()}

    # 1. Missing: the PSP simply never settled it.
    missing = set(chosen["missing_in_settlement"])
    rows = [r for r in rows if r.ref not in missing]

    # 2. Unknown: money arrives for a payment we have no record of. The payment is removed
    #    entirely and replaced by an orphan line, so the label is unambiguous.
    orphans = set()
    for n, ref in enumerate(chosen["unknown_in_settlement"]):
        expectations = [e for e in expectations if e.ref != ref]
        rows = [r for r in rows if r.ref != ref]
        orphan = f"PSP-ORPHAN-{n:03d}"
        orphans.add(orphan)
        rows.append(SettlementRow(
            row_id=f"R9{n:05d}", ref=orphan, currency="EUR",
            gross=12_500, fee=200, value_date=date(2026, 10, 2),
        ))
    truth["unknown_in_settlement"] = orphans

    def replace_row(ref: str, **changes) -> None:
        index = next(i for i, r in enumerate(rows) if r.ref == ref)
        target = rows[index]
        rows[index] = SettlementRow(
            row_id=target.row_id, ref=ref,
            currency=changes.get("currency", target.currency),
            gross=changes.get("gross", target.gross),
            fee=changes.get("fee", target.fee),
            value_date=changes.get("value_date", target.value_date),
        )

    # 3. Amount mismatch: settled, but short or over by a real amount.
    for ref in chosen["amount_mismatch"]:
        shift = rng.choice([-1, 1]) * rng.randrange(500, 9_000)
        target = next(r for r in rows if r.ref == ref)
        replace_row(ref, gross=target.gross + shift)

    # 4. Duplicate: the same line twice, which is how a PSP double pays you.
    for n, ref in enumerate(chosen["duplicate_settlement"]):
        target = next(r for r in rows if r.ref == ref)
        rows.append(SettlementRow(
            row_id=f"R8{n:05d}", ref=ref, currency=target.currency,
            gross=target.gross, fee=target.fee, value_date=target.value_date,
        ))

    # 5. Currency mismatch: right reference, wrong currency.
    for ref in chosen["currency_mismatch"]:
        target = next(r for r in rows if r.ref == ref)
        replace_row(ref, currency="USD" if target.currency != "USD" else "EUR")

    # 6. Late: settled, but far outside the expected window.
    for ref in chosen["late_settlement"]:
        target = next(r for r in rows if r.ref == ref)
        replace_row(ref, value_date=target.value_date + timedelta(days=rng.randrange(10, 40)))

    rng.shuffle(rows)
    return Day(expectations=expectations, rows=rows, truth=truth)
