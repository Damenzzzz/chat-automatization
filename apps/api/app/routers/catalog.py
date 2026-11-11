import asyncio
import uuid
from pathlib import PurePath
from typing import Annotated

import httpx
import structlog
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.deps import Principal, TenantDb, require_role
from app.catalog.gsheet import SheetError, download_csv, parse_sheet_url
from app.catalog.mapping import MappingProposal, heuristic_mapping, validate_mapping
from app.catalog.mapping_llm import refine_with_llm
from app.catalog.reader import FileFormatError, preview
from app.core.config import get_settings
from app.core.http import get_http_client
from app.core.queue import Queue, get_queue
from app.core.storage import Storage, get_storage
from app.llm import LLM, LLMError, get_llm
from app.models import CatalogSource, IngestJob

router = APIRouter(prefix="/catalog", tags=["catalog"])
log = structlog.get_logger()

Editor = Annotated[Principal, Depends(require_role("owner", "manager"))]

FILE_TYPES = {
    ".xlsx": ("xlsx", "excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".csv": ("csv", "csv", "text/csv"),
}
CHUNK = 1024 * 1024


class UploadOut(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    status: str
    file_name: str | None


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    data = bytearray()
    while chunk := await file.read(CHUNK):
        data.extend(chunk)
        if len(data) > limit:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "file_too_large")
    return bytes(data)


async def create_job(
    db: TenantDb,
    storage: Storage,
    principal: Principal,
    *,
    data: bytes,
    file_name: str,
    file_type: str,
    content_type: str,
    source: CatalogSource,
) -> IngestJob:
    job_id = uuid.uuid4()
    key = f"tenants/{principal.tenant_id}/catalog/{job_id}.{file_type}"
    await storage.put(key, data, content_type)
    job = IngestJob(
        id=job_id,
        tenant_id=principal.tenant_id,
        source_id=source.id,
        status="pending",
        file_key=key,
        file_name=file_name,
        file_type=file_type,
    )
    db.add(job)
    await db.flush()
    return job


async def get_source(db: TenantDb, source_id: uuid.UUID) -> CatalogSource:
    source = await db.scalar(select(CatalogSource).where(CatalogSource.id == source_id))
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "source_not_found")
    return source


async def get_job(db: TenantDb, job_id: uuid.UUID) -> IngestJob:
    job = await db.scalar(select(IngestJob).where(IngestJob.id == job_id))
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job_not_found")
    return job


async def load_preview(job: IngestJob, storage: Storage) -> tuple[list[str], list[list[object]]]:
    if not job.file_key or not job.file_type:
        raise HTTPException(status.HTTP_409_CONFLICT, "job_has_no_file")
    try:
        data = await storage.get(job.file_key)
        return await asyncio.to_thread(preview, data, job.file_type)
    except FileFormatError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.post("/uploads", status_code=status.HTTP_201_CREATED)
async def upload(
    principal: Editor,
    db: TenantDb,
    storage: Annotated[Storage, Depends(get_storage)],
    file: Annotated[UploadFile, File()],
    source_id: Annotated[uuid.UUID | None, Form()] = None,
) -> UploadOut:
    file_name = PurePath(file.filename or "catalog").name[:255]
    spec = FILE_TYPES.get(PurePath(file_name).suffix.lower())
    if spec is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "only_xlsx_or_csv")
    file_type, source_type, content_type = spec
    data = await _read_limited(file, get_settings().catalog_max_upload_bytes)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty_file")

    if source_id is not None:
        source = await get_source(db, source_id)
    else:
        source = CatalogSource(tenant_id=principal.tenant_id, type=source_type, name=file_name)
        db.add(source)
        await db.flush()

    job = await create_job(
        db,
        storage,
        principal,
        data=data,
        file_name=file_name,
        file_type=file_type,
        content_type=content_type,
        source=source,
    )
    return UploadOut(id=job.id, source_id=source.id, status=job.status, file_name=job.file_name)


class SheetIn(BaseModel):
    url: str = Field(max_length=2000)
    source_id: uuid.UUID | None = None


@router.post("/uploads/gsheet", status_code=status.HTTP_201_CREATED)
async def upload_gsheet(
    body: SheetIn,
    principal: Editor,
    db: TenantDb,
    storage: Annotated[Storage, Depends(get_storage)],
    http: Annotated[httpx.AsyncClient, Depends(get_http_client)],
) -> UploadOut:
    try:
        ref = parse_sheet_url(body.url)
        data = await download_csv(http, ref, get_settings().catalog_max_upload_bytes)
    except SheetError as exc:
        code = str(exc)
        status_code = (
            status.HTTP_413_CONTENT_TOO_LARGE
            if code == "file_too_large"
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code, code) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "sheet_download_failed") from exc

    config = {"url": body.url, "sheet_id": ref.sheet_id, "gid": ref.gid}
    if body.source_id is not None:
        source = await get_source(db, body.source_id)
        source.config = config
    else:
        source = CatalogSource(
            tenant_id=principal.tenant_id, type="gsheet", name="Google Таблица", config=config
        )
        db.add(source)
        await db.flush()

    job = await create_job(
        db,
        storage,
        principal,
        data=data,
        file_name=f"gsheet-{ref.sheet_id[:8]}-{ref.gid}.csv",
        file_type="csv",
        content_type="text/csv",
        source=source,
    )
    return UploadOut(id=job.id, source_id=source.id, status=job.status, file_name=job.file_name)


@router.get("/uploads/{job_id}/mapping")
async def get_mapping(
    job_id: uuid.UUID,
    principal: Editor,
    db: TenantDb,
    storage: Annotated[Storage, Depends(get_storage)],
    llm: Annotated[LLM | None, Depends(get_llm)],
) -> MappingProposal:
    job = await get_job(db, job_id)
    source = await get_source(db, job.source_id)
    headers, rows = await load_preview(job, storage)
    proposal = heuristic_mapping(headers, rows, source.column_map)
    if llm is None or proposal.method == "saved":
        return proposal
    try:
        return await refine_with_llm(llm, get_settings().llm_model_router, headers, rows, proposal)
    except LLMError as exc:
        log.warning("catalog.mapping.llm_failed", job_id=str(job_id), error=str(exc))
        return proposal


class ConfirmIn(BaseModel):
    mapping: dict[str, str | None]


class ConfirmOut(BaseModel):
    id: uuid.UUID
    status: str


@router.post("/uploads/{job_id}/confirm", status_code=status.HTTP_202_ACCEPTED)
async def confirm(
    job_id: uuid.UUID,
    body: ConfirmIn,
    principal: Editor,
    db: TenantDb,
    storage: Annotated[Storage, Depends(get_storage)],
    queue: Annotated[Queue, Depends(get_queue)],
    background: BackgroundTasks,
) -> ConfirmOut:
    job = await get_job(db, job_id)
    if job.status in ("queued", "running"):
        raise HTTPException(status.HTTP_409_CONFLICT, "job_in_progress")
    headers, _ = await load_preview(job, storage)
    problems = validate_mapping(headers, body.mapping)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problems)

    source = await get_source(db, job.source_id)
    source.column_map = body.mapping
    job.status = "queued"
    background.add_task(queue.enqueue, "ingest_catalog", str(principal.tenant_id), str(job.id))
    return ConfirmOut(id=job.id, status=job.status)
