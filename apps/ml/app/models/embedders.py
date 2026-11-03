from typing import Any

from app.models.base import EMBEDDING_DIM, Kind


class SentenceTransformerEmbedder:
    def __init__(
        self,
        name: str,
        *,
        device: str,
        query_prompt: str | None,
        max_tokens: int,
        batch_size: int,
        padding_side: str | None = None,
    ) -> None:
        from sentence_transformers import SentenceTransformer

        processor_kwargs = {"padding_side": padding_side} if padding_side else None
        self.model: Any = SentenceTransformer(
            name, device=device, processor_kwargs=processor_kwargs
        )
        self.model.max_seq_length = max_tokens
        self.name = name
        self.query_prompt = query_prompt
        self.batch_size = batch_size
        dim = self.model.get_sentence_embedding_dimension()
        if dim != EMBEDDING_DIM:
            raise ValueError(f"{name}: размерность {dim}, ожидается {EMBEDDING_DIM}")
        self.dim: int = EMBEDDING_DIM

    def encode(self, texts: list[str], kind: Kind) -> list[list[float]]:
        prompt = self.query_prompt if kind == "query" else None
        vectors = self.model.encode(
            texts,
            prompt=prompt,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [[float(x) for x in v] for v in vectors]


def qwen3_query_prompt(task: str) -> str:
    return f"Instruct: {task}\nQuery:"
