import hashlib
import math
import random

from app.models.asr import AudioError, Transcript
from app.models.base import EMBEDDING_DIM, Kind


class FakeEmbedder:
    name = "fake-embedder"
    dim = EMBEDDING_DIM

    def encode(self, texts: list[str], kind: Kind) -> list[list[float]]:
        vectors = []
        for text in texts:
            seed = int.from_bytes(hashlib.sha256(f"{kind}:{text}".encode()).digest()[:8], "big")
            rng = random.Random(seed)  # noqa: S311
            vec = [rng.gauss(0, 1) for _ in range(self.dim)]
            norm = math.sqrt(sum(v * v for v in vec))
            vectors.append([v / norm for v in vec])
        return vectors


class FakeReranker:
    name = "fake-reranker"

    def score(self, query: str, documents: list[str]) -> list[float]:
        words = set(query.lower().split())
        return [len(words & set(doc.lower().split())) / (len(words) or 1) for doc in documents]


class FakeTranscriber:
    name = "fake-asr"

    def transcribe(self, audio: bytes) -> Transcript:
        if audio.startswith(b"bad"):
            raise AudioError("не удалось прочитать аудио")
        language = "kk" if audio.startswith(b"kk") else "ru"
        return Transcript(
            text=f"расшифровка {len(audio)} байт",
            language=language,
            language_probability=1.0,
            duration=1.0,
            model=self.name,
        )
