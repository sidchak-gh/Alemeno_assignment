"""cleaner.py — Data cleaning pipeline (Step a)."""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


DATE_FORMATS = [
    "%d-%m-%Y",       # e.g. 15-07-2024
    "%Y/%m/%d",       # e.g. 2024/07/15
    "%Y-%m-%d",       # standard ISO format
    "%m/%d/%Y",       # US format, last resort
]


def parse_date(raw: str) -> date | None:
    """Try every known format return None if none match."""
    raw = raw.strip()
    if not raw:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


_AMOUNT_STRIP = re.compile(r"[^\d.]")


def parse_amount(raw: str) -> Decimal | None:
    """Strip non-numeric characters (like $) and parse to Decimal."""
    raw = raw.strip()
    if not raw:
        return None
    cleaned = _AMOUNT_STRIP.sub("", raw)
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def clean_row(row: dict) -> dict:
    """
    Takes a raw parsed row dict and returns a cleaned dict.
    All fields are normalised; None is used for genuinely missing values.
    """
    txn_id = row.get("txn_id", "").strip() or None
    merchant = row.get("merchant", "").strip() or None
    account_id = row.get("account_id", "").strip() or None
    notes = row.get("notes", "").strip() or None

    raw_category = row.get("category", "").strip()
    category = raw_category if raw_category else "Uncategorised"

    raw_currency = row.get("currency", "").strip()
    currency = raw_currency.upper() if raw_currency else None

    raw_status = row.get("status", "").strip()
    status = raw_status.upper() if raw_status else None

    parsed_date = parse_date(row.get("date", ""))
    parsed_amount = parse_amount(row.get("amount", ""))

    return {
        "txn_id": txn_id,
        "date": parsed_date,
        "merchant": merchant,
        "amount": parsed_amount,
        "currency": currency,
        "status": status,
        "category": category,
        "account_id": account_id,
        "notes": notes,
    }


def _row_fingerprint(row: dict) -> tuple:
    """Tuple of all field values used to detect exact duplicates."""
    return (
        row["txn_id"],
        str(row["date"]),
        row["merchant"],
        str(row["amount"]),
        row["currency"],
        row["status"],
        row["category"],
        row["account_id"],
        row["notes"],
    )


def clean_rows(raw_rows: list[dict]) -> list[dict]:
    """
    Clean all rows and remove exact duplicates.
    Returns a deduplicated list of cleaned dicts.
    """
    cleaned: list[dict] = [clean_row(r) for r in raw_rows]

    seen: set[tuple] = set()
    unique: list[dict] = []
    for row in cleaned:
        fp = _row_fingerprint(row)
        if fp not in seen:
            seen.add(fp)
            unique.append(row)

    return unique
