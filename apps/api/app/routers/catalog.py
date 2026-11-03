import uuid
from pathlib import PurePath
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.deps import Principal, TenantDb, require_role
from app.core.config import get_settings
from app.core.storage import Storage, get_storage
from app.models import CatalogSource, IngestJob

router = APIRouter(prefix="/catalog", tags=["catalog"])

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
