from __future__ import annotations

import threading
import time

import rumps
from AppKit import NSPasteboard, NSPasteboardTypeString

from .config import Config
from .redactor import available_labels, load_model, redact

POLL_INTERVAL_S = 0.3
APP_NAME = "PPI Redactor"


class RedactorApp(rumps.App):
    def __init__(self) -> None:
        super().__init__(APP_NAME, title="🛡", quit_button=None)

        self._cfg_lock = threading.Lock()
        self.cfg = Config.load()

        # Lazy-loaded; first clipboard change triggers the load.
        self._model = None
        self._tokenizer = None
        self._labels: list[str] = []
        self._model_lock = threading.Lock()

        self._pause_item = rumps.MenuItem("Pause redaction", callback=self._toggle_pause)
        self._pause_item.state = 1 if self.cfg.paused else 0

        self._labels_menu = rumps.MenuItem("Labels")
        self._label_items: dict[str, rumps.MenuItem] = {}

        self._status_item = rumps.MenuItem("Last: (idle)")
        self._status_item.set_callback(None)

        self.menu = [
            self._pause_item,
            None,
            self._labels_menu,
            None,
            self._status_item,
            rumps.MenuItem("Quit", callback=rumps.quit_application),
        ]

        # Loading the model takes a while — kick it off in a background thread
        # so the menubar icon appears immediately.
        threading.Thread(target=self._ensure_model, daemon=True).start()
        threading.Thread(target=self._clipboard_loop, daemon=True).start()

    # ----- model loading -----

    def _ensure_model(self) -> tuple[object, object]:
        with self._model_lock:
            if self._model is None:
                self._status("Loading model…")
                model, tokenizer = load_model()
                self._model = model
                self._tokenizer = tokenizer
                self._labels = available_labels(model)
                # Build the Labels submenu on the main thread via rumps timer.
                rumps.Timer(self._populate_labels_once, 0.01).start()
                self._status("Ready")
            return self._model, self._tokenizer

    def _populate_labels_once(self, sender) -> None:
        sender.stop()
        if self._label_items:
            return
        enabled = set(self.cfg.enabled_labels)
        for label in self._labels:
            item = rumps.MenuItem(label, callback=self._make_label_toggler(label))
            item.state = 1 if label in enabled else 0
            self._labels_menu.add(item)
            self._label_items[label] = item

    # ----- menu callbacks -----

    def _toggle_pause(self, sender) -> None:
        with self._cfg_lock:
            self.cfg.paused = not self.cfg.paused
            sender.state = 1 if self.cfg.paused else 0
            self.cfg.save()
        self._status("Paused" if self.cfg.paused else "Resumed")

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
        # Track our own writes so we don't reprocess them.
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
                self._status(f"Redacted {len(spans)} span(s): {summary}")
                try:
                    rumps.notification(
                        APP_NAME,
                        f"Redacted {len(spans)} span(s)",
                        summary,
                    )
                except Exception:
                    # Notifications require a bundled .app on recent macOS;
                    # fall back silently when running via `uv run`.
                    pass
            except Exception as e:  # don't let the loop die
                self._status(f"Error: {e}")

    # ----- helpers -----

    def _status(self, msg: str) -> None:
        self._status_item.title = f"Last: {msg}"


def main() -> int:
    RedactorApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
