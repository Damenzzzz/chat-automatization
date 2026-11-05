import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import update

from app.auth.deps import Principal, TenantDb, require_role
from app.core.queue import Queue, get_queue
from app.models import KbChunk, Unanswered

router = APIRouter(prefix="/unanswered", tags=["analytics"])

Member = Annotated[Principal, Depends(require_role("owner", "manager"))]
KB_SOURCE = "unanswered"
TITLE_LIMIT = 200


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)
    also_resolve: list[uuid.UUID] = Field(default_factory=list, max_length=300)


class AnswerOut(BaseModel):
    kb_chunk_id: uuid.UUID
    resolved: int


@router.post("/{unanswered_id}/answer", status_code=status.HTTP_201_CREATED)
async def answer_question(
    unanswered_id: uuid.UUID,
    body: AnswerIn,
    principal: Member,
    db: TenantDb,
    queue: Annotated[Queue, Depends(get_queue)],
    background: BackgroundTasks,
) -> AnswerOut:
    text = body.answer.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "answer_empty")
    question = await db.get(Unanswered, unanswered_id, with_for_update=True)
    if question is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "question_not_found")
    if question.resolved_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "already_resolved")

    chunk = KbChunk(
        tenant_id=principal.tenant_id,
        source=KB_SOURCE,
        title=question.question[:TITLE_LIMIT],
        text=text,
    )
    db.add(chunk)
    await db.flush()

    now = datetime.now(UTC)
    ids = {unanswered_id, *body.also_resolve}
    rows = await db.scalars(
        update(Unanswered)
        .where(Unanswered.id.in_(ids), Unanswered.resolved_at.is_(None))
        .values(answer=text, resolved_at=now)
        .returning(Unanswered.id)
    )
    resolved = len(list(rows))
    background.add_task(
        queue.enqueue,
        "reindex_embeddings",
        str(principal.tenant_id),
        job_id=f"reindex:{principal.tenant_id}",
    )
    return AnswerOut(kb_chunk_id=chunk.id, resolved=resolved)
