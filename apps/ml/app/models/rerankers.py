from typing import Any

QWEN3_PREFIX = (
    "<|im_start|>system\nJudge whether the Document meets the requirements based on the Query "
    'and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n'
    "<|im_start|>user\n"
)
QWEN3_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


class Qwen3Reranker:
    def __init__(
        self, name: str, *, device: str, instruction: str, max_tokens: int, batch_size: int
    ) -> None:
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.name = name
        self.device = device
        self.instruction = instruction
        self.max_tokens = max_tokens
        self.batch_size = batch_size
        self.tokenizer: Any = AutoTokenizer.from_pretrained(name, padding_side="left")
        loaded: Any = AutoModelForCausalLM.from_pretrained(name)
        self.model: Any = loaded.to(device).eval()
        self.true_id = self.tokenizer.convert_tokens_to_ids("yes")
        self.false_id = self.tokenizer.convert_tokens_to_ids("no")
        self.prefix = self.tokenizer.encode(QWEN3_PREFIX, add_special_tokens=False)
        self.suffix = self.tokenizer.encode(QWEN3_SUFFIX, add_special_tokens=False)

    def _format(self, query: str, doc: str) -> str:
        return f"<Instruct>: {self.instruction}\n<Query>: {query}\n<Document>: {doc}"

    def score(self, query: str, documents: list[str]) -> list[float]:
        import torch

        scores: list[float] = []
        budget = self.max_tokens - len(self.prefix) - len(self.suffix)
        for batch in _chunks(documents, self.batch_size):
            inputs = self.tokenizer(
                [self._format(query, d) for d in batch],
                padding=False,
                truncation="longest_first",
                return_attention_mask=False,
                max_length=budget,
            )
            inputs["input_ids"] = [self.prefix + ids + self.suffix for ids in inputs["input_ids"]]
            padded = self.tokenizer.pad(
                inputs, padding=True, return_tensors="pt", max_length=self.max_tokens
            )
            padded = {k: v.to(self.device) for k, v in padded.items()}
            with torch.no_grad():
                logits = self.model(**padded).logits[:, -1, :]
            pair = torch.stack([logits[:, self.false_id], logits[:, self.true_id]], dim=1)
            scores.extend(torch.nn.functional.log_softmax(pair, dim=1)[:, 1].exp().tolist())
        return scores
