import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field


@dataclass
class Fused:
    id: uuid.UUID
    score: float = 0.0
    ranks: dict[str, int] = field(default_factory=dict)


def rrf(lists: Mapping[str, Sequence[uuid.UUID]], k: int = 60) -> list[Fused]:
    fused: dict[uuid.UUID, Fused] = {}
    for name, ids in lists.items():
        for rank, item_id in enumerate(ids, start=1):
            entry = fused.setdefault(item_id, Fused(item_id))
            if name not in entry.ranks:
                entry.ranks[name] = rank
                entry.score += 1.0 / (k + rank)
    return sorted(fused.values(), key=lambda f: (-f.score, min(f.ranks.values())))
