import io
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Protocol

import structlog

log = structlog.get_logger()

SAMPLE_RATE = 16_000
KAZAKH = "kk"
CT2_WEIGHTS = "model.bin"
TOKENIZER_FILES = ("tokenizer.json", "preprocessor_config.json")


class AudioError(ValueError):
    pass


class AudioTooLongError(AudioError):
    pass


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str
    language_probability: float
    duration: float
    model: str


class Transcriber(Protocol):
    name: str

    def transcribe(self, audio: bytes) -> Transcript: ...


def ensure_ct2(model_id: str, root: Path, quantization: str) -> str:
    if Path(model_id).is_dir():
        return model_id
    target = root / f"{model_id.replace('/', '--')}-{quantization}"
    if (target / CT2_WEIGHTS).exists():
        return str(target)

    from huggingface_hub import HfApi

    files = HfApi().list_repo_files(model_id)
    if CT2_WEIGHTS in files:
        return model_id

    from ctranslate2.converters import TransformersConverter

    log.info("ml.asr_converting", model=model_id, quantization=quantization)
    temporary = root / f"{target.name}.tmp"
    shutil.rmtree(temporary, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    converter = TransformersConverter(
        model_id, copy_files=[name for name in TOKENIZER_FILES if name in files]
    )
    converter.convert(str(temporary), quantization=quantization, force=True)
    temporary.rename(target)
    return str(target)


def decode(audio: bytes) -> Any:
    from faster_whisper import decode_audio

    try:
        return decode_audio(io.BytesIO(audio), sampling_rate=SAMPLE_RATE)
    except Exception as exc:
        raise AudioError("не удалось прочитать аудио") from exc


class WhisperTranscriber:
    def __init__(
        self,
        base_model: str,
        kk_model: str,
        *,
        device: str,
        compute_type: str,
        ct2_dir: Path,
        max_seconds: float,
        factory: Callable[[str], Any] | None = None,
        prepare: Callable[[str, Path, str], str] = ensure_ct2,
    ) -> None:
        if factory is None:
            from faster_whisper import WhisperModel

            def factory(path: str) -> Any:
                return WhisperModel(path, device=device, compute_type=compute_type)

        self.name = base_model
        self.kk_name = kk_model
        self.max_seconds = max_seconds
        self._factory = factory
        self._base = factory(base_model)
        self._kk: Any = None
        self._kk_lock = Lock()
        self._kk_path: str | None = None
        try:
            self._kk_path = prepare(kk_model, ct2_dir, compute_type)
        except Exception:
            log.exception("ml.asr_kk_unavailable", model=kk_model)

    def _model_for(self, language: str) -> tuple[Any, str]:
        if language != KAZAKH or self._kk_path is None:
            return self._base, self.name
        with self._kk_lock:
            if self._kk is None:
                self._kk = self._factory(self._kk_path)
        return self._kk, self.kk_name

    def transcribe(self, audio: bytes) -> Transcript:
        waveform = decode(audio)
        duration = len(waveform) / SAMPLE_RATE
        if duration > self.max_seconds:
            raise AudioTooLongError(f"аудио длиннее {self.max_seconds:.0f} с")
        language, probability, _ = self._base.detect_language(audio=waveform)
        model, name = self._model_for(language)
        segments, _ = model.transcribe(
            waveform,
            language=language,
            vad_filter=True,
            beam_size=5,
            condition_on_previous_text=False,
        )
        text = " ".join(part for part in (s.text.strip() for s in segments) if part)
        return Transcript(
            text=text,
            language=language,
            language_probability=round(float(probability), 4),
            duration=round(duration, 2),
            model=name,
        )
