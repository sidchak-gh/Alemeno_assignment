import uuid
from datetime import datetime, date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    txn_id: str | None
    date: date | None
    merchant: str | None
    amount: Decimal | None
    currency: str | None
    status: str | None
    category: str | None
    account_id: str | None
    notes: str | None
    is_anomaly: bool
    anomaly_reason: str | None
    llm_category: str | None
    llm_failed: bool


class JobSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_spend_inr: Decimal | None
    total_spend_usd: Decimal | None
    top_merchants: Any | None
    anomaly_count: int | None
    narrative: str | None
    risk_level: str | None
    category_breakdown: Any | None


class JobCreatedResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    filename: str
    row_count_raw: int | None


class JobStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: uuid.UUID
    status: str
    filename: str
    created_at: datetime
    completed_at: datetime | None
    row_count_raw: int | None
    row_count_clean: int | None
    summary: JobSummaryOut | None = None
    error_message: str | None = None


class JobListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: uuid.UUID
    filename: str
    status: str
    row_count_raw: int | None
    created_at: datetime


class JobResultsResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    transactions: list[TransactionOut]
    anomalies: list[TransactionOut]
    category_breakdown: dict[str, Any]
    llm_summary: JobSummaryOut | None
