# settlement-recon

A settlement reconciliation engine that scores its own accuracy against breaks it
injected on purpose, and refuses to force a match when the numbers do not agree.

```
388 expected payments, 423 settlement lines
352 matched, 60 breaks
missing 12, unknown 12, amount mismatch 12, duplicate 12, currency 12, late 12
micro precision 1.000, micro recall 1.000
every line accounted for exactly once: pass
unexplained minor units: 0
```

## Problem

A PSP settles money in a file. Your ledger says what should have settled. The gap between
the two is where cash disappears: a line that never arrived, a duplicate payout, a refund
booked in the wrong currency, a payment that landed eleven days late.

Most teams close that gap in a spreadsheet, by eye, once a month. It works until volume
grows, and then it becomes a person.

## Why it matters

The failure mode of reconciliation is not a crash. It is silence. A matcher that is too
clever will pair a 99.00 line with a 100.00 expectation because the dates look right, and
nobody finds out until the auditor does. In payments, a false match is worse than a missed
one: a missed break shows up as an open item, a false match disappears.

So the design constraint here is: never invent a match, and prove that every line landed
somewhere.

## What makes this different

Most reconciliation code ships with an assertion that it works. This one ships with a
generator that injects labelled breaks into a clean day and scores the matcher against
them, per break class, so recall and precision are computed rather than claimed. The
clean day is run with zero breaks to check the matcher invents nothing.

`results/eval.md` and `results/eval.json` are produced by the committed command, and CI
regenerates them on every push and fails if they differ by a single byte. The numbers
below are not a transcript of one lucky run.

## Design

```
expectations (our ledger)          settlement file (the PSP)
        |                                   |
        +------------- reconcile -----------+
                          |
              +-----------+-----------+
              |                       |
           matches                  breaks
    exact / tolerance / split    missing, unknown, amount,
    with timing flags            duplicate, currency, composite
```

**Money is an integer.** Amounts are minor units, parsed from text with a hard rejection of
anything past two decimals. No float touches an amount.

**Matching is a cascade, not a similarity score.** For each reference, in order:

1. Currency mismatch: the right payment arrived in the wrong currency. Break.
2. Sum equals expected net: match. One line is exact, several lines are a legitimate split.
3. Within tolerance: match, flag as `amount_tolerance`.
4. Several lines where one alone matches: match one, break the extras as duplicates.
5. Anything else: `amount_mismatch` or `composite_mismatch`. Never forced.

**Two invariants run on every reconciliation, not just in tests.**

| Invariant | What it catches |
|---|---|
| Every expectation and every settlement row is claimed exactly once | A matcher that double counts, drops a line, or loses an orphan |
| Residual (expected minus settled) equals the sum of match deltas and break amounts | Arithmetic drift in how breaks are explained |

The second one matters because it is per currency: a currency mismatch has to show up as a
shortfall in one currency and a surplus in another, or the explanation is wrong. It is
asserted as an equality between two independently computed values, not as
`residual == 0`, because a sign flip passes a zero check on clean data and only surfaces
on dirty data.

**Ground truth is injected, not assumed.** The generator builds a clean day, then injects
six classes of break at disjoint references so labels cannot leak between classes.

### Decisions and tradeoffs

| Decision | Why | What it gives up |
|---|---|---|
| No fuzzy amount matching beyond 1 minor unit | Fuzzy matching is how recon engines hide mistakes | Genuine small variances need a policy change, deliberately |
| Reference is the join key | It is what PSPs actually send | Payments without a stable reference cannot be matched this way |
| Splits are matched, duplicates are broken | Both look like two lines; only the sum tells you which | A PSP that splits unevenly across days needs a wider window |
| Tolerance and window are a policy object, not constants | Finance owns the tolerance, not the code | More knobs to get wrong |
| Synthetic data only | Real settlement files are confidential | The format is a model of a PSP file, not a specific one |

## Run

```bash
uv sync

PYTHONPATH=. uv run python -m recon.cli demo    # prints a dirty day, break by break
PYTHONPATH=. uv run python -m recon.cli eval    # rewrites results/eval.md and eval.json
PYTHONPATH=. uv run python -m recon.cli bench   # rewrites results/bench.md

uv run pytest                                   # 87 tests, no network, no clock
```

The suite is deterministic: fixed seeds, no wall clock, no sleeps, no network. The bench is
the only timing dependent output and it is not asserted in CI.

## Results

Every number from `results/eval.md` and `results/bench.md`, produced by the commands above.
Policy: tolerance 1 minor unit, settlement window 3 days.

| Class | Injected | Detected | Recall | Precision | F1 |
|---|---|---|---|---|---|
| missing_in_settlement | 12 | 12 | 1.000 | 1.000 | 1.000 |
| unknown_in_settlement | 12 | 12 | 1.000 | 1.000 | 1.000 |
| amount_mismatch | 12 | 12 | 1.000 | 1.000 | 1.000 |
| duplicate_settlement | 12 | 12 | 1.000 | 1.000 | 1.000 |
| currency_mismatch | 12 | 12 | 1.000 | 1.000 | 1.000 |
| late_settlement | 12 | 12 | 1.000 | 1.000 | 1.000 |

Clean day, no breaks injected: **0 breaks raised**, 400 matches, 24 legitimate splits, 14
rounding rows inside tolerance. Both invariants hold.

Throughput: **21,171 settlement lines in 36 ms**, about 584,000 lines per second, single
core, with 500 injected breaks and both invariants holding.

Tests: **87 passing**, including 25 randomized days that assert the invariants on every one.

## Limits

- The breaks are synthetic and the classes are known. Perfect recall here means the cascade
  has no blind spot on these six classes. It does not mean this solves reconciliation in
  the wild.
- One currency per payment. There is no FX conversion, and a cross-currency settlement is
  treated as a break by design.
- No partial capture semantics. A payment captured for less than authorized is an amount
  mismatch here, which may be the wrong classification in a card context.
- The reference is assumed to be stable and unique. Real files sometimes reuse references
  across acquirers.
- A tolerance of one minor unit is a default, not a defensible accounting policy. It hides
  small real losses on purpose, and that tradeoff has to be an explicit decision in
  production.
- No persistence. Each run is a pure function over two in memory collections.

## Next

- FX aware matching: convert at a booked rate, then compare, and keep the rate as evidence.
- Partial capture and multi capture support with an authorization lifecycle.
- Settlement summary versus detail: reconcile the totals first, then the lines, which is how
  finance actually closes.
- A one page HTML report a treasury team would accept, instead of a markdown table.
- Persist to Postgres with an append only break table, so the aging of open items is
  queryable.

## Provenance

Built as a daily artifact in [fintech-lab](https://github.com/peebee1/fintech-lab), promoted
here because the measurement reproduced. The original directory stays there as the
historical record.

Licence: MIT.
