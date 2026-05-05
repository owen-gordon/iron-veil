from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Labels enabled by default. Names and dates are intentionally OFF: they're
# noisy and usually not what you want stripped from a casual copy.
DEFAULT_ENABLED = [
    "account_number",
    "private_address",
    "private_email",
    "private_phone",
    "private_url",
    "secret",
]


def config_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ppi-redactor"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "ppi-redactor"


def config_path() -> Path:
    return config_dir() / "config.json"


@dataclass
class Config:
    enabled_labels: list[str] = field(default_factory=lambda: list(DEFAULT_ENABLED))
    paused: bool = False
    max_chars: int = 50_000

    @classmethod
    def load(cls) -> "Config":
        p = config_path()
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return cls()
        return cls(
            enabled_labels=list(data.get("enabled_labels", DEFAULT_ENABLED)),
            paused=bool(data.get("paused", False)),
            max_chars=int(data.get("max_chars", 50_000)),
        )

    def save(self) -> None:
        d = config_dir()
        d.mkdir(parents=True, exist_ok=True)
        target = config_path()
        with tempfile.NamedTemporaryFile(
            "w", dir=d, prefix=".config-", suffix=".tmp", delete=False
        ) as f:
            json.dump(asdict(self), f, indent=2)
            tmp = f.name
        os.replace(tmp, target)
