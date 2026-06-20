"""
main.py: FastAPI application entry point.
Includes startup (DB init), router registration, and health endpoint.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.routers.jobs import router as jobs_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run DB table creation on startup (alembic handles prod migrations)."""
    await init_db()
    yield


app = FastAPI(
    title="AI-Powered Transaction Processing Pipeline",
    description=(
        "Upload dirty CSV transaction files, process them asynchronously "
        "with LLM-powered classification and anomaly detection, and retrieve "
        "structured results via a polling API."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — allow all origins in dev (restrict in prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(jobs_router)


@app.get("/health", tags=["Health"])
async def health_check():
    """Simple health check for load balancers / Docker."""
    return {"status": "ok"}
