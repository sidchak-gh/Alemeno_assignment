"""llm.py — Gemini LLM integration: batched classification and narrative summary."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import google.generativeai as genai
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from app.config import get_settings

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {
    "Food", "Shopping", "Travel", "Transport",
    "Utilities", "Cash Withdrawal", "Entertainment", "Other",
}


def _get_model() -> genai.GenerativeModel:
    settings = get_settings()
    genai.configure(api_key=settings.gemini_api_key)
    return genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        generation_config=genai.GenerationConfig(
            temperature=0.1,
            response_mime_type="application/json",
        ),
    )


def _make_retry():
    return retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )


CLASSIFICATION_PROMPT = """You are a financial transaction classifier.
Classify each transaction into exactly one of these categories:
Food, Shopping, Travel, Transport, Utilities, Cash Withdrawal, Entertainment, Other.

Return ONLY a JSON array in this exact format:
[{"txn_index": 0, "category": "Food"}, ...]

Transactions to classify:
{transactions}
"""


@_make_retry()
def _call_classify(transactions_json: str) -> str:
    model = _get_model()
    prompt = CLASSIFICATION_PROMPT.format(transactions=transactions_json)
    response = model.generate_content(prompt)
    return response.text


def classify_transactions(rows: list[dict]) -> list[dict]:
    """
    For transactions with category == 'Uncategorised', call Gemini to assign a category.
    Updates 'llm_category' on each row in-place.
    On LLM failure, sets 'llm_failed' = True for all rows in the batch.
    Returns the rows list (modified in place).
    """
    uncategorised = [
        (i, row) for i, row in enumerate(rows)
        if row.get("category") == "Uncategorised" and not row.get("llm_failed")
    ]

    if not uncategorised:
        return rows

    # pack all uncategorised transactions into one prompt so we make a single API call
    batch = [
        {
            "txn_index": batch_idx,
            "merchant": row.get("merchant", ""),
            "amount": float(row.get("amount") or 0),
            "currency": row.get("currency", ""),
            "notes": row.get("notes", "") or "",
        }
        for batch_idx, (_, row) in enumerate(uncategorised)
    ]

    try:
        raw_response = _call_classify(json.dumps(batch, ensure_ascii=False))
        
        clean = re.sub(r"```(?:json)?\s*|\s*```", "", raw_response).strip()
        results: list[dict] = json.loads(clean)

       
        result_map = {r["txn_index"]: r.get("category", "Other") for r in results}
        for batch_idx, (orig_idx, row) in enumerate(uncategorised):
            cat = result_map.get(batch_idx, "Other")
            row["llm_category"] = cat if cat in VALID_CATEGORIES else "Other"
            row["llm_raw_response"] = raw_response  

    except Exception as exc:
        logger.error("LLM classification failed after retries: %s", exc)
        for _, (_, row) in enumerate(uncategorised):
            row["llm_failed"] = True
            row["llm_raw_response"] = str(exc)  

    return rows



SUMMARY_PROMPT = """You are a financial analyst AI. Analyze these transactions and return a JSON summary.

Return ONLY valid JSON with exactly these fields:
{{
  "total_spend_inr": <float>,
  "total_spend_usd": <float>,
  "top_merchants": [
    {{"merchant": "name", "total": <float>}},
    ...3 entries max...
  ],
  "anomaly_count": <int>,
  "narrative": "<2-3 sentence spending summary>",
  "risk_level": "<low|medium|high>"
}}

Risk assessment: low = normal patterns, medium = some anomalies or high spend,
high = multiple anomalies, very high amounts, or suspicious patterns.

Transaction data:
Total rows: {total_rows}
Anomaly count: {anomaly_count}
INR transactions: {inr_data}
USD transactions: {usd_data}
Top merchants by spend: {merchant_data}
Category breakdown: {category_data}
Flagged anomalies: {anomaly_data}
"""


@_make_retry()
def _call_summary(prompt: str) -> str:
    model = _get_model()
    response = model.generate_content(prompt)
    return response.text


def generate_narrative_summary(rows: list[dict]) -> dict[str, Any] | None:
    """
    Generate a JSON narrative summary for all transactions using Gemini.
    Returns parsed dict or None on failure.
    """
    from decimal import Decimal
    from collections import defaultdict

    inr_total = Decimal("0")
    usd_total = Decimal("0")
    merchant_totals: dict[str, Decimal] = defaultdict(Decimal)
    anomaly_count = 0
    anomalies_info: list[dict] = []

    for row in rows:
        amt = row.get("amount") or Decimal("0")
        currency = (row.get("currency") or "").upper()
        merchant = row.get("merchant") or "Unknown"

        if currency == "INR":
            inr_total += amt
            merchant_totals[merchant] += amt
        elif currency == "USD":
            usd_total += amt
            merchant_totals[merchant] += amt

        if row.get("is_anomaly"):
            anomaly_count += 1
            anomalies_info.append({
                "txn_id": row.get("txn_id"),
                "merchant": merchant,
                "amount": float(amt),
                "reason": row.get("anomaly_reason"),
            })

    top_3 = sorted(merchant_totals.items(), key=lambda x: x[1], reverse=True)[:3]
    top_3_fmt = [{"merchant": m, "total": float(t)} for m, t in top_3]

    cat_breakdown: dict[str, float] = defaultdict(float)
    for row in rows:
        cat = row.get("llm_category") or row.get("category") or "Uncategorised"
        amt = float(row.get("amount") or 0)
        cat_breakdown[cat] += amt

    prompt = SUMMARY_PROMPT.format(
        total_rows=len(rows),
        anomaly_count=anomaly_count,
        inr_data=f"INR {float(inr_total):.2f}",
        usd_data=f"USD {float(usd_total):.2f}",
        merchant_data=json.dumps(top_3_fmt),
        category_data=json.dumps(dict(cat_breakdown)),
        anomaly_data=json.dumps(anomalies_info[:10]),  # limit for token budget
    )

    try:
        raw = _call_summary(prompt)
        clean = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
        parsed: dict[str, Any] = json.loads(clean)
        # fill in any fields the LLM might have skipped
        parsed.setdefault("risk_level", "medium")
        parsed["category_breakdown"] = dict(cat_breakdown)
        return parsed
    except Exception as exc:
        logger.error("LLM summary generation failed after retries: %s", exc)
        return None
