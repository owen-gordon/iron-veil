from __future__ import annotations

import shlex
import subprocess
import threading
import time

import rumps
from AppKit import NSPasteboard, NSPasteboardTypeString

from .config import Config
from .redactor import available_labels, load_model, redact

POLL_INTERVAL_S = 0.3
APP_NAME = "PPI Redactor"
ICON_IDLE = "🛡"
ICON_REDACTED = "✂️"
ICON_FLASH_S = 1.5

# Known label set for openai/privacy-filter. Populated eagerly so the Labels
# submenu is interactive before the model finishes loading. Refreshed from
# the model's id2label after load in case the set ever changes.
KNOWN_LABELS = [
    "account_number",
    "private_address",
    "private_date",
    "private_email",
    "private_person",
    "private_phone",
    "private_url",
    "secret",
]


class RedactorApp(rumps.App):
    def __init__(self) -> None:
        super().__init__(APP_NAME, title=ICON_IDLE, quit_button=None)

        self._cfg_lock = threading.Lock()
        self.cfg = Config.load()

        self._model = None
        self._tokenizer = None
        self._model_lock = threading.Lock()

        self._pause_item = rumps.MenuItem("Pause redaction", callback=self._toggle_pause)
        self._pause_item.state = 1 if self.cfg.paused else 0

        # Build the Labels submenu eagerly so it's interactive at launch.
        # rumps locks a submenu as disabled if it has no children when first
        # rendered, so we MUST add items before assigning self.menu.
        self._labels_menu = rumps.MenuItem("Labels")
        self._label_items: dict[str, rumps.MenuItem] = {}
        enabled = set(self.cfg.enabled_labels)
        for label in KNOWN_LABELS:
            item = rumps.MenuItem(label, callback=self._make_label_toggler(label))
            item.state = 1 if label in enabled else 0
            self._labels_menu.add(item)
            self._label_items[label] = item

        self._status_item = rumps.MenuItem("Last: loading model…")

        self.menu = [
            self._pause_item,
            None,
            self._labels_menu,
            None,
            self._status_item,
            rumps.MenuItem("Quit", callback=rumps.quit_application),
        ]

        threading.Thread(target=self._ensure_model, daemon=True).start()
        threading.Thread(target=self._clipboard_loop, daemon=True).start()

    # ----- model loading -----

    def _ensure_model(self):
        with self._model_lock:
            if self._model is None:
                model, tokenizer = load_model()
                self._model = model
                self._tokenizer = tokenizer
                # Add any labels the model exposes that we didn't hardcode.
                actual = set(available_labels(model))
                for label in sorted(actual - set(self._label_items)):
                    item = rumps.MenuItem(label, callback=self._make_label_toggler(label))
                    item.state = 1 if label in set(self.cfg.enabled_labels) else 0
                    self._labels_menu.add(item)
                    self._label_items[label] = item
                self._status("ready")
            return self._model, self._tokenizer

    # ----- menu callbacks -----

    def _toggle_pause(self, sender) -> None:
        with self._cfg_lock:
            self.cfg.paused = not self.cfg.paused
            sender.state = 1 if self.cfg.paused else 0
            self.cfg.save()
        self._status("paused" if self.cfg.paused else "resumed")

    def _make_label_toggler(self, label: str):
        def toggle(sender) -> None:
            with self._cfg_lock:
                enabled = set(self.cfg.enabled_labels)
                if label in enabled:
                    enabled.remove(label)
                    sender.state = 0
                else:
                    enabled.add(label)
                    sender.state = 1
                self.cfg.enabled_labels = sorted(enabled)
                self.cfg.save()
        return toggle

    # ----- clipboard loop -----

    def _clipboard_loop(self) -> None:
        pb = NSPasteboard.generalPasteboard()
        last_change = pb.changeCount()
        self_write_count = -1

        while True:
            time.sleep(POLL_INTERVAL_S)
            try:
                cur = pb.changeCount()
                if cur == last_change:
                    continue
                last_change = cur
                if cur == self_write_count:
                    continue

                with self._cfg_lock:
                    if self.cfg.paused:
                        continue
                    enabled = set(self.cfg.enabled_labels)
                    max_chars = self.cfg.max_chars

                if not enabled:
                    continue

                text = pb.stringForType_(NSPasteboardTypeString)
                if not text:
                    continue
                if len(text) < 3 or len(text) > max_chars:
                    continue

                model, tokenizer = self._ensure_model()
                redacted, spans = redact(text, model, tokenizer, enabled)
                if not spans or redacted == text:
                    continue

                pb.clearContents()
                pb.setString_forType_(redacted, NSPasteboardTypeString)
                self_write_count = pb.changeCount()
                last_change = self_write_count

                unique = sorted({s.label for s in spans if s.label})
                summary = ", ".join(unique) if unique else "?"
                self._status(f"redacted {len(spans)} span(s): {summary}")
                self._flash_icon(len(spans))
                _notify(f"Redacted {len(spans)} span(s)", summary)
            except Exception as e:
                self._status(f"error: {e}")

    # ----- helpers -----

    def _status(self, msg: str) -> None:
        self._status_item.title = f"Last: {msg}"

    def _flash_icon(self, n: int) -> None:
        """Briefly change the menubar title so redaction is visible without notifs."""
        self.title = f"{ICON_REDACTED} {n}"

        def restore():
            self.title = ICON_IDLE
        t = threading.Timer(ICON_FLASH_S, restore)
        t.daemon = True
        t.start()


def _notify(title: str, message: str) -> None:
    """Show a macOS notification via osascript.

    rumps.notification requires a bundled .app; osascript works from any
    process (shows under 'Script Editor' identity). Best-effort — silently
    swallows failures so the redaction loop never dies on a notif issue.
    """
    try:
        script = (
            f'display notification {shlex.quote(message)} '
            f'with title {shlex.quote(APP_NAME)} '
            f'subtitle {shlex.quote(title)}'
        )
        subprocess.run(
            ["osascript", "-e", script],
            check=False,
            timeout=2,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def main() -> int:
    RedactorApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
