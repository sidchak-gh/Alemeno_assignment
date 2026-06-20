"""
tasks.py — Celery task: process_job

Full 5-step pipeline:
  a) Data Cleaning
  b) Anomaly Detection
  c) LLM Classification
  d) LLM Narrative Summary
  e) Job Completion / Error Handling
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, update, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.worker.celery_app import celery_app
from app.services.csv_parser import parse_csv_file
from app.services.cleaner import clean_rows
from app.services.anomaly import detect_anomalies
from app.services.llm import classify_transactions, generate_narrative_summary

logger = logging.getLogger(__name__)

settings = get_settings()

# workers run sync code, so we need the psycopg2 driver instead of asyncpg
_SYNC_DB_URL = settings.database_url.replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
_engine = create_engine(_SYNC_DB_URL, pool_pre_ping=True)
SyncSession = sessionmaker(bind=_engine, autocommit=False, autoflush=False)


def _get_sync_db() -> Session:
    return SyncSession()


@celery_app.task(bind=True, name="app.worker.tasks.process_job")
def process_job(self, job_id: str, file_path: str) -> dict:
    """
    Main processing task. Runs the full 5-step pipeline synchronously.
    """
    # imported inside the function to avoid a circular import at startup
    from app.models.job import Job
    from app.models.transaction import Transaction
    from app.models.job_summary import JobSummary

    job_uuid = uuid.UUID(job_id)
    db = _get_sync_db()

    def _update_job_status(status: str, **kwargs):
        stmt = update(Job).where(Job.id == job_uuid).values(status=status, **kwargs)
        db.execute(stmt)
        db.commit()

    try:
        logger.info("Starting pipeline for job %s", job_id)
        _update_job_status("processing")

        logger.info("[%s] Step a: Cleaning data", job_id)
        file = Path(file_path)
        if not file.exists():
            raise FileNotFoundError(f"Upload file not found: {file_path}")

        raw_rows, raw_count = parse_csv_file(file)
        clean_data = clean_rows(raw_rows)
        logger.info("[%s] Cleaned: %d → %d rows", job_id, raw_count, len(clean_data))

        logger.info("[%s] Step b: Detecting anomalies", job_id)
        clean_data = detect_anomalies(clean_data)
        anomaly_count = sum(1 for r in clean_data if r.get("is_anomaly"))
        logger.info("[%s] Anomalies detected: %d", job_id, anomaly_count)

        logger.info("[%s] Step c: LLM classification", job_id)
        clean_data = classify_transactions(clean_data)

        logger.info("[%s] Persisting %d transactions", job_id, len(clean_data))
        txn_objects = [
            Transaction(
                job_id=job_uuid,
                txn_id=row.get("txn_id"),
                date=row.get("date"),
                merchant=row.get("merchant"),
                amount=row.get("amount"),
                currency=row.get("currency"),
                status=row.get("status"),
                category=row.get("category"),
                account_id=row.get("account_id"),
                notes=row.get("notes"),
                is_anomaly=row.get("is_anomaly", False),
                anomaly_reason=row.get("anomaly_reason"),
                llm_category=row.get("llm_category"),
                llm_raw_response=row.get("llm_raw_response"),
                llm_failed=row.get("llm_failed", False),
            )
            for row in clean_data
        ]
        db.add_all(txn_objects)
        db.commit()

        _update_job_status(
            "processing",
            row_count_raw=raw_count,
            row_count_clean=len(clean_data),
        )

        logger.info("[%s] Step d: Generating LLM summary", job_id)
        summary_data = generate_narrative_summary(clean_data)

        if summary_data:
            cat_breakdown = summary_data.pop("category_breakdown", {})
            summary_obj = JobSummary(
                job_id=job_uuid,
                total_spend_inr=Decimal(str(summary_data.get("total_spend_inr", 0))),
                total_spend_usd=Decimal(str(summary_data.get("total_spend_usd", 0))),
                top_merchants=summary_data.get("top_merchants"),
                anomaly_count=summary_data.get("anomaly_count", anomaly_count),
                narrative=summary_data.get("narrative"),
                risk_level=summary_data.get("risk_level", "medium"),
                category_breakdown=cat_breakdown,
            )
            db.add(summary_obj)
            db.commit()
        else:
            _build_fallback_summary(db, job_uuid, clean_data, anomaly_count, JobSummary)

        _update_job_status(
            "completed",
            completed_at=datetime.now(timezone.utc),
        )
        logger.info("[%s] Pipeline complete ✓", job_id)
        return {"status": "completed", "job_id": job_id}

    except Exception as exc:
        logger.exception("[%s] Pipeline failed: %s", job_id, exc)
        try:
            _update_job_status("failed", error_message=str(exc))
        except Exception:
            pass
        raise

    finally:
        db.close()


def _build_fallback_summary(db, job_uuid, rows, anomaly_count, JobSummary):
    """Build a basic summary without LLM when all retries fail."""
    from decimal import Decimal
    from collections import defaultdict

    inr_total = Decimal("0")
    usd_total = Decimal("0")
    merchant_totals: dict[str, Decimal] = defaultdict(Decimal)
    cat_breakdown: dict[str, float] = defaultdict(float)

    for row in rows:
        amt = row.get("amount") or Decimal("0")
        currency = (row.get("currency") or "").upper()
        merchant = row.get("merchant") or "Unknown"
        cat = row.get("llm_category") or row.get("category") or "Uncategorised"

        if currency == "INR":
            inr_total += amt
        elif currency == "USD":
            usd_total += amt

        merchant_totals[merchant] += amt
        cat_breakdown[cat] += float(amt)

    top_3 = sorted(merchant_totals.items(), key=lambda x: x[1], reverse=True)[:3]
    top_3_fmt = [{"merchant": m, "total": float(t)} for m, t in top_3]

    risk = "low" if anomaly_count == 0 else ("high" if anomaly_count >= 5 else "medium")

    summary_obj = JobSummary(
        job_id=job_uuid,
        total_spend_inr=inr_total,
        total_spend_usd=usd_total,
        top_merchants=top_3_fmt,
        anomaly_count=anomaly_count,
        narrative="LLM summary unavailable. Statistical summary generated automatically.",
        risk_level=risk,
        category_breakdown=dict(cat_breakdown),
    )
    db.add(summary_obj)
    db.commit()
