import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.understand import Understanding
from app.channels.gateway import Gateway
from app.channels.outbound import Outbound
from app.channels.processor import Processor
from app.channels.store import load_channel
from app.channels.types import Media
from app.llm.fake import FakeLLM
from app.mlclient import MLClient, MLError
from tests.agent_helpers import make_agent, make_conversation, nodes
from tests.channel_helpers import RecordingAdapter, incoming, make_channel
from tests.conftest import RecordingQueue
from tests.fake_ml import FakeML

VOICE = {"kind": "audio", "file_id": "voice-1", "mime_type": "audio/ogg", "size": None}
UNDERSTOOD = Understanding(lang="kk", intent="smalltalk", complexity="low")


@pytest.fixture
async def conversation(owner_engine: AsyncEngine, redis: Any) -> tuple[uuid.UUID, uuid.UUID, Any]:
    tenant_id, conversation_id = await make_conversation(owner_engine)
    channel_id = await make_channel(owner_engine, tenant_id)
    return tenant_id, conversation_id, channel_id


async def _customer_row(engine: AsyncEngine, conversation_id: uuid.UUID) -> Any:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text(
                    "SELECT content, media FROM messages"
                    " WHERE conversation_id = :c AND role = 'customer' ORDER BY created_at DESC"
                ),
                {"c": conversation_id},
            )
        ).first()


async def test_voice_is_downloaded_transcribed_stored_and_answered(
    conversation: tuple[uuid.UUID, uuid.UUID, uuid.UUID], owner_engine: AsyncEngine
) -> None:
    tenant_id, conversation_id, channel_id = conversation
    adapter = RecordingAdapter(audio=b"OGG")
    ml = FakeML(transcript="ақ пион бар ма")
    llm = FakeLLM([UNDERSTOOD, "Иә, бар."])
    agent, _ = await make_agent(llm=llm, ml=ml, channels=Outbound({"telegram": adapter}))

    turn = await agent.run(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        text="",
        channel_id=channel_id,
        customer_external_id="c1",
        media=[VOICE],
    )

    assert adapter.downloaded == ["voice-1"]
    assert ml.transcribed == [(b"OGG", "audio/ogg")]
    assert nodes(turn.trace)[:3] == ["ingest", "transcribe", "guard_in"]
    assert turn.trace[1]["recognized"] == 1
    assert turn.trace[1]["languages"] == ["kk"]
    assert turn.reply == "Иә, бар."
    assert "ақ пион бар ма" in llm.calls[0].messages[-1].text

    row = await _customer_row(owner_engine, conversation_id)
    assert row.content == "ақ пион бар ма"
    [stored] = row.media["items"]
    assert stored["transcript"] == "ақ пион бар ма"
    assert stored["language"] == "kk"
    assert stored["file_id"] == "voice-1"


async def test_voice_with_caption_keeps_both(
    conversation: tuple[uuid.UUID, uuid.UUID, uuid.UUID], owner_engine: AsyncEngine
) -> None:
    tenant_id, conversation_id, channel_id = conversation
    agent, _ = await make_agent(ml=FakeML(), channels=Outbound({"telegram": RecordingAdapter()}))
    await agent.run(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        text="вот подпись",
        channel_id=channel_id,
        customer_external_id="c1",
        media=[VOICE],
    )
    row = await _customer_row(owner_engine, conversation_id)
    assert row.content == "вот подпись\nголосовой текст"


@pytest.mark.parametrize(
    "broken",
    [
        {"ml": FakeML(fail=True), "adapter": RecordingAdapter()},
        {"ml": FakeML(), "adapter": RecordingAdapter(fail=True)},
        {"ml": FakeML(transcript="   "), "adapter": RecordingAdapter()},
    ],
    ids=["ml_down", "download_failed", "silence"],
)
async def test_failed_recognition_asks_to_write_text(
    conversation: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
    owner_engine: AsyncEngine,
    broken: dict[str, Any],
) -> None:
    tenant_id, conversation_id, channel_id = conversation
    llm = FakeLLM([UNDERSTOOD, "Жазып жіберіңізші."])
    agent, _ = await make_agent(
        llm=llm, ml=broken["ml"], channels=Outbound({"telegram": broken["adapter"]})
    )
    turn = await agent.run(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        text="",
        channel_id=channel_id,
        customer_external_id="c1",
        media=[VOICE],
    )
    assert turn.trace[1]["failed"] is True
    assert turn.reply == "Жазып жіберіңізші."
    prompt = llm.calls[1].messages[-1].text
    assert "[голосовое сообщение]" in prompt
    assert "не удалось разобрать" in prompt
    row = await _customer_row(owner_engine, conversation_id)
    assert row.content is None


