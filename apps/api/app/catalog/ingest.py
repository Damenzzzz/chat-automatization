import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.mapping import ATTRIBUTE_PREFIX
from app.catalog.normalize import (
    NormalizeError,
    clean_sku,
    clean_text,
    content_hash,
    name_hash,
    parse_images,
    parse_price,
    parse_stock,
    sku_norm,
)
from app.catalog.reader import Row, is_empty, open_table
from app.core.config import get_settings
from app.core.storage import Storage
from app.db.session import tenant_session
from app.models import CatalogSource, IngestJob, Product

log = structlog.get_logger()

BATCH_SIZE = 500
MAX_STORED_ERRORS = 1000


@dataclass
class ParsedRow:
    row: int
    name: str
    sku: str | None
    sku_norm: str | None
    price: int | None
    stock: int | None
    category: str | None
    description: str | None
    images: list[str]
    attributes: dict[str, str]

    @property
    def name_hash(self) -> str:
        return name_hash(self.name)

    @property
    def key(self) -> tuple[str, str]:
        return ("sku", self.sku_norm) if self.sku_norm else ("name", self.name_hash)

    @property
    def content_hash(self) -> str:
        return content_hash(self.name, self.description, self.category, self.attributes)


@dataclass
class Stats:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped_empty: int = 0
    errors: int = 0


@dataclass
class Progress:
    stats: Stats = field(default_factory=Stats)
    errors: list[dict[str, Any]] = field(default_factory=list)
    rows_done: int = 0

    def error(self, row: int | None, reason: str) -> None:
        self.stats.errors += 1
        if len(self.errors) < MAX_STORED_ERRORS:
            self.errors.append({"row": row, "reason": reason})


def build_index(headers: list[str], mapping: dict[str, Any]) -> dict[int, str]:
    return {i: mapping[h] for i, h in enumerate(headers) if mapping.get(h)}


def parse_row(number: int, row: Row, index: dict[int, str]) -> ParsedRow:
    raw: dict[str, Any] = {}
    attributes: dict[str, str] = {}
    for i, target in index.items():
        if target.startswith(ATTRIBUTE_PREFIX):
            value = clean_text(row[i])
            if value is not None:
                attributes[target.removeprefix(ATTRIBUTE_PREFIX)] = value
        else:
            raw[target] = row[i]

    name = clean_text(raw.get("name"))
    if name is None:
        raise NormalizeError("нет названия")
    sku = clean_sku(raw.get("sku"))
    return ParsedRow(
        row=number,
        name=name[:500],
        sku=sku,
        sku_norm=sku_norm(sku),
        price=parse_price(raw.get("price")),
        stock=parse_stock(raw.get("stock")),
        category=clean_text(raw.get("category")),
        description=clean_text(raw.get("description")),
        images=parse_images(raw.get("image_url")),
        attributes=attributes,
    )


async def _existing(
    session: AsyncSession, batch: list[ParsedRow]
) -> dict[tuple[str, str], Product]:
    found: dict[tuple[str, str], Product] = {}
    skus = [r.sku_norm for r in batch if r.sku_norm]
    names = [r.name_hash for r in batch if not r.sku_norm]
    if skus:
        for p in await session.scalars(select(Product).where(Product.sku_norm.in_(skus))):
            found[("sku", p.sku_norm or "")] = p
    if names:
        query = select(Product).where(Product.sku_norm.is_(None), Product.name_hash.in_(names))
        for p in await session.scalars(query):
            found[("name", p.name_hash or "")] = p
    return found


def _apply(product: Product, row: ParsedRow, source_id: uuid.UUID) -> bool:
    static_changed = product.content_hash != row.content_hash
    dynamic_changed = (
        product.price,
        product.stock,
        product.images,
        product.sku,
        product.is_active,
    ) != (
        row.price,
        row.stock,
        row.images,
        row.sku,
        True,
    )
    product.source_id = source_id
    if static_changed:
        product.name = row.name
        product.name_hash = row.name_hash
        product.description = row.description
        product.category = row.category
        product.attributes = row.attributes
        product.content_hash = row.content_hash
        product.embedding_stale = True
    if dynamic_changed:
        product.price = row.price
        product.stock = row.stock
        product.images = row.images
        product.sku = row.sku
        product.is_active = True
    return static_changed or dynamic_changed


