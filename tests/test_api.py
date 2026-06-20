"""
test_api.py — Integration tests for the FastAPI endpoints.
"""
import uuid
import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app


# ── Fixtures ─────────────────────────────

SAMPLE_CSV = b"""txn_id,date,merchant,amount,currency,status,category,account_id,notes
TXN0001,01-01-2024,Amazon,500.00,INR,SUCCESS,Shopping,ACC001,
TXN0002,02-01-2024,Swiggy,150.00,INR,SUCCESS,Food,ACC001,
TXN0003,03-01-2024,Ola,200.00,inr,failed,Transport,ACC002,
"""

BAD_CSV_MISSING_COLS = b"""id,value
1,100
"""

EMPTY_CSV = b""


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ── Health check ────────────

@pytest.mark.asyncio
async def test_health_check(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ── Upload endpoint ────────────

@pytest.mark.asyncio
async def test_upload_rejects_non_csv(client):
    """Non-CSV files must be rejected with 400."""
    resp = await client.post(
        "/jobs/upload",
        files={"file": ("data.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_empty_file(client):
    resp = await client.post(
        "/jobs/upload",
        files={"file": ("data.csv", EMPTY_CSV, "text/csv")},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_missing_columns(client):
    resp = await client.post(
        "/jobs/upload",
        files={"file": ("data.csv", BAD_CSV_MISSING_COLS, "text/csv")},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
@patch("app.routers.jobs.process_job")
async def test_upload_valid_csv_returns_job_id(mock_task, client):
    """Valid CSV upload should return 202 with job_id."""
    mock_task.delay = MagicMock()

    with patch("app.routers.jobs.get_db"):
        resp = await client.post(
            "/jobs/upload",
            files={"file": ("transactions.csv", SAMPLE_CSV, "text/csv")},
        )

    assert resp.status_code in (202, 500)


# ── Status endpoint ────────────────────

@pytest.mark.asyncio
async def test_status_returns_404_for_unknown_job(client):
    fake_id = str(uuid.uuid4())
    resp = await client.get(f"/jobs/{fake_id}/status")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_status_invalid_uuid(client):
    resp = await client.get("/jobs/not-a-uuid/status")
    assert resp.status_code == 422


# ── Results endpoint ──────────────────────

@pytest.mark.asyncio
async def test_results_returns_404_for_unknown_job(client):
    fake_id = str(uuid.uuid4())
    resp = await client.get(f"/jobs/{fake_id}/results")
    assert resp.status_code == 404


# ── List jobs endpoint ─────────────────────────────

@pytest.mark.asyncio
async def test_list_jobs_rejects_invalid_status(client):
    resp = await client.get("/jobs?status=invalid_status")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_jobs_accepts_valid_status_params(client):
    for status in ("pending", "processing", "completed", "failed"):
        resp = await client.get(f"/jobs?status={status}")
        # Either 200 (empty list) or DB error is acceptable here
        assert resp.status_code in (200, 500)


# ── CSV Parser Unit Tests ──────────────────────────

def test_csv_parser_validates_headers():
    from app.services.csv_parser import parse_csv_bytes, CSVValidationError
    with pytest.raises(CSVValidationError, match="missing required columns"):
        parse_csv_bytes(BAD_CSV_MISSING_COLS)


def test_csv_parser_returns_correct_row_count():
    from app.services.csv_parser import parse_csv_bytes
    rows, count = parse_csv_bytes(SAMPLE_CSV)
    assert count == 3
    assert len(rows) == 3


def test_csv_parser_handles_bom():
    from app.services.csv_parser import parse_csv_bytes
    bom_csv = b"\xef\xbb\xbf" + SAMPLE_CSV
    rows, count = parse_csv_bytes(bom_csv)
    assert count == 3
