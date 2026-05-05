# ppi-redactor

A local clipboard PII redactor for macOS. Lives in your menubar, watches the
pasteboard, and rewrites copied text in place using
[`openai/privacy-filter`](https://huggingface.co/openai/privacy-filter) — a
~1.3B-parameter token classifier — so that whatever you paste is already
redacted. Nothing leaves the machine.

## Requirements

- macOS (Apple Silicon recommended — runs on the MPS backend)
- ~16 GB RAM (model is ~2.7 GB resident in bf16)
- ~5 GB free disk for the model weights
- Python 3.13 and [`uv`](https://github.com/astral-sh/uv)

A non-Mac machine can still run the CLI (`ppi-redactor cli`), it just won't
have the menubar app.

## Install

```bash
git clone <this repo>
cd ppi-redactor
uv sync --extra mac
```

The first run downloads the model (~2.7 GB) into the Hugging Face cache at
`~/.cache/huggingface/hub/`. Subsequent launches load from disk in a few
seconds.

## Run the menubar app

```bash
uv run ppi-redactor menubar
```

A 🛡 icon appears in the menubar. Click it to see:

- **Pause redaction** — toggle off when you intentionally want to copy raw text
- **Labels ▶** — checkboxes for each label class. Toggle individually:
  - `account_number` — credit cards, bank accounts, SSN-style numbers
  - `private_address` — postal addresses
  - `private_date` *(off by default)* — dates
  - `private_email` — email addresses
  - `private_person` *(off by default)* — names
  - `private_phone` — phone numbers
  - `private_url` — URLs the model considers private
  - `secret` — API keys, tokens, passwords, etc.
- **Last: …** — status of the most recent operation
- **Quit**

When something gets redacted you'll see a macOS notification *and* a brief
`✂️ N` flash on the menubar icon. The redacted text is written back to the
clipboard in place — your original copy is gone, paste is always safe.

Preferences are persisted to:

```
~/Library/Application Support/ppi-redactor/config.json
```

## First-run notes

**Notifications.** The app uses `osascript` to post notifications, so the first
redaction will trigger a macOS permission prompt to allow notifications from
"Script Editor". Approve it once. If you skip or deny it, the icon flash and
the "Last:" menu item still confirm redaction visually.

**Model load.** The model loads in a background thread, so the icon and Labels
submenu are interactive immediately. The first clipboard event after launch
may take a few seconds while the model finishes loading; subsequent events
are sub-second.

**SSNs.** The model has no dedicated SSN label — Social Security numbers
typically get classified as `account_number` or `secret`. Keep both enabled
if SSNs matter to you.

## Run on login (optional)

To start the menubar app automatically at login, create
`~/Library/LaunchAgents/com.owen.ppi-redactor.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.owen.ppi-redactor</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/uv</string>
        <string>run</string>
        <string>--directory</string>
        <string>/Users/YOU/path/to/ppi-redactor</string>
        <string>ppi-redactor</string>
        <string>menubar</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardErrorPath</key>
    <string>/tmp/ppi-redactor.err</string>
    <key>StandardOutPath</key>
    <string>/tmp/ppi-redactor.out</string>
</dict>
</plist>
```

Adjust the path to `uv` (`which uv`) and the repo path. Then:

```bash
launchctl load ~/Library/LaunchAgents/com.owen.ppi-redactor.plist
```

To stop / disable:

```bash
launchctl unload ~/Library/LaunchAgents/com.owen.ppi-redactor.plist
```

## CLI mode

For one-shot redaction from a terminal:

```bash
echo "My email is foo@bar.com" | uv run ppi-redactor cli
```

Reads stdin, prints redacted text on stdout. Uses the same per-label
preferences from the config file as the menubar app.

## Architecture

```
src/ppi_redactor/
├── redactor.py   # model load + redact(text, ..., enabled_labels)
├── config.py     # persisted preferences
├── cli.py        # stdin → stdout redaction
├── menubar.py    # rumps menubar app + clipboard loop
└── __main__.py   # entry: dispatches to cli or menubar
```

The menubar app polls `NSPasteboard.changeCount()` every 300 ms. When the
count increments, it reads the pasteboard, runs the model, and — if anything
was tagged — writes the redacted string back. A self-write guard prevents the
loop from re-processing its own output.

## Troubleshooting

**Model download is slow / fails.** Re-run; HF caches partial downloads. Make
sure you can reach `huggingface.co`.

**"Last: error: …" in the menu.** Check `/tmp/ppi-redactor.err` if running via
launchd, or the terminal output otherwise.

**Notifications don't appear.** System Settings → Notifications → Script
Editor → Allow Notifications. Or rely on the icon flash and "Last:" menu
item.

**App is using too much RAM.** Expected — the model is ~2.7 GB resident.
Toggle Pause when you don't need it, or quit and relaunch as needed.