async def _flush(
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
    source_id: uuid.UUID,
    batch: list[ParsedRow],
    progress: Progress,
) -> None:
    async with tenant_session(tenant_id) as session:
        existing = await _existing(session, batch) if batch else {}
        for row in batch:
            product = existing.get(row.key)
            if product is None:
                session.add(
                    Product(
                        tenant_id=tenant_id,
                        source_id=source_id,
                        sku=row.sku,
                        name=row.name,
                        name_hash=row.name_hash,
                        description=row.description,
                        category=row.category,
                        attributes=row.attributes,
                        price=row.price,
                        stock=row.stock,
                        images=row.images,
                        content_hash=row.content_hash,
                    )
                )
                progress.stats.created += 1
            elif _apply(product, row, source_id):
                progress.stats.updated += 1
            else:
                progress.stats.unchanged += 1
        await session.execute(
            update(IngestJob)
            .where(IngestJob.id == job_id)
            .values(
                rows_done=progress.rows_done,
                stats=asdict(progress.stats),
                errors=progress.errors,
            )
        )


async def _finish(tenant_id: uuid.UUID, job_id: uuid.UUID, status: str, progress: Progress) -> None:
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        job = await session.get_one(IngestJob, job_id)
        job.status = status
        job.finished_at = now
        job.rows_done = progress.rows_done
        job.stats = asdict(progress.stats)
        job.errors = progress.errors
        if status == "done":
            await session.execute(
                update(CatalogSource)
                .where(CatalogSource.id == job.source_id)
                .values(last_sync_at=now)
            )


async def run_ingest(tenant_id: uuid.UUID, job_id: uuid.UUID, storage: Storage) -> Stats:
    max_rows = get_settings().catalog_max_rows
    async with tenant_session(tenant_id) as session:
        job = await session.get_one(IngestJob, job_id)
        source = await session.get_one(CatalogSource, job.source_id)
        mapping = dict(source.column_map)
        source_id, file_key, file_type = source.id, job.file_key, job.file_type
        job.status, job.started_at, job.finished_at = "running", datetime.now(UTC), None
        job.rows_done, job.stats, job.errors = 0, {}, []

    progress = Progress()
    log.info("catalog.ingest.start", tenant_id=str(tenant_id), job_id=str(job_id))
    try:
        if not file_key or not file_type:
            raise NormalizeError("у задачи нет файла")
        table = open_table(await storage.get(file_key), file_type)
        index = build_index(table.headers, mapping)
        async with tenant_session(tenant_id) as session:
            await session.execute(
                update(IngestJob).where(IngestJob.id == job_id).values(rows_total=table.total_rows)
            )

        seen: dict[tuple[str, str], int] = {}
        batch: list[ParsedRow] = []
        for number, row in table.rows:
            if is_empty(row):
                progress.stats.skipped_empty += 1
                continue
            if progress.rows_done >= max_rows:
                progress.error(number, f"превышен лимит {max_rows} строк, остальные пропущены")
                break
            progress.rows_done += 1
            try:
                parsed = parse_row(number, row, index)
            except NormalizeError as exc:
                progress.error(number, str(exc))
                continue
            if parsed.key in seen:
                what = (
                    f"артикула «{parsed.sku}»" if parsed.sku_norm else f"названия «{parsed.name}»"
                )
                progress.error(number, f"дубль {what}, уже был в строке {seen[parsed.key]}")
                continue
            seen[parsed.key] = number
            batch.append(parsed)
            if len(batch) >= BATCH_SIZE:
                await _flush(tenant_id, job_id, source_id, batch, progress)
                batch = []
        await _flush(tenant_id, job_id, source_id, batch, progress)
    except Exception as exc:
        log.exception("catalog.ingest.failed", job_id=str(job_id))
        progress.error(None, f"импорт прерван: {exc}")
        await _finish(tenant_id, job_id, "failed", progress)
        return progress.stats

    await _finish(tenant_id, job_id, "done", progress)
    log.info("catalog.ingest.done", job_id=str(job_id), **asdict(progress.stats))
    return progress.stats
