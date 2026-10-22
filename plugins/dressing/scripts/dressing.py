#!/usr/bin/env python3
"""Local Dressing operations through the configured Obsidian plugin."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import sys
import tempfile
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import uuid

from dressing_settings import DEFAULTS, Locations, read_values
from plugin_dependency import obsidian_wrapper

# Default locations retained for callers; runtime operations use vault.locations.
INVENTORY = str(PurePosixPath(DEFAULTS["inventory_base"]).parent)
PREFERENCES = str(PurePosixPath(DEFAULTS["preferences_base"]).parent)
STYLEBOARD = str(PurePosixPath(DEFAULTS["styleboard_canvas"]).parent)
CANVAS = DEFAULTS["styleboard_canvas"]
LIST_FIELDS = {"clothing_category", "clothing_brand", "color", "clothing_fit", "clothing_label_size"}
MEASURES = {"clothing_" + k + "_cm" for k in ("chest", "shoulder", "sleeve", "length", "waist", "hip", "front", "inseam")}
CLOTHING = LIST_FIELDS | MEASURES | {"clothing_materials", "clothing_link", "price"}
RATINGS = {"yes", "maybe", "no"}


class DressingError(Exception):
    pass


def normalized(value):
    return re.sub(r"\W+", " ", unicodedata.normalize("NFKC", value).casefold()).strip()


def valid_url(value):
    u = urlsplit(value)
    if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password:
        raise DressingError("Expected an HTTP(S) URL without credentials.")
    return value


def url_key(value, host_only=False):
    if not value:
        return ""
    u = urlsplit(value)
    host = (u.hostname or "").lower().removeprefix("www.")
    if host_only:
        return host
    query = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit(("", host, u.path.rstrip("/"), urlencode(sorted(query)), ""))


def as_list(value):
    return value if isinstance(value, list) else ([] if value is None else [value])


def kind_of(props):
    value = props.get("preference_type")
    # Accept existing Obsidian list typing without rewriting it.
    return value[0] if isinstance(value, list) and len(value) == 1 else value


def piece_identity(a, b):
    """Return same, different or ambiguous; don't conflate colourways."""
    pa, pb = a["properties"], b["properties"]
    na, nb = normalized(a["name"]), normalized(b["name"])
    ba = [normalized(v) for v in as_list(pa.get("clothing_brand"))]
    bb = [normalized(v) for v in as_list(pb.get("clothing_brand"))]
    ca = sorted(v.lower() for v in as_list(pa.get("color")))
    cb = sorted(v.lower() for v in as_list(pb.get("color")))
    same_url = bool(url_key(pa.get("clothing_link"))) and url_key(pa.get("clothing_link")) == url_key(pb.get("clothing_link"))
    same_name = na == nb and bool(ba) and ba == bb
    if ca and cb and ca != cb:
        return "different"
    if same_name or (same_url and ca and cb):
        return "same"
    if same_url:
        return "ambiguous"
    return "different"


def yaml_value(value, indent=None):
    # Valid YAML JSON syntax, avoiding Obsidian CLI's \n / \t expansion.
    encoded = json.dumps(value, ensure_ascii=False, indent=indent)
    return re.sub(r'\\(?:\\|n|r|t)', lambda m: {
        "\\\\": "\\u005c", "\\n": "\\u000a", "\\r": "\\u000d", "\\t": "\\u0009"
    }[m.group()], encoded)


def note_content(props, body=""):
    return "---\n" + "".join(k + ": " + yaml_value(v) + "\n" for k, v in props.items()) + "---\n" + body


def note_body(content):
    match = re.match(r"\A---\r?\n.*?\r?\n---(?:\r?\n|\Z)", content, re.S)
    if not match:
        raise DressingError("Existing note has no recognizable frontmatter; use a targeted manual edit.")
    return content[match.end():]


def filename(name):
    value = re.sub(r'[/\\:*?"<>|\x00-\x1f]', "-", name).strip(" .")
    if not value or len(value.encode("utf-8")) > 220:
        raise DressingError("Choose a nonempty shorter note name.")
    return value + ".md"


