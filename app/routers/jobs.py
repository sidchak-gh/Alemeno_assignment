"""jobs.py — All /jobs/* API endpoints."""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.job import Job
from app.models.transaction import Transaction
from app.models.job_summary import JobSummary
from app.schemas.job import (
    JobCreatedResponse,
    JobStatusResponse,
    JobListItem,
    JobResultsResponse,
    JobSummaryOut,
    TransactionOut,
)
from app.services.csv_parser import parse_csv_bytes, CSVValidationError

router = APIRouter(prefix="/jobs", tags=["Jobs"])

UPLOAD_DIR = Path("/tmp/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_STATUSES = {"pending", "processing", "completed", "failed"}


@router.post("/upload", response_model=JobCreatedResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_csv(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Accept a CSV upload, validate it, create a Job, and enqueue processing."""

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400, detail="Only .csv files are accepted."
        )

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        _, raw_count = parse_csv_bytes(content)
    except CSVValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    job_id = uuid.uuid4()
    save_path = UPLOAD_DIR / f"{job_id}.csv"
    save_path.write_bytes(content)

    job = Job(
        id=job_id,
        filename=file.filename,
        status="pending",
        row_count_raw=raw_count,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # kick off the background worker — imported here to avoid a circular import
    from app.worker.tasks import process_job
    process_job.delay(str(job_id), str(save_path))

    return JobCreatedResponse(
        job_id=job.id,
        status=job.status,
        filename=job.filename,
        row_count_raw=job.row_count_raw,
    )


@router.get("/{job_id}/status", response_model=JobStatusResponse)
async def get_job_status(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Return current job status. Includes summary if completed."""
    job = await _get_job_or_404(db, job_id)
    summary = None

    if job.status == "completed" and job.summary:
        summary = JobSummaryOut.model_validate(job.summary)

    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        filename=job.filename,
        created_at=job.created_at,
        completed_at=job.completed_at,
        row_count_raw=job.row_count_raw,
        row_count_clean=job.row_count_clean,
        summary=summary,
        error_message=job.error_message,
    )


@router.get("/{job_id}/results", response_model=JobResultsResponse)
async def get_job_results(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Return full results: transactions, anomalies, categories, LLM summary."""
    job = await _get_job_or_404(db, job_id)

    if job.status not in ("completed", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Job is not yet complete (status: {job.status}). Poll /status first.",
        )

    result = await db.execute(
        select(Transaction).where(Transaction.job_id == job_id)
    )
    transactions = result.scalars().all()

    anomalies = [t for t in transactions if t.is_anomaly]

    breakdown: dict[str, float] = {}
    for t in transactions:
        cat = t.llm_category or t.category or "Uncategorised"
        breakdown[cat] = breakdown.get(cat, 0.0) + float(t.amount or 0)

    llm_summary = None
    if job.summary:
        llm_summary = JobSummaryOut.model_validate(job.summary)

    return JobResultsResponse(
        job_id=job.id,
        status=job.status,
        transactions=[TransactionOut.model_validate(t) for t in transactions],
        anomalies=[TransactionOut.model_validate(t) for t in anomalies],
        category_breakdown=breakdown,
        llm_summary=llm_summary,
    )


@router.get("", response_model=list[JobListItem])
async def list_jobs(
    status: str | None = Query(default=None, description="Filter by status"),
    db: AsyncSession = Depends(get_db),
):
    """List all jobs, optionally filtered by status."""
    if status and status not in ALLOWED_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status filter. Must be one of: {', '.join(ALLOWED_STATUSES)}",
        )

    stmt = select(Job).order_by(Job.created_at.desc())
    if status:
        stmt = stmt.where(Job.status == status)

    result = await db.execute(stmt)
    jobs = result.scalars().all()

    return [
        JobListItem(
            job_id=j.id,
            filename=j.filename,
            status=j.status,
            row_count_raw=j.row_count_raw,
            created_at=j.created_at,
        )
        for j in jobs
    ]


async def _get_job_or_404(db: AsyncSession, job_id: uuid.UUID) -> Job:
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")
    return job
