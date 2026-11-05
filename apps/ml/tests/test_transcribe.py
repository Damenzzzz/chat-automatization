import io
import math
import struct
import wave
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.hub import ModelHub
from app.main import create_app
from app.models import asr
from app.models.asr import AudioError, AudioTooLongError, WhisperTranscriber, ensure_ct2
from tests.conftest import wait_ready


def wav(seconds: float = 1.0) -> bytes:
    frames = int(16000 * seconds)
    samples = (int(8000 * math.sin(2 * math.pi * 440 * i / 16000)) for i in range(frames))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"".join(struct.pack("<h", s) for s in samples))
    return buffer.getvalue()


class Segment:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeWhisper:
    def __init__(self, path: str, language: str = "ru") -> None:
        self.path = path
        self.language = language
        self.calls: list[str] = []

    def detect_language(self, audio: Any) -> tuple[str, float, list[tuple[str, float]]]:
        return self.language, 0.91234567, []

    def transcribe(self, audio: Any, language: str, **kwargs: Any) -> tuple[list[Segment], Any]:
        self.calls.append(language)
        assert kwargs["vad_filter"] is True
        return [Segment(f" текст {self.path} "), Segment(" "), Segment("конец")], None


def transcriber(
    language: str, *, kk_path: str | None = "/ct2/kk", max_seconds: float = 60.0
) -> tuple[WhisperTranscriber, dict[str, FakeWhisper]]:
    built: dict[str, FakeWhisper] = {}

    def factory(path: str) -> FakeWhisper:
        built[path] = FakeWhisper(path, language)
        return built[path]

    def prepare(model: str, root: Path, quantization: str) -> str:
        if kk_path is None:
            raise OSError("нет сети")
        return kk_path

    return (
        WhisperTranscriber(
            "base",
            "org/kk",
            device="cpu",
            compute_type="int8",
            ct2_dir=Path("/ct2"),
            max_seconds=max_seconds,
            factory=factory,
            prepare=prepare,
        ),
        built,
    )


def test_russian_stays_on_base_model_and_kk_is_not_loaded() -> None:
    model, built = transcriber("ru")
    result = model.transcribe(wav())
    assert result.text == "текст base конец"
    assert result.language == "ru"
    assert result.language_probability == 0.9123
    assert result.duration == 1.0
    assert result.model == "base"
    assert built["base"].calls == ["ru"]
    assert "/ct2/kk" not in built


def test_kazakh_goes_to_tuned_model_once_detected() -> None:
    model, built = transcriber("kk")
    first = model.transcribe(wav())
    second = model.transcribe(wav())
    assert first.model == second.model == "org/kk"
    assert first.text == "текст /ct2/kk конец"
    assert built["base"].calls == []
    assert built["/ct2/kk"].calls == ["kk", "kk"]


def test_kazakh_falls_back_to_base_when_tuned_model_is_unavailable() -> None:
    model, built = transcriber("kk", kk_path=None)
    result = model.transcribe(wav())
    assert result.model == "base"
    assert built["base"].calls == ["kk"]


def test_invalid_audio_is_rejected() -> None:
    model, _ = transcriber("ru")
    with pytest.raises(AudioError):
        model.transcribe(b"this is not audio at all")


def test_too_long_audio_is_rejected_before_transcribing() -> None:
    model, built = transcriber("ru", max_seconds=0.5)
    with pytest.raises(AudioTooLongError):
        model.transcribe(wav(1.0))
    assert built["base"].calls == []


def test_ensure_ct2_reuses_converted_model(tmp_path: Path) -> None:
    target = tmp_path / "org--kk-int8"
    target.mkdir()
    (target / "model.bin").write_bytes(b"x")
    assert ensure_ct2("org/kk", tmp_path, "int8") == str(target)


def test_ensure_ct2_uses_ready_ct2_repo_directly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Api:
        def list_repo_files(self, model: str) -> list[str]:
            return ["config.json", "model.bin"]

    monkeypatch.setattr("huggingface_hub.HfApi", Api)
    assert ensure_ct2("org/ready", tmp_path, "int8") == "org/ready"


def test_ensure_ct2_converts_transformers_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    class Api:
        def list_repo_files(self, model: str) -> list[str]:
            return ["config.json", "model.safetensors", "tokenizer.json"]

    class Converter:
        def __init__(self, model: str, copy_files: list[str]) -> None:
            seen["model"], seen["copy_files"] = model, copy_files

        def convert(self, output: str, quantization: str, force: bool) -> None:
            seen["quantization"] = quantization
            Path(output).mkdir(parents=True)
            (Path(output) / "model.bin").write_bytes(b"x")

    monkeypatch.setattr("huggingface_hub.HfApi", Api)
    monkeypatch.setattr("ctranslate2.converters.TransformersConverter", Converter)

    path = ensure_ct2("org/kk", tmp_path, "int8")

    assert path == str(tmp_path / "org--kk-int8")
    assert (Path(path) / "model.bin").exists()
    assert not (tmp_path / "org--kk-int8.tmp").exists()
    assert seen == {"model": "org/kk", "copy_files": ["tokenizer.json"], "quantization": "int8"}
    assert asr.CT2_WEIGHTS == "model.bin"


def test_transcribe_endpoint(client: TestClient) -> None:
    response = client.post("/transcribe", files={"file": ("v.ogg", b"kk-audio", "audio/ogg")})
    assert response.status_code == 200
    assert response.json() == {
        "text": "расшифровка 8 байт",
        "language": "kk",
        "language_probability": 1.0,
        "duration": 1.0,
        "model": "fake-asr",
    }
    assert client.get("/health").json()["asr"]["loaded"] is True


@pytest.mark.parametrize(
    ("content", "status", "detail"),
    [
        (b"", 400, "audio_empty"),
        (b"bad-audio", 400, "audio_invalid"),
        (b"x" * 1025, 413, "audio_too_large"),
    ],
)
def test_transcribe_rejects(client: TestClient, content: bytes, status: int, detail: str) -> None:
    response = client.post("/transcribe", files={"file": ("v.ogg", content)})
    assert response.status_code == status
    assert response.json()["detail"] == detail


def test_transcribe_requires_file(client: TestClient) -> None:
    assert client.post("/transcribe").status_code == 422


async def test_not_ready_before_asr_loaded() -> None:
    from app.hub import NotReadyError

    hub = ModelHub(Settings(ml_embedder="fake", ml_reranker="fake", ml_asr="fake"))
    with pytest.raises(NotReadyError):
        await hub.transcribe(b"x")


def test_failed_asr_does_not_break_search_models(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("нет памяти")

    monkeypatch.setattr("app.hub.build_transcriber", boom)
    settings = Settings(ml_embedder="fake", ml_reranker="fake", ml_asr="fake")
    with TestClient(create_app(settings)) as client:
        body = wait_ready(client)
        assert body["status"] == "ok"
        assert "нет памяти" in body["asr"]["error"]
        response = client.post("/transcribe", files={"file": ("v.ogg", b"a")})
        assert response.status_code == 503
        assert response.json()["detail"] == "asr_failed"
        assert client.post("/embed", json={"texts": ["x"]}).status_code == 200
