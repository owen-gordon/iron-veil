from __future__ import annotations

import sys


def main() -> int:
    args = sys.argv[1:]
    cmd = args[0] if args else "cli"
    if cmd == "menubar":
        from .menubar import main as run
    elif cmd == "cli":
        from .cli import main as run
    else:
        print(f"Unknown command: {cmd!r}. Use 'cli' or 'menubar'.", file=sys.stderr)
        return 2
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
