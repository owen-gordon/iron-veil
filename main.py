import sys

import torch
from transformers import AutoModelForTokenClassification, AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained("openai/privacy-filter")
model = AutoModelForTokenClassification.from_pretrained("openai/privacy-filter", device_map="auto")

# Only redact labels containing one of these substrings (case-insensitive).
# Set to None to redact everything non-"O".
REDACT_LABELS = {"SSN", "CREDIT", "BANK", "ACCOUNT", "PASSPORT", "LICENSE"}

def should_redact(label: str) -> bool:
    if label == "O":
        return False
    if REDACT_LABELS is None:
        return True
    upper = label.upper()
    return any(tag in upper for tag in REDACT_LABELS)

print("Model labels:", sorted(set(model.config.id2label.values())), file=sys.stderr)

print("Paste text to redact, then press Ctrl-D (Ctrl-Z on Windows) when done:")
text = sys.stdin.read()

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

redact_mask = [False] * len(text)

for i in range(offsets_per_chunk.shape[0]):
    chunk = {k: v[i : i + 1].to(model.device) for k, v in enc.items()}
    with torch.no_grad():
        logits = model(**chunk).logits
    pred_ids = logits.argmax(dim=-1)[0].tolist()
    for (start, end), pid in zip(offsets_per_chunk[i].tolist(), pred_ids):
        if start == end:
            continue
        if should_redact(model.config.id2label[pid]):
            for j in range(start, end):
                redact_mask[j] = True

out = []
i = 0
n = len(text)
while i < n:
    if redact_mask[i]:
        j = i
        while j < n and redact_mask[j]:
            j += 1
        out.append("[REDACTED]")
        i = j
    else:
        out.append(text[i])
        i += 1

print("".join(out))
