"""The matcher.

One rule governs everything here: every expected payment and every settlement line must
end up in exactly one place, either a match or a break. If a line is claimed twice, the
reconciliation is lying, and the ledger will not balance at month end.

Matching is a fixed cascade, not a similarity score. Fuzzy matching is how real recon
engines hide their mistakes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import Expectation, SettlementRow

BREAK_KINDS = (
    "missing_in_settlement",
    "unknown_in_settlement",
    "amount_mismatch",
    "duplicate_settlement",
    "currency_mismatch",
    "composite_mismatch",
)

FLAGS = ("late_settlement", "amount_tolerance", "split_settlement")


@dataclass(frozen=True)
class Policy:
    """What a break is allowed to look like before it counts as a break."""

    tolerance_minor: int = 1
    date_window_days: int = 3


@dataclass(frozen=True)
class Match:
    ref: str
    expectation: Expectation
    rows: tuple[SettlementRow, ...]
    flags: frozenset[str] = frozenset()

    @property
    def settled_net(self) -> int:
        return sum(row.net for row in self.rows)

    @property
    def delta(self) -> int:
        """Positive means we were settled more than expected."""
        return self.settled_net - self.expectation.net


@dataclass(frozen=True)
class Break:
    ref: str
    kind: str
    detail: str
    contributions: dict[str, int] = field(default_factory=dict)
    row_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in BREAK_KINDS:
            raise ValueError(f"unknown break kind: {self.kind}")


@dataclass
class Reconciliation:
    expectations: list[Expectation]
    rows: list[SettlementRow]
    policy: Policy
    matches: list[Match] = field(default_factory=list)
    breaks: list[Break] = field(default_factory=list)

    # ---- invariants -------------------------------------------------

    def residual(self) -> dict[str, int]:
        """Expected minus settled, per currency. This is the money we cannot account for yet."""
        out: dict[str, int] = {}
        for exp in self.expectations:
            out[exp.currency] = out.get(exp.currency, 0) + exp.net
        for row in self.rows:
            out[row.currency] = out.get(row.currency, 0) - row.net
        return out

    def explained(self) -> dict[str, int]:
        """Residual as reconstructed from matches and breaks. Must equal residual()."""
        out: dict[str, int] = {}
        for match in self.matches:
            currency = match.expectation.currency
            out[currency] = out.get(currency, 0) - match.delta
        for brk in self.breaks:
            for currency, amount in brk.contributions.items():
                out[currency] = out.get(currency, 0) + amount
        return out

    def balances(self) -> bool:
        residual = self.residual()
        explained = self.explained()
        for currency in set(residual) | set(explained):
            if residual.get(currency, 0) != explained.get(currency, 0):
                return False
        return True

    def every_line_accounted(self) -> bool:
        """No expectation and no settlement row may be silently dropped."""
        seen_exp: list[str] = [m.ref for m in self.matches]
        seen_rows: list[str] = [row.row_id for m in self.matches for row in m.rows]

        for brk in self.breaks:
            if brk.kind in {"missing_in_settlement", "amount_mismatch", "composite_mismatch",
                            "currency_mismatch"}:
                seen_exp.append(brk.ref)
            seen_rows.extend(brk.row_ids)

        expected_refs = [e.ref for e in self.expectations]
        return (
            sorted(seen_exp) == sorted(expected_refs)
            and sorted(seen_rows) == sorted(r.row_id for r in self.rows)
        )

    # ---- reporting --------------------------------------------------

    def by_kind(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for brk in self.breaks:
            out[brk.kind] = out.get(brk.kind, 0) + 1
        return out

    def by_flag(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for match in self.matches:
            for flag in match.flags:
                out[flag] = out.get(flag, 0) + 1
        return out

    def matched_total(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for match in self.matches:
            currency = match.expectation.currency
            out[currency] = out.get(currency, 0) + match.settled_net
        return out


def reconcile(
    expectations: list[Expectation],
    rows: list[SettlementRow],
    policy: Policy | None = None,
) -> Reconciliation:
    policy = policy or Policy()
    result = Reconciliation(expectations=list(expectations), rows=list(rows), policy=policy)

    exp_by_ref: dict[str, Expectation] = {e.ref: e for e in expectations}
    rows_by_ref: dict[str, list[SettlementRow]] = {}
    for row in rows:
        rows_by_ref.setdefault(row.ref, []).append(row)

    for ref in sorted(set(exp_by_ref) | set(rows_by_ref)):
        exp = exp_by_ref.get(ref)
        ref_rows = rows_by_ref.get(ref, [])

        if exp is None:
            for row in ref_rows:
                result.breaks.append(Break(
                    ref=ref,
                    kind="unknown_in_settlement",
                    detail=f"{row.describe()} has no expected payment in the ledger",
                    contributions={row.currency: -row.net},
                    row_ids=(row.row_id,),
                ))
            continue

        if not ref_rows:
            result.breaks.append(Break(
                ref=ref,
                kind="missing_in_settlement",
                detail=f"{exp.describe()} never appears in the settlement file",
                contributions={exp.currency: exp.net},
            ))
            continue

        same: list[SettlementRow] = []
        counted_expectation = False
        for row in ref_rows:
            if row.currency != exp.currency:
                contributions = {row.currency: -row.net}
                if not counted_expectation:
                    contributions[exp.currency] = exp.net
                    counted_expectation = True
                result.breaks.append(Break(
                    ref=ref,
                    kind="currency_mismatch",
                    detail=f"expected {exp.currency}, {row.describe()} arrived in {row.currency}",
                    contributions=contributions,
                    row_ids=(row.row_id,),
                ))
            else:
                same.append(row)
        if not same:
            continue

        total = sum(row.net for row in same)
        delta = total - exp.net
        flags: set[str] = set()

        if abs(delta) <= policy.tolerance_minor:
            if len(same) > 1:
                flags.add("split_settlement")
            if delta:
                flags.add("amount_tolerance")
            flags |= _timing_flags(exp, same, policy)
            result.matches.append(Match(ref=ref, expectation=exp,
                                        rows=tuple(same), flags=frozenset(flags)))
            continue

        # A duplicated line looks like a sum that is too large, while one line on its own
        # still matches. Match the line, blame the extra ones. Anything else is a real
        # composite problem and must not be forced into a match.
        candidates = [row for row in same if abs(row.net - exp.net) <= policy.tolerance_minor]
        if len(same) > 1 and candidates:
            keeper = candidates[0]
            extras = [r for r in same if r.row_id != keeper.row_id]
            flags = _timing_flags(exp, [keeper], policy)
            result.matches.append(Match(ref=ref, expectation=exp,
                                        rows=(keeper,), flags=frozenset(flags)))
            for extra in extras:
                result.breaks.append(Break(
                    ref=ref,
                    kind="duplicate_settlement",
                    detail=f"{extra.describe()} repeats a line already settled",
                    contributions={extra.currency: -extra.net},
                    row_ids=(extra.row_id,),
                ))
            continue

        result.breaks.append(Break(
            ref=ref,
            kind="amount_mismatch" if len(same) == 1 else "composite_mismatch",
            detail=f"expected {exp.net} minor units, settled {total} across {len(same)} line(s)",
            contributions={exp.currency: exp.net - total},
            row_ids=tuple(row.row_id for row in same),
        ))

    return result


def _timing_flags(exp: Expectation, rows: list[SettlementRow], policy: Policy) -> set[str]:
    latest = max(row.value_date for row in rows)
    return {"late_settlement"} if (latest - exp.value_date).days > policy.date_window_days else set()
