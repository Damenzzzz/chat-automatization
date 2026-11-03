import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.deps import Principal, TenantDb, require_role
from app.routers.catalog import get_job

router = APIRouter(prefix="/ingest-jobs", tags=["catalog"])

Editor = Annotated[Principal, Depends(require_role("owner", "manager"))]


class RowError(BaseModel):
    row: int | None
    reason: str


class JobOut(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    status: str
    file_name: str | None
    rows_total: int | None
    rows_done: int
    progress: float | None
    stats: dict[str, Any]
    errors: list[RowError]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@router.get("/{job_id}")
async def job_status(job_id: uuid.UUID, principal: Editor, db: TenantDb) -> JobOut:
    job = await get_job(db, job_id)
    if job.status == "done":
        progress: float | None = 1.0
    elif job.rows_total:
        progress = round(min(job.rows_done / job.rows_total, 1.0), 3)
    else:
        progress = None
    return JobOut(
        id=job.id,
        source_id=job.source_id,
        status=job.status,
        file_name=job.file_name,
        rows_total=job.rows_total,
        rows_done=job.rows_done,
        progress=progress,
        stats=job.stats,
        errors=[RowError(**e) for e in job.errors],
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )
