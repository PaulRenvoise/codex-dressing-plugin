#!/usr/bin/env python3
"""Install Dressing or configure its existing Obsidian collection locations."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "plugins/dressing/scripts"))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Install Dressing. Prefer the native plugin settings page for collection paths.")
    parser.add_argument("--install", action="store_true", help="Register this checkout and install Dressing in Codex.")
    parser.add_argument("--check", action="store_true", help="Check runtime prerequisites without installing anything.")
    parser.add_argument("--inventory-base", help="Existing vault-relative Inventory .base file.")
    parser.add_argument("--preferences-base", help="Existing vault-relative Preferences .base file.")
    parser.add_argument("--styleboard-canvas", help="Existing vault-relative Styleboard .canvas file.")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 11):
        parser.error("Python 3.11 or later is required.")
    if sys.platform not in {"darwin", "linux"}:
        parser.error("Dressing requires macOS or Linux.")
    from dressing_settings import read_values, update_settings
    from plugin_dependency import obsidian_wrapper
    from dressing import DressingError, Vault

    changes = {key: getattr(args, key) for key in
               ("inventory_base", "preferences_base", "styleboard_canvas")
               if getattr(args, key) is not None}
    try:
        if args.check or args.install:
            for executable in ("codex", "uv"):
                if not shutil.which(executable):
                    raise ValueError(f"{executable} must be available on PATH.")
            codex_dir = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
            obsidian_wrapper(codex_dir)
            print("Codex, uv and the enabled Obsidian plugin are available.")
            print("Obsidian must also be running with CLI support and a configured vault.")
        values = update_settings(changes, Vault())["values"] if changes else read_values()
        print(json.dumps(values, ensure_ascii=False, indent=2))
        if args.install:
            subprocess.run(["codex", "plugin", "marketplace", "add", str(ROOT)], check=True)
            subprocess.run(["codex", "plugin", "add", "dressing@codex-dressing-plugin"], check=True)
            print("Dressing installed. Reload Codex or start a new conversation.")
    except (DressingError, OSError, ValueError, subprocess.SubprocessError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
