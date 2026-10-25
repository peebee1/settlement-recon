from datetime import date

import pytest

from recon.model import ParseError, parse_settlement_csv, parse_date, rows_to_csv

HEADER = "row_id,ref,currency,gross,fee,value_date,type\n"


def test_parses_a_clean_file():
    text = HEADER + "R1,ORD-1,EUR,100.00,1.50,2026-09-01,capture\n"
    rows = parse_settlement_csv(text)
    assert len(rows) == 1
    assert rows[0].net == 9850
    assert rows[0].value_date == date(2026, 9, 1)


def test_survives_bom_padding_and_accounting_negatives():
    text = "\ufeffrow_id , ref , currency , gross , fee , value_date , type\n"
    text += ' R1 , ORD-1 , eur , "1,100.00" , 1.50 , 01 Sep 2026 , capture \n'
    text += "R2,ORD-2,EUR,(25.00),0.00,2026-09-02,refund\n"
    rows = parse_settlement_csv(text)
    assert [row.ref for row in rows] == ["ORD-1", "ORD-2"]
    assert rows[0].currency == "EUR"
    assert rows[0].gross == 110000
    assert rows[1].net == -2500


def test_blank_reference_rows_are_skipped_not_guessed():
    text = HEADER + "R1,,EUR,10.00,0,2026-09-01,capture\n"
    assert parse_settlement_csv(text) == []


def test_missing_column_is_an_error_not_a_default():
    with pytest.raises(ParseError):
        parse_settlement_csv("row_id,ref,currency,gross\n1,A,EUR,10.00\n")


def test_bad_amount_names_the_row():
    text = HEADER + "R7,ORD-7,EUR,ten euros,0,2026-09-01,capture\n"
    with pytest.raises(ParseError, match="R7"):
        parse_settlement_csv(text)


def test_unknown_date_format_is_rejected():
    with pytest.raises(ParseError):
        parse_date("2026/13/45")


def test_csv_round_trip():
    text = HEADER + "R1,ORD-1,EUR,100.00,1.50,2026-09-01,capture\n"
    rows = parse_settlement_csv(text)
    again = parse_settlement_csv(rows_to_csv(rows))
    assert rows == again
