"""What we expect to be settled, and what the PSP says was settled."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .money import format_minor, parse_minor, validate_currency


class ParseError(ValueError):
    """A settlement file row we refuse to guess about."""


@dataclass(frozen=True)
class Expectation:
    """Our side of the books: one payment we believe the PSP owes us."""

    ref: str
    currency: str
    gross: int
    fee: int
    value_date: date

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", validate_currency(self.currency))

    @property
    def net(self) -> int:
        return self.gross - self.fee

    def describe(self) -> str:
        return f"{self.ref} {format_minor(self.net, self.currency)} on {self.value_date}"


@dataclass(frozen=True)
class SettlementRow:
    """The PSP's side: one line from the settlement file."""

    row_id: str
    ref: str
    currency: str
    gross: int
    fee: int
    value_date: date
    kind: str = "capture"

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", validate_currency(self.currency))

    @property
    def net(self) -> int:
        return self.gross - self.fee

    def describe(self) -> str:
        return f"row {self.row_id} {self.ref} {format_minor(self.net, self.currency)}"


_DATE_FORMATS = ("%Y-%m-%d", "%d %b %Y", "%d/%m/%Y")


def parse_date(raw: str) -> date:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    raise ParseError(f"unrecognised date: {raw!r}")


def parse_settlement_csv(text: str) -> list[SettlementRow]:
    """Parse a PSP settlement export.

    Handles the things real files do: a UTF-8 BOM, padded cells, spaces before a quoted
    field (which is how csv quoting silently breaks), thousands separators, and negative
    amounts in parentheses.

    A row with the wrong number of fields is an error, not a row to guess about.
    """
    if text.startswith("\ufeff"):
        text = text[1:]
    reader = csv.reader(io.StringIO(text), skipinitialspace=True)
    grid = [row for row in reader if any(cell.strip() for cell in row)]
    if not grid:
        raise ParseError("empty file")

    header = [cell.strip() for cell in grid[0]]
    required = {"row_id", "ref", "currency", "gross", "fee", "value_date"}
    missing = required - set(header)
    if missing:
        raise ParseError(f"missing columns: {sorted(missing)}")
    if len(set(header)) != len(header):
        raise ParseError(f"duplicate column names: {sorted(header)}")

    out: list[SettlementRow] = []
    for line_no, cells in enumerate(grid[1:], start=2):
        if len(cells) != len(header):
            raise ParseError(
                f"line {line_no}: {len(cells)} fields, header has {len(header)}"
            )
        clean = {name: cells[i].strip() for i, name in enumerate(header)}
        if not clean.get("ref"):
            continue
        try:
            out.append(
                SettlementRow(
                    row_id=clean["row_id"],
                    ref=clean["ref"],
                    currency=clean["currency"],
                    gross=parse_minor(clean["gross"]),
                    fee=parse_minor(clean["fee"] or "0"),
                    value_date=parse_date(clean["value_date"]),
                    kind=clean.get("type") or "capture",
                )
            )
        except (KeyError, ValueError) as exc:
            raise ParseError(f"bad row {clean.get('row_id', '?')}: {exc}") from exc
    return out


def rows_to_csv(rows: list[SettlementRow]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["row_id", "ref", "currency", "gross", "fee", "value_date", "type"])
    for row in rows:
        writer.writerow([
            row.row_id,
            row.ref,
            row.currency,
            format_minor(row.gross).replace(",", "").replace(" ", ""),
            format_minor(row.fee).replace(",", "").replace(" ", ""),
            row.value_date.isoformat(),
            row.kind,
        ])
    return out.getvalue()


def load_csv(path: Path) -> list[SettlementRow]:
    return parse_settlement_csv(path.read_text(encoding="utf-8"))
