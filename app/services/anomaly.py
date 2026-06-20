"""anomaly.py — Anomaly detection pipeline (Step b)."""
from __future__ import annotations

from decimal import Decimal
from statistics import median

from app.config import get_settings


def detect_anomalies(rows: list[dict]) -> list[dict]:
    """
    Takes a list of cleaned row dicts.
    Returns the same list with 'is_anomaly' and 'anomaly_reason' fields set.
    """
    settings = get_settings()
    domestic = {m.lower() for m in settings.domestic_merchants}

    account_amounts: dict[str, list[Decimal]] = {}
    for row in rows:
        acct = row.get("account_id")
        amt = row.get("amount")
        if acct and amt is not None:
            account_amounts.setdefault(acct, []).append(amt)

    account_medians: dict[str, Decimal] = {}
    for acct, amounts in account_amounts.items():
        if amounts:
            med = median(amounts)
            account_medians[acct] = Decimal(str(med))

    for row in rows:
        reasons: list[str] = []

        acct = row.get("account_id")
        amt = row.get("amount")
        currency = (row.get("currency") or "").upper()
        merchant = (row.get("merchant") or "").strip().lower()

        if acct and amt is not None and acct in account_medians:
            med = account_medians[acct]
            if med > 0 and amt > med * 3:
                reasons.append(
                    f"Amount {amt} exceeds 3x account median ({med:.2f})"
                )

        if currency == "USD" and merchant in domestic:
            reasons.append(
                f"USD transaction at domestic-only merchant '{row.get('merchant')}'"
            )

        row["is_anomaly"] = len(reasons) > 0
        row["anomaly_reason"] = "; ".join(reasons) if reasons else None

    return rows
