"""Native Dressing settings, persisted independently of installed plugin versions."""
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import tempfile

DEFAULTS = {
    "inventory_base": "Dressing/Inventory/Inventory.base",
    "preferences_base": "Dressing/Preferences/Preferences.base",
    "styleboard_canvas": "Dressing/Styleboard/Styleboard.canvas",
}
FIELDS = {
    key: {"type": "string", "title": title, "minLength": 1, "maxLength": 4096,
          "description": description}
    for key, title, description in (
        ("inventory_base", "Inventory Base", "Existing .base file, relative to your Obsidian vault. Garment notes and photos are stored directly beside this Base file."),
        ("preferences_base", "Preferences Base", "Existing .base file, relative to your Obsidian vault. Feedback, source and style notes use its parent folder."),
        ("styleboard_canvas", "Styleboard Canvas", "Existing .canvas file, relative to your Obsidian vault. Reference images are stored directly beside this Canvas file. Changing paths never moves existing files."),
    )
}
CAPABILITY = {"openai/settings": {"readTool": "settings_read", "updateTool": "settings_update"}}


def validate(changes):
    if not isinstance(changes, dict) or set(changes) - DEFAULTS.keys():
        raise ValueError("Only Inventory Base, Preferences Base and Styleboard Canvas can be configured.")
    for key, value in changes.items():
        suffix = ".canvas" if key == "styleboard_canvas" else ".base"
        if (not isinstance(value, str) or not value or len(value) > 4096
                or value != value.strip() or value.startswith(("/", "~"))
                or any(c in value for c in "\\:") or any(ord(c) < 32 or ord(c) == 127 for c in value)
                or any(part in {"", ".", ".."} for part in value.split("/"))
                or not value.endswith(suffix)):
            raise ValueError(f"{FIELDS[key]['title']} must be a vault-relative {suffix} file path without traversal or control characters.")


class Locations:
    def __init__(self, values):
        validate(values)
        self.values = dict(DEFAULTS, **values)
        if self.inventory_base == self.preferences_base:
            raise ValueError("Inventory and Preferences must use different Base files.")

    def __getattr__(self, key):
        if key in self.values:
            return self.values[key]
        if key.endswith("_folder"):
            setting = "styleboard_canvas" if key == "styleboard_folder" else key.removesuffix("_folder") + "_base"
            if setting in self.values:
                return str(PurePosixPath(self.values[setting]).parent)
        if key in {"inventory_name", "preferences_name"}:
            return PurePosixPath(self.values[key.removesuffix("_name") + "_base"]).name
        raise AttributeError(key)

    def identity(self, vault, *keys):
        return (str(vault.root), *(self.values[key] for key in keys))


def settings_path():
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser() / "plugin-data/dressing/settings.json"


def read_values():
    path = settings_path()
    if not path.exists():
        return dict(DEFAULTS)
    try:
        return Locations(json.loads(path.read_text())).values
    except (OSError, ValueError) as error:
        raise ValueError(f"Cannot read Dressing settings at {path}: {error}") from error


def read_settings():
    return {"schema": {"type": "object", "properties": FIELDS, "required": list(FIELDS)},
            "values": read_values(), "layout": [{"kind": "group", "title": "Obsidian locations",
            "items": [{"kind": "property", "property": key} for key in FIELDS]}]}


def update_settings(changes, vault):
    validate(changes)
    if not changes:
        return {"values": read_values()}
    # Validate only changed destinations so an unrelated missing file can be repaired later.
    for key, value in changes.items():
        if not vault.path(value).is_file():
            raise ValueError(f"{FIELDS[key]['title']} does not exist in the configured Obsidian vault: {value}")
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Lock the directory: replacing the JSON file must not replace the lock inode.
    lock = os.open(path.parent, os.O_RDONLY)
    temporary = None
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        values = Locations(dict(read_values(), **changes)).values
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".settings-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(values, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.fsync(lock)
        return {"values": values}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        os.close(lock)
