"""Entry point: ``python -m bobanana`` launches the TUI.

``python -m bobanana --selfcheck`` runs offline diagnostics (no network).
"""

from __future__ import annotations

import argparse
import sys

from .app import Application
from .config import Settings
from .version import version_line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bobanana", description="Terminal coding agent")
    parser.add_argument("--version", action="version", version=version_line())
    parser.add_argument("--selfcheck", action="store_true", help="Run offline diagnostics and exit")
    parser.add_argument("--workspace", help="Override workspace directory")
    parser.add_argument("--debug", action="store_true", help="Verbose DEBUG logging in the terminal")
    parser.add_argument("--load-agent-reach", action="store_true",
                        help="Clone & register the Agent-Reach skill repo, then continue")
    parser.add_argument(
        "--configure",
        action="store_true",
        help="Interactive API key / base URL / model setup (writes .env)",
    )
    args = parser.parse_args(argv)

    if args.configure:
        from .env_setup import configure_api, print_env_summary

        configure_api()
        print_env_summary()
        return 0

    settings = Settings.load()
    if args.workspace:
        from pathlib import Path

        settings.workspace = Path(args.workspace).resolve()
        settings.data_dir = settings.workspace / ".bobanana"
    if args.debug:
        settings.log_level = "DEBUG"

    app = Application(settings)

    if args.load_agent_reach:
        print(app.load_agent_reach())

    if args.selfcheck:
        ok_all = True
        print(version_line() + " self-check\n" + "=" * 32)
        for name, ok, detail in app.selfcheck():
            mark = "PASS" if ok else "FAIL"
            if not ok:
                ok_all = False
            print(f"[{mark}] {name}: {detail}")
        app.close()
        return 0 if ok_all else 1

    from .tui import TerminalUI

    TerminalUI(app).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