async def test_failure_flag_does_not_leak_into_next_turn(
    conversation: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    tenant_id, conversation_id, channel_id = conversation
    llm = FakeLLM([UNDERSTOOD, "Напишите текстом.", UNDERSTOOD, "Здравствуйте!"])
    agent, _ = await make_agent(
        llm=llm, ml=FakeML(fail=True), channels=Outbound({"telegram": RecordingAdapter()})
    )
    common: dict[str, Any] = {
        "tenant_id": tenant_id,
        "conversation_id": conversation_id,
        "channel_id": channel_id,
        "customer_external_id": "c1",
    }
    await agent.run(text="", media=[VOICE], **common)
    turn = await agent.run(text="привет", **common)
    assert "transcribe" not in nodes(turn.trace)
    assert "не удалось разобрать" not in llm.calls[3].messages[-1].text


async def test_human_mode_voice_is_transcribed_for_manager_without_reply(
    owner_engine: AsyncEngine, redis: Any
) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine, mode="human")
    channel_id = await make_channel(owner_engine, tenant_id)
    adapter = RecordingAdapter()
    llm = FakeLLM([])
    agent, _ = await make_agent(llm=llm, ml=FakeML(), channels=Outbound({"telegram": adapter}))
    turn = await agent.run(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        text="",
        channel_id=channel_id,
        customer_external_id="c1",
        media=[VOICE],
    )
    assert turn.reply is None
    assert adapter.sent == []
    assert llm.calls == []
    row = await _customer_row(owner_engine, conversation_id)
    assert row.content == "голосовой текст"


async def test_voice_merged_with_text_through_queue(owner_engine: AsyncEngine, redis: Any) -> None:
    tenant_id, _ = await make_conversation(owner_engine)
    channel_id = await make_channel(owner_engine, tenant_id)
    channel = await load_channel(channel_id)
    assert channel is not None
    queue = RecordingQueue()
    gateway = Gateway(redis, queue)
    await gateway.accept(channel, incoming(channel_id, "m1", "смотрите"))
    await gateway.accept(channel, incoming(channel_id, "m2", "", media=[Media(file_id="voice-2")]))
    adapter = RecordingAdapter()
    outbound = Outbound({"telegram": adapter})
    llm = FakeLLM([UNDERSTOOD, "Понял."])
    agent, agent_queue = await make_agent(llm=llm, ml=FakeML(), channels=outbound)
    processor = Processor(redis, agent_queue, agent, outbound)
    _, args = queue.jobs[-1]
    tenant, channel_arg, key, seq = args
    assert isinstance(seq, int)

    assert await processor.flush(str(tenant), str(channel_arg), str(key), seq) == "done"

    assert adapter.downloaded == ["voice-2"]
    assert "смотрите\nголосовой текст" in llm.calls[0].messages[-1].text


def _client(handler: Any) -> MLClient:
    async def no_sleep(_: float) -> None:
        return None

    return MLClient(
        "http://ml", transport=httpx.MockTransport(handler), sleep=no_sleep, max_retries=2
    )


async def test_ml_client_sends_multipart_and_strips_codec() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["type"] = request.headers["content-type"]
        seen["body"] = request.content
        return httpx.Response(
            200,
            json={
                "text": "сәлем",
                "language": "kk",
                "language_probability": 0.97,
                "duration": 1.5,
                "model": "kk-model",
            },
        )

    result = await _client(handler).transcribe(b"OGGDATA", "audio/ogg; codecs=opus")

    assert result.text == "сәлем"
    assert result.language == "kk"
    assert seen["type"].startswith("multipart/form-data")
    assert b"OGGDATA" in seen["body"]
    assert b"Content-Type: audio/ogg\r\n" in seen["body"]


async def test_ml_client_retries_while_models_load() -> None:
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(503, json={"detail": "asr_loading"})
        return httpx.Response(200, json={"text": "ок"})

    assert (await _client(handler).transcribe(b"x")).text == "ок"
    assert len(attempts) == 3


async def test_ml_client_does_not_retry_bad_audio() -> None:
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(400, json={"detail": "audio_invalid"})

    with pytest.raises(MLError):
        await _client(handler).transcribe(b"x")
    assert len(attempts) == 1
