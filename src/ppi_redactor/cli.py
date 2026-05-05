from __future__ import annotations

import sys

from .config import Config
from .redactor import available_labels, load_model, redact


def main() -> int:
    model, tokenizer = load_model()
    print("Model labels:", available_labels(model), file=sys.stderr)

    cfg = Config.load()
    enabled = set(cfg.enabled_labels)
    print(f"Redacting labels: {sorted(enabled)}", file=sys.stderr)

    print(
        "Paste text to redact, then press Ctrl-D (Ctrl-Z on Windows) when done:",
        file=sys.stderr,
    )
    text = sys.stdin.read()
    redacted, spans = redact(text, model, tokenizer, enabled)
    print(redacted)
    print(f"Redacted {len(spans)} span(s).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
