"""
test_anomaly.py — Unit tests for anomaly detection.
"""
import pytest
from decimal import Decimal

from app.services.anomaly import detect_anomalies


def _make_row(txn_id, merchant, amount, currency, account_id="ACC001"):
    return {
        "txn_id": txn_id,
        "date": None,
        "merchant": merchant,
        "amount": Decimal(str(amount)),
        "currency": currency,
        "status": "SUCCESS",
        "category": "Other",
        "account_id": account_id,
        "notes": None,
    }


class TestStatisticalOutlier:
    def test_flags_amount_exceeding_3x_median(self):
        rows = [
            _make_row("T1", "Amazon", 1000, "INR"),
            _make_row("T2", "Amazon", 1200, "INR"),
            _make_row("T3", "Amazon", 900, "INR"),
            _make_row("T4", "Amazon", 50000, "INR"),  
        ]
        result = detect_anomalies(rows)
        anomalies = [r for r in result if r["is_anomaly"]]
        assert len(anomalies) == 1
        assert anomalies[0]["txn_id"] == "T4"
        assert "median" in anomalies[0]["anomaly_reason"].lower()

    def test_does_not_flag_normal_amounts(self):
        rows = [
            _make_row("T1", "Amazon", 1000, "INR"),
            _make_row("T2", "Amazon", 1100, "INR"),
            _make_row("T3", "Amazon", 1200, "INR"),
            _make_row("T4", "Amazon", 1300, "INR"),
        ]
        result = detect_anomalies(rows)
        assert all(not r["is_anomaly"] for r in result)

    def test_outlier_per_account_not_global(self):
        """An amount that is 3x the median for one account should not
        flag a different account where that amount is normal."""
        rows = [
            # ACC001: small amounts
            _make_row("T1", "Amazon", 100, "INR", "ACC001"),
            _make_row("T2", "Amazon", 110, "INR", "ACC001"),
            _make_row("T3", "Amazon", 90, "INR", "ACC001"),
            # ACC002: large amounts — 5000 is NOT an outlier here
            _make_row("T4", "Amazon", 5000, "INR", "ACC002"),
            _make_row("T5", "Amazon", 5200, "INR", "ACC002"),
            _make_row("T6", "Amazon", 4800, "INR", "ACC002"),
        ]
        result = detect_anomalies(rows)
        assert all(not r["is_anomaly"] for r in result)

    def test_txn2000_style_outlier(self):
        """Simulate the massive TXN2000-2004 amounts from the real CSV."""
        rows = [
            _make_row(f"TXN{i}", "Jio Recharge", 10000 + i * 100, "INR", "ACC002")
            for i in range(10)
        ]
        rows.append(_make_row("TXN2000", "Jio Recharge", 175917, "INR", "ACC002"))
        result = detect_anomalies(rows)
        outliers = [r for r in result if r["is_anomaly"]]
        assert any(r["txn_id"] == "TXN2000" for r in outliers)


class TestCurrencyMerchantMismatch:
    def test_flags_usd_at_swiggy(self):
        rows = [_make_row("T1", "Swiggy", 500, "USD")]
        result = detect_anomalies(rows)
        assert result[0]["is_anomaly"]
        assert "domestic" in result[0]["anomaly_reason"].lower()

    def test_flags_usd_at_ola(self):
        rows = [_make_row("T1", "Ola", 200, "USD")]
        result = detect_anomalies(rows)
        assert result[0]["is_anomaly"]

    def test_flags_usd_at_irctc(self):
        rows = [_make_row("T1", "IRCTC", 1000, "USD")]
        result = detect_anomalies(rows)
        assert result[0]["is_anomaly"]

    def test_does_not_flag_inr_at_swiggy(self):
        rows = [_make_row("T1", "Swiggy", 300, "INR")]
        result = detect_anomalies(rows)
        assert not result[0]["is_anomaly"]

    def test_does_not_flag_usd_at_makemytrip(self):
        """MakeMyTrip is international-capable — should not be flagged."""
        rows = [_make_row("T1", "MakeMyTrip", 200, "USD")]
        result = detect_anomalies(rows)
        assert not result[0]["is_anomaly"]

    def test_both_anomaly_reasons_combined(self):
        """A row can trigger BOTH rules."""
        rows = [
            _make_row("T1", "Swiggy", 5, "INR", "ACC001"),    # normal
            _make_row("T2", "Swiggy", 5, "INR", "ACC001"),    # normal
            _make_row("T3", "Swiggy", 50000, "USD", "ACC001"),# outlier + USD mismatch
        ]
        result = detect_anomalies(rows)
        big = next(r for r in result if r["txn_id"] == "T3")
        assert big["is_anomaly"]
        assert "median" in big["anomaly_reason"].lower()
        assert "domestic" in big["anomaly_reason"].lower()
