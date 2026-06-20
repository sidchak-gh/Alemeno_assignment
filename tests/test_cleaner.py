"""
test_cleaner.py — Unit tests for the data cleaning service.
"""
import pytest
from datetime import date
from decimal import Decimal

from app.services.cleaner import parse_date, parse_amount, clean_row, clean_rows


# ── Date parsing ──────────────────────────────────────────────────────────────

class TestParseDate:
    def test_dd_mm_yyyy(self):
        assert parse_date("04-09-2024") == date(2024, 9, 4)

    def test_yyyy_slash_mm_slash_dd(self):
        assert parse_date("2024/02/05") == date(2024, 2, 5)

    def test_iso_format(self):
        assert parse_date("2024-07-15") == date(2024, 7, 15)

    def test_leap_day_valid(self):
        # 2024 IS a leap year — should parse correctly
        assert parse_date("2024/02/29") == date(2024, 2, 29)

    def test_empty_string(self):
        assert parse_date("") is None

    def test_invalid_date(self):
        assert parse_date("not-a-date") is None

    def test_stripping_spaces(self):
        assert parse_date("  17-02-2024  ") == date(2024, 2, 17)


# ── Amount parsing ────────────────────────────────────────────────────────────

class TestParseAmount:
    def test_plain_number(self):
        assert parse_amount("10882.55") == Decimal("10882.55")

    def test_dollar_prefix(self):
        assert parse_amount("$11325.79") == Decimal("11325.79")

    def test_dollar_prefix_2(self):
        assert parse_amount("$12092.64") == Decimal("12092.64")

    def test_integer_amount(self):
        assert parse_amount("500") == Decimal("500")

    def test_empty(self):
        assert parse_amount("") is None

    def test_whitespace_only(self):
        assert parse_amount("   ") is None


# ── Row cleaning ──────────────────────────────────────────────────────────────

class TestCleanRow:
    def test_normalises_currency_to_uppercase(self):
        row = {"txn_id": "T1", "date": "01-01-2024", "merchant": "Ola",
               "amount": "100", "currency": "inr", "status": "success",
               "category": "Transport", "account_id": "ACC1", "notes": ""}
        result = clean_row(row)
        assert result["currency"] == "INR"

    def test_normalises_status_to_uppercase(self):
        row = {"txn_id": "T1", "date": "01-01-2024", "merchant": "Amazon",
               "amount": "200", "currency": "INR", "status": "failed",
               "category": "Shopping", "account_id": "ACC1", "notes": ""}
        result = clean_row(row)
        assert result["status"] == "FAILED"

    def test_fills_missing_category_with_uncategorised(self):
        row = {"txn_id": "T1", "date": "01-01-2024", "merchant": "Unknown",
               "amount": "50", "currency": "INR", "status": "SUCCESS",
               "category": "", "account_id": "ACC1", "notes": ""}
        result = clean_row(row)
        assert result["category"] == "Uncategorised"

    def test_blank_txn_id_becomes_none(self):
        row = {"txn_id": "", "date": "01-01-2024", "merchant": "Swiggy",
               "amount": "300", "currency": "INR", "status": "SUCCESS",
               "category": "Food", "account_id": "ACC1", "notes": ""}
        result = clean_row(row)
        assert result["txn_id"] is None

    def test_strips_dollar_from_amount(self):
        row = {"txn_id": "T2", "date": "2024/06/03", "merchant": "Jio Recharge",
               "amount": "$12092.64", "currency": "INR", "status": "failed",
               "category": "Utilities", "account_id": "ACC3", "notes": ""}
        result = clean_row(row)
        assert result["amount"] == Decimal("12092.64")


# ── Deduplication ─────────────────────────────────────────────────────────────

class TestCleanRows:
    def _make_rows(self, n=1):
        return [
            {
                "txn_id": "TXN1009",
                "date": "11-03-2024",
                "merchant": "MakeMyTrip",
                "amount": "7428.06",
                "currency": "USD",
                "status": "success",
                "category": "Travel",
                "account_id": "ACC004",
                "notes": "SUSPICIOUS",
            }
        ] * n

    def test_removes_exact_duplicates(self):
        raw = self._make_rows(3)
        result = clean_rows(raw)
        assert len(result) == 1

    def test_keeps_distinct_rows(self):
        raw = [
            {"txn_id": "TXN001", "date": "01-01-2024", "merchant": "A",
             "amount": "100", "currency": "INR", "status": "SUCCESS",
             "category": "Food", "account_id": "ACC1", "notes": ""},
            {"txn_id": "TXN002", "date": "02-01-2024", "merchant": "B",
             "amount": "200", "currency": "INR", "status": "SUCCESS",
             "category": "Shopping", "account_id": "ACC1", "notes": ""},
        ]
        result = clean_rows(raw)
        assert len(result) == 2

    def test_real_csv_duplicates(self):
        """Simulate the actual duplicate pattern in transactions.csv."""
        # TXN1009 appears twice in the CSV
        raw = self._make_rows(2)
        result = clean_rows(raw)
        assert len(result) == 1
