"""The invariants, under many synthetic days.

A matcher that balances on one hand-built example is not tested. These loop over seeds so
a bug in an unusual combination of splits, duplicates, and tolerances still shows up.
"""

import pytest

from recon.engine import Policy, reconcile
from recon.inject import inject, make_clean


@pytest.mark.parametrize("seed", range(1, 26))
def test_invariants_hold_on_dirty_days(seed):
    day = inject(make_clean(seed=seed, count=150), seed=seed, per_class=3)
    result = reconcile(day.expectations, day.rows, Policy())

    assert result.every_line_accounted(), f"seed {seed} dropped or double counted a line"
    assert result.balances(), f"seed {seed} left an unexplained residual: {result.residual()}"
    assert sum(result.explained().values()) == sum(result.residual().values())


@pytest.mark.parametrize("seed", range(1, 26))
def test_clean_days_produce_no_breaks(seed):
    clean = make_clean(seed=seed, count=150)
    policy = Policy()
    result = reconcile(clean.expectations, clean.rows, policy)
    assert result.breaks == [], f"seed {seed} invented breaks: {result.by_kind()}"
    assert result.every_line_accounted()
    assert result.balances()
    # A clean day is not a zero residual day: inside-tolerance rounding legitimately
    # leaves a few minor units unexplained. It must stay bounded by that tolerance.
    residual = abs(sum(result.residual().values()))
    assert residual <= policy.tolerance_minor * len(result.matches)


def test_larger_tolerance_never_creates_breaks():
    clean = make_clean(seed=3, count=300)
    tight = reconcile(clean.expectations, clean.rows, Policy(tolerance_minor=0))
    loose = reconcile(clean.expectations, clean.rows, Policy(tolerance_minor=5))
    assert len(loose.breaks) <= len(tight.breaks)
