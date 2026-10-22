"""Resolve Dressing's runtime Obsidian prerequisite from installed Codex plugins."""
import json
from pathlib import Path
import shutil
import subprocess


def obsidian_wrapper(codex_home):
    codex = shutil.which("codex")
    if not codex:
        raise ValueError("Codex CLI was not found on PATH. Make codex available to the app so Dressing can locate the installed Obsidian plugin.")
    try:
        result = subprocess.run([codex, "plugin", "list", "--json"],
                                capture_output=True, text=True, timeout=15, check=True)
        installed = json.loads(result.stdout)["installed"]
        if not isinstance(installed, list):
            raise ValueError("Invalid installed plugin list")
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as error:
        raise ValueError("Cannot discover installed plugins through codex plugin list --json. Check that the Codex CLI supports this command.") from error
    candidates = [p for p in installed if isinstance(p, dict) and p.get("name") == "obsidian"
                  and p.get("installed") is True and p.get("enabled") is True]
    if not candidates:
        raise ValueError("Install and enable the Obsidian plugin, then configure its vault in Plugins before using Dressing.")
    if len(candidates) != 1:
        raise ValueError("Multiple Obsidian plugins are enabled. Enable only the intended Obsidian plugin before using Dressing.")
    plugin = candidates[0]
    parts = [plugin.get("marketplaceName"), plugin.get("name"), plugin.get("version")]
    if any(not isinstance(p, str) or not p or p in {".", ".."} or any(c in p for c in "/\\:") for p in parts):
        raise ValueError("Codex returned incomplete or invalid Obsidian installation metadata.")
    # Codex's installed cache layout is isolated here. Use the exact enabled version,
    # never a guessed latest version or the mutable marketplace authoring source.
    cache = (Path(codex_home) / "plugins/cache").resolve()
    root = cache.joinpath(*parts).resolve()
    if not root.is_relative_to(cache):
        raise ValueError("Obsidian installation resolves outside the Codex plugin cache.")
    try:
        manifest = json.loads((root / ".codex-plugin/plugin.json").read_text())
    except (OSError, ValueError) as error:
        raise ValueError("The installed Obsidian package is missing or unreadable. Reinstall Obsidian from its marketplace.") from error
    if not isinstance(manifest, dict) or manifest.get("name") != "obsidian" or manifest.get("version") != plugin["version"]:
        raise ValueError("Obsidian package identity does not match the installed version. Reinstall Obsidian.")
    wrapper = root / "scripts/obsidian.py"
    for file in (wrapper, root / "scripts/settings_store.py"):
        if not file.resolve().is_relative_to(root) or not file.is_file():
            raise ValueError("This Obsidian plugin does not provide the expected settings-aware CLI wrapper. Install a compatible version.")
    return wrapper
