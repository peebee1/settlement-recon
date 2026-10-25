from recon.engine import Policy
from recon.evals import clean_run, evaluate, to_markdown
from recon.inject import BREAK_CLASSES, inject, make_clean


def test_every_injected_class_is_found():
    day = inject(make_clean(seed=7, count=400), seed=11, per_class=12)
    result = evaluate(day, Policy())

    assert result["micro_recall"] == 1.0, [
        (s.kind, s.injected, s.true_positives) for s in result["classes"] if s.recall < 1.0
    ]
    assert result["micro_precision"] == 1.0, [
        (s.kind, s.detected, s.true_positives) for s in result["classes"] if s.precision < 1.0
    ]
    assert result["accounted"] and result["balances"]


def test_no_class_is_silently_empty():
    day = inject(make_clean(seed=7, count=400), seed=11, per_class=12)
    result = evaluate(day, Policy())
    assert {s.kind for s in result["classes"]} == set(BREAK_CLASSES)
    assert all(s.injected == 12 for s in result["classes"])


def test_clean_day_raises_nothing():
    clean = make_clean(seed=7, count=400)
    stats = clean_run(clean, Policy())
    assert stats["breaks"] == 0
    assert stats["accounted"] and stats["balances"]


def test_markdown_reports_the_numbers_it_ran():
    day = inject(make_clean(seed=7, count=400), seed=11, per_class=12)
    result = evaluate(day, Policy())
    clean = clean_run(make_clean(seed=7, count=400), Policy())
    text = to_markdown(result, clean, Policy())
    assert "micro F1" in text
    assert "| missing_in_settlement | 12 | 12 |" in text
    assert "pass" in text
