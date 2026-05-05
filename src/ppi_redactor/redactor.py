from __future__ import annotations

from dataclasses import dataclass

import torch
from transformers import AutoModelForTokenClassification, AutoTokenizer

MODEL_ID = "openai/privacy-filter"
REDACTION_TOKEN = "[REDACTED]"


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    label: str


def _pick_device(preferred: str | None) -> str:
    if preferred:
        return preferred
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def load_model(device: str | None = None):
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModelForTokenClassification.from_pretrained(MODEL_ID)
    dev = _pick_device(device)
    model = model.to(dev)
    model.eval()
    return model, tokenizer


def available_labels(model) -> list[str]:
    """Return the sorted set of base labels (BIO prefix stripped, excluding O)."""
    bases = set()
    for v in model.config.id2label.values():
        if v == "O":
            continue
        base = v.split("-", 1)[1] if "-" in v else v
        bases.add(base)
    return sorted(bases)


def _base_label(label: str) -> str:
    if label == "O":
        return label
    return label.split("-", 1)[1] if "-" in label else label


def redact(
    text: str,
    model,
    tokenizer,
    enabled_labels: set[str],
) -> tuple[str, list[Span]]:
    """Redact spans of `text` whose predicted base label is in `enabled_labels`.

    Returns the redacted text and the list of spans that were redacted (in
    original-text coordinates, merged into contiguous runs).
    """
    if not text or not enabled_labels:
        return text, []

    max_len = tokenizer.model_max_length
    stride = max_len // 8

    enc = tokenizer(
        text,
        return_tensors="pt",
        return_offsets_mapping=True,
        truncation=True,
        max_length=max_len,
        stride=stride,
        return_overflowing_tokens=True,
        padding=False,
    )

    offsets_per_chunk = enc.pop("offset_mapping")
    enc.pop("overflow_to_sample_mapping", None)

    n = len(text)
    redact_mask = bytearray(n)
    label_at = [None] * n  # type: list[str | None]

    device = next(model.parameters()).device
    for i in range(offsets_per_chunk.shape[0]):
        chunk = {k: v[i : i + 1].to(device) for k, v in enc.items()}
        with torch.no_grad():
            logits = model(**chunk).logits
        pred_ids = logits.argmax(dim=-1)[0].tolist()
        for (start, end), pid in zip(offsets_per_chunk[i].tolist(), pred_ids):
            if start == end:
                continue
            base = _base_label(model.config.id2label[pid])
            if base in enabled_labels:
                for j in range(start, end):
                    redact_mask[j] = 1
                    if label_at[j] is None:
                        label_at[j] = base

    out: list[str] = []
    spans: list[Span] = []
    i = 0
    while i < n:
        if redact_mask[i]:
            j = i
            run_label = label_at[i] or ""
            while j < n and redact_mask[j]:
                j += 1
            out.append(REDACTION_TOKEN)
            spans.append(Span(i, j, run_label))
            i = j
        else:
            out.append(text[i])
            i += 1

    return "".join(out), spans
