import uuid
from decimal import Decimal

from sqlalchemy import String, Integer, Text, Numeric, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class JobSummary(Base):
    __tablename__ = "job_summaries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    total_spend_inr: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    total_spend_usd: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    top_merchants: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    anomaly_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(10), nullable=True)  
    category_breakdown: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    job: Mapped["Job"] = relationship("Job", back_populates="summary")

    def __repr__(self) -> str:
        return f"<JobSummary job_id={self.job_id} risk={self.risk_level}>"