class Vault:
    def __init__(self):
        self.locations = Locations(read_values())
        codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
        self.wrapper = obsidian_wrapper(codex_home)
        try:
            settings = codex_home / "plugin-data/obsidian/settings.json"
            self.config = json.loads(settings.read_text())
            folder = self.config["vault_path"]
            if not isinstance(folder, str) or not folder.strip():
                raise ValueError("No configured vault")
            self.root = Path(folder).expanduser().resolve(strict=True)
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise DressingError("Configure the installed Obsidian plugin first.") from e

    def writable(self):
        if self.config.get("read_only", False):
            raise DressingError("Obsidian connection is read-only; do not change it silently.")

    def path(self, relative):
        value = Path(relative)
        target = (self.root / value).resolve()
        if value.is_absolute() or ".." in value.parts or not target.is_relative_to(self.root):
            raise DressingError("Path must stay inside the configured vault.")
        return target

    def cli(self, *args):
        process = subprocess.Popen([sys.executable, str(self.wrapper), *args],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        try:
            out, err = process.communicate(timeout=25)
        except subprocess.TimeoutExpired as e:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise DressingError("Obsidian CLI timed out. Read back before retrying any write.") from e
        if process.returncode or out.lstrip().startswith("Error:"):
            raise DressingError((err or out).strip() or "Obsidian CLI failed.")
        return out

    def read(self, path):
        # CLI for properties/actions; exact local bytes for concurrency checks.
        return self.path(path).read_text()

    def records(self, folder, base):
        self.path(folder)
        rows = []
        folders = [] if folder == "." else ["folder=" + folder]
        for path in self.cli("files", *folders, "ext=md").splitlines():
            if str(Path(path).parent) != folder:
                continue
            raw = self.cli("properties", "path=" + path, "format=json")
            props = {} if raw.strip() == "No frontmatter found." else json.loads(raw)
            if props.get("base") == base:
                rows.append({"path": path, "name": Path(path).stem, "properties": props})
        return rows

    def write(self, path, content, before=None):
        self.writable()
        target = self.path(path)
        backup = None
        if before is None:
            if target.exists():
                raise DressingError("Destination already exists; refusing to overwrite: " + path)
        else:
            if self.read(path) != before:
                raise DressingError("File changed since reading; reload before applying.")
            backup_dir = Path(tempfile.mkdtemp(prefix="dressing-backup-"))
            backup = backup_dir / target.name
            backup.write_text(before)
        args = ["create", "path=" + path, "content=" + content]
        if before is not None:
            args.append("overwrite")
        self.cli(*args)
        # CLI may add a final newline; do not normalize content inside the note.
        actual = self.read(path)
        if actual != content and actual != content + "\n":
            raise DressingError("Write could not be verified; inspect " + path + " before retrying.")
        return str(backup) if backup else None


def validate_input(kind, data):
    if kind not in {"inventory", "feedback", "source", "style"}:
        raise DressingError("Unsupported record kind.")
    if not isinstance(data, dict) or set(data) - {"name", "properties"}:
        raise DressingError("Input must contain name and properties only.")
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        raise DressingError("A nonempty name is required.")
    props = data.get("properties")
    if not isinstance(props, dict):
        raise DressingError("properties must be an object.")
    allowed = (CLOTHING | {"clothing_photo"} if kind == "inventory" else
               CLOTHING | {"feedback_rating", "feedback_comment"} if kind == "feedback" else
               {"source_link"} if kind == "source" else set())
    if set(props) - allowed:
        raise DressingError("Unsupported properties: " + ", ".join(sorted(set(props) - allowed)))
    for key, value in props.items():
        if key in LIST_FIELDS:
            if not isinstance(value, list) or not value or not all(isinstance(v, str) and v for v in value):
                raise DressingError(key + " must be a nonempty list of strings.")
        elif key in MEASURES | {"price"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise DressingError(key + " must be a nonnegative number.")
        elif not isinstance(value, str):
            raise DressingError(key + " must be text.")
    for color in props.get("color", []):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise DressingError("Use verified six-digit hexadecimal colours, or omit color.")
    for key in ("source_link", "clothing_link"):
        if key in props:
            valid_url(props[key])
    if kind == "source" and not props.get("source_link"):
        raise DressingError("source_link is required.")
    if kind == "feedback" and props.get("feedback_rating") not in RATINGS:
        raise DressingError("feedback_rating must be yes, maybe or no.")
    return props.copy()


def save(vault, kind, data, apply=False, importing=False):
    props = validate_input(kind, data)
    current = {"name": data["name"], "properties": props}
    inventory = vault.records(vault.locations.inventory_folder, vault.locations.inventory_name) if kind in {"inventory", "feedback"} else []
    if kind == "feedback":
        for owned in inventory:
            relation = piece_identity(current, owned)
            if relation == "same":
                return {"status": "skipped_owned", "inventory_path": owned["path"]}
            if relation == "ambiguous":
                raise DressingError("Possible owned variant; resolve colour/model before saving: " + owned["path"])
    records = inventory if kind == "inventory" else vault.records(vault.locations.preferences_folder, vault.locations.preferences_name)
    if kind != "inventory":
        records = [r for r in records if kind_of(r["properties"]) == kind]
    matches = []
    for record in records:
        if kind == "style":
            relation = "same" if normalized(current["name"]) == normalized(record["name"]) else "different"
        elif kind == "source":
            relation = "same" if url_key(props.get("source_link"), True) == url_key(record["properties"].get("source_link"), True) else "different"
        else:
            relation = piece_identity(current, record)
        if relation == "same":
            matches.append(record)
        elif relation == "ambiguous":
            raise DressingError("Resolve an ambiguous existing variant: " + record["path"])
    if len(matches) > 1:
        raise DressingError("Multiple existing matches; resolve duplicates before writing.")
    if matches:
        found = matches[0]
        if kind != "feedback":
            return {"status": "exists", "path": found["path"]}
        changes = {k: props[k] for k in ("feedback_rating", "feedback_comment")
                   if k in props and props[k] != found["properties"].get(k)}
        if not changes:
            return {"status": "unchanged", "path": found["path"]}
        if importing:
            raise DressingError("Import conflict; existing opinion preserved: " + found["path"])
        result = {"status": "updated" if apply else "would_update", "path": found["path"], "changes": changes}
        if apply:
            before = vault.read(found["path"])
            merged = dict(found["properties"], **changes)
            result["backup"] = vault.write(found["path"], note_content(merged, note_body(before)), before)
            actual = json.loads(vault.cli("properties", "path=" + found["path"], "format=json"))
            if actual != merged:
                raise DressingError("Updated properties differ on read-back; inspect the note.")
        return result
    base = vault.locations.inventory_name if kind == "inventory" else vault.locations.preferences_name
    all_props = {"base": base}
    if kind != "inventory":
        all_props["preference_type"] = kind
    all_props.update(props)
    if kind == "feedback":
        all_props.setdefault("feedback_comment", "")
    folder = vault.locations.inventory_folder if kind == "inventory" else vault.locations.preferences_folder
    path = str(PurePosixPath(folder) / filename(data["name"]))
    if vault.path(path).exists():
        raise DressingError("Filename collision; use a name including brand/colour: " + path)
    result = {"status": "created" if apply else "would_create", "path": path, "properties": all_props}
    if apply:
        vault.write(path, note_content(all_props))
        actual = json.loads(vault.cli("properties", "path=" + path, "format=json"))
        if actual != all_props:
            raise DressingError("Created properties differ on read-back; inspect the note.")
    return result


def image_extension(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    raise DressingError("Input is not a supported PNG/JPEG/GIF/WebP image.")


def attach_image(vault, source, collection, apply=False):
    source = Path(source)
    if source.stat().st_size > 25 * 1024 * 1024:
        raise DressingError("Image exceeds 25 MiB; choose a suitable original-size asset.")
    data = source.read_bytes()
    ext = image_extension(data)
    digest = hashlib.sha256(data).hexdigest()
    folder = vault.locations.inventory_folder if collection == "inventory" else vault.locations.styleboard_folder
    # Also recognize assets the user had already saved under a different name.
    for candidate in vault.path(folder).rglob("*"):
        if candidate.is_file() and candidate.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            if candidate.stat().st_size == len(data) and hashlib.sha256(candidate.read_bytes()).hexdigest() == digest:
                path = candidate.relative_to(vault.root).as_posix()
                return {"status": "exists", "file": path, "wikilink": "[[" + path + "]]"}
    path = str(PurePosixPath(folder) / (digest[:24] + ext))
    target = vault.path(path)
    if apply:
        vault.writable()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise DressingError("Attachment read-back failed.")
    return {"status": "created" if apply else "would_create", "file": path, "wikilink": "[[" + path + "]]"}


def canvas_add(vault, data, apply=False):
    if not isinstance(data, dict) or set(data) - {"file", "source_url", "title", "note", "group"}:
        raise DressingError("Canvas input has unsupported fields.")
    for field in ("file", "source_url", "title", "note", "group"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise DressingError("Canvas selection requires " + field)
    valid_url(data["source_url"])
    if not vault.path(data["file"]).is_relative_to(vault.path(vault.locations.styleboard_folder)) or not vault.path(data["file"]).is_file():
        raise DressingError("Use a saved image within the configured Styleboard folder.")
    image_extension(vault.path(data["file"]).read_bytes())
    before = vault.read(vault.locations.styleboard_canvas)
    board = json.loads(before)
    nodes, edges = board.get("nodes"), board.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise DressingError("Unexpected Canvas structure.")
    ids = [n["id"] for n in nodes] + [e["id"] for e in edges]
    if len(set(ids)) != len(ids):
        raise DressingError("Canvas has duplicate IDs; resolve before editing.")
    for node in nodes:
        if node.get("file") == data["file"] or (node.get("type") == "link" and url_key(node.get("url")) == url_key(data["source_url"])):
            return {"status": "exists", "path": vault.locations.styleboard_canvas, "node_id": node["id"]}
    groups = [n for n in nodes if n.get("type") == "group" and n.get("label") == data["group"]]
    if len(groups) != 1:
        raise DressingError("Choose one exact existing group label from the current Canvas.")
    # Add beside all existing geometry. Never resize or move the user's layout.
    x = max((n["x"] + n["width"] for n in nodes), default=0) + 100
    y = groups[0]["y"]
    def new_id():
        value = uuid.uuid4().hex[:16]
        while value in ids:
            value = uuid.uuid4().hex[:16]
        ids.append(value)
        return value
    additions = [
        {"id": new_id(), "type": "group", "label": data["group"] + " · " + data["title"], "x": x, "y": y, "width": 600, "height": 850},
        {"id": new_id(), "type": "file", "file": data["file"], "x": x + 30, "y": y + 60, "width": 540, "height": 540},
        {"id": new_id(), "type": "link", "url": data["source_url"], "x": x + 30, "y": y + 620, "width": 540, "height": 80},
        {"id": new_id(), "type": "text", "text": data["title"] + "\n\n" + data["note"], "x": x + 30, "y": y + 720, "width": 540, "height": 100},
    ]
    board["nodes"] = nodes + additions
    result = {"status": "added" if apply else "would_add", "path": vault.locations.styleboard_canvas, "nodes": additions}
    if apply:
        result["backup"] = vault.write(vault.locations.styleboard_canvas, yaml_value(board, indent=2) + "\n", before)
        if json.loads(vault.read(vault.locations.styleboard_canvas)) != board:
            raise DressingError("Canvas read-back failed.")
    return result


def context(vault, scope, query=""):
    result = {"vault": str(vault.root), "locations": vault.locations.values}
    for key, folder, base in (("inventory", vault.locations.inventory_folder, vault.locations.inventory_name),
                              ("preferences", vault.locations.preferences_folder, vault.locations.preferences_name)):
        if scope in {"all", key}:
            rows = vault.records(folder, base)
            result[key] = [r for r in rows if query.casefold() in json.dumps(r, ensure_ascii=False).casefold()]
            result[key + "_total"] = len(rows)
    if scope in {"all", "styleboard"}:
        result["styleboard"] = {"path": vault.locations.styleboard_canvas, "canvas": json.loads(vault.read(vault.locations.styleboard_canvas))}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    c = commands.add_parser("context", help="Read current vault context")
    c.add_argument("--scope", choices=["all", "inventory", "preferences", "styleboard"], default="all")
    c.add_argument("--query", default="")
    s = commands.add_parser("save", help="Preview or save a note")
    s.add_argument("--kind", choices=["inventory", "feedback", "source", "style"], required=True)
    s.add_argument("--input", required=True)
    s.add_argument("--apply", action="store_true")
    s.add_argument("--import", dest="importing", action="store_true")
    a = commands.add_parser("attach-image", help="Save a previously downloaded real image")
    a.add_argument("--input", required=True)
    a.add_argument("--collection", choices=["inventory", "styleboard"], required=True)
    a.add_argument("--apply", action="store_true")
    c = commands.add_parser("canvas-add", help="Add an already selected image reference")
    c.add_argument("--input", required=True)
    c.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        vault = Vault()
        if args.command == "context":
            result = context(vault, args.scope, args.query)
        elif args.command == "attach-image":
            result = attach_image(vault, args.input, args.collection, args.apply)
        else:
            data = json.loads(Path(args.input).read_text())
            result = save(vault, args.kind, data, args.apply, args.importing) if args.command == "save" else canvas_add(vault, data, args.apply)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (DressingError, OSError, ValueError, KeyError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
