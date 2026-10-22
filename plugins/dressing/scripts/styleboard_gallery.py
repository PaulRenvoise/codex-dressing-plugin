"""State and Canvas writes for user-selected Styleboard references."""
import copy
import json
import math
import secrets
import tempfile
import time
import uuid
from pathlib import Path
from dressing import DressingError, attach_image, image_extension, url_key, valid_url, yaml_value
from public_images import MAX_BYTES, download_image, image_target

UI_URI = "ui://dressing/styleboard-gallery-v2"


def image_url(value):
    return image_target(value)[0]


def read_board(vault):
    before = vault.read(vault.locations.styleboard_canvas)
    board = json.loads(before)
    if not isinstance(board, dict) or not isinstance(board.get("nodes"), list) or not isinstance(board.get("edges"), list):
        raise DressingError("Unexpected Styleboard Canvas structure.")
    nodes = board["nodes"]
    ids = [n["id"] for n in nodes] + [e["id"] for e in board["edges"]]
    if len(ids) != len(set(ids)):
        raise DressingError("The Canvas contains duplicate IDs.")
    for n in nodes:
        if any(not isinstance(n.get(k), (int, float)) or isinstance(n[k], bool) or not math.isfinite(n[k])
               for k in ("x", "y", "width", "height")) or n["width"] <= 0 or n["height"] <= 0:
            raise DressingError("The Canvas contains invalid node geometry.")
    node_ids = {n["id"] for n in nodes}
    if any(e.get("fromNode") not in node_ids or e.get("toNode") not in node_ids for e in board["edges"]):
        raise DressingError("The Canvas contains an edge with a missing endpoint.")
    return before, board


def contains(a, b):
    return a["x"] <= b["x"] and a["y"] <= b["y"] and a["x"] + a["width"] >= b["x"] + b["width"] and a["y"] + a["height"] >= b["y"] + b["height"]


def overlaps(a, b):
    return a["x"] < b["x"] + b["width"] and a["x"] + a["width"] > b["x"] and a["y"] < b["y"] + b["height"] and a["y"] + a["height"] > b["y"]


def place_reference(board, group, reference):
    """Fill free space, or grow only the destination group into empty space."""
    others = [n for n in board["nodes"] if n["id"] != group["id"]]
    ancestors = [n for n in others if n["type"] == "group" and contains(n, group)]
    obstacles = [n for n in others if n not in ancestors]
    width, height = min(360, max(240, group["width"] - 48)), 490

    def free_slot(rect):
        xs = sorted({rect["x"] + 24} | {n["x"] + n["width"] + 24 for n in obstacles})
        ys = sorted({rect["y"] + 60} | {n["y"] + n["height"] + 24 for n in obstacles})
        for y in ys:
            for x in xs:
                slot = {"x": x, "y": y, "width": width, "height": height}
                padded = dict(slot, width=width + 24, height=height + 24)
                if x >= rect["x"] + 24 and y >= rect["y"] + 60 and contains(rect, padded) and not any(overlaps(padded, n) for n in obstacles):
                    return slot

    slot = free_slot(group)
    if slot is None:
        outside = [n for n in obstacles if not contains(group, n)]
        candidates = [dict(group, height=group["height"] + height + 84),
                      dict(group, y=group["y"] - height - 84, height=group["height"] + height + 84),
                      dict(group, width=group["width"] + width + 48),
                      dict(group, x=group["x"] - width - 48, width=group["width"] + width + 48)]
        for candidate in candidates:
            if any(overlaps(candidate, n) for n in outside) or any(not contains(n, candidate) for n in ancestors):
                continue
            slot = free_slot(candidate)
            if slot:
                group.update(candidate)
                break
    if slot is None:
        raise DressingError("No free space in or around this group. Make room in the Canvas or choose another group; no references were added.")
    x, y = slot["x"], slot["y"]
    ids = {n["id"] for n in board["nodes"]} | {e["id"] for e in board["edges"]}
    def node(kind, dy, h, **fields):
        identity = uuid.uuid4().hex[:16]
        while identity in ids:
            identity = uuid.uuid4().hex[:16]
        ids.add(identity)
        return dict(id=identity, type=kind, x=x, y=y + dy, width=width, height=h, **fields)
    picture = node("file", 0, 320, file=reference["file"]) if reference.get("file") else node("text", 0, 320, text="Image unavailable — use the source link below.")
    board["nodes"].extend([picture, node("link", 332, 60, url=reference["source_url"]),
                           node("text", 404, 86, text=reference["title"] + "\n\n" + reference["note"])])
    return picture


class Gallery:
    def __init__(self, vault_factory, downloader=download_image):
        self.vault_factory = vault_factory
        self.downloader = downloader
        self.sessions = {}

    def show(self, args):
        if set(args) - {"references", "demo"} or not isinstance(args.get("references"), list) or not 1 <= len(args["references"]) <= 12 or not isinstance(args.get("demo", False), bool):
            raise DressingError("Provide 1–12 references and an optional boolean demo flag.")
        refs, origins = [], set()
        for ref in args["references"]:
            if not isinstance(ref, dict) or set(ref) != {"title", "note", "source_url", "image_url"}:
                raise DressingError("Each reference needs title, note, source_url and image_url.")
            if any(not isinstance(v, str) or not v.strip() for v in ref.values()) or len(ref["title"]) > 200 or len(ref["note"]) > 1500:
                raise DressingError("Provide a title up to 200 characters and a note up to 1500 characters.")
            valid_url(ref["source_url"])
            canonical, origin, *_ = image_target(ref["image_url"])
            origins.add(origin)
            refs.append(dict(copy.deepcopy(ref), image_url=canonical, reference_id=secrets.token_urlsafe(16)))
        demo = args.get("demo", False)
        root = canvas = None
        if demo:
            groups = [{"id": "demo-casual", "label": "Casual"}, {"id": "demo-tailoring", "label": "Tailoring"}]
        else:
            vault = self.vault_factory()
            _, board = read_board(vault)
            groups = [{"id": n["id"], "label": n.get("label") or "Untitled group"} for n in board["nodes"] if n["type"] == "group"]
            root = str(vault.root)
            canvas = vault.locations.styleboard_canvas
            if not groups:
                raise DressingError("Create a destination group in your Styleboard first.")
        now = time.monotonic()
        self.sessions = {k: v for k, v in self.sessions.items() if now - v["created"] <= 86400}
        if len(self.sessions) >= 50:
            raise DressingError("Too many open galleries. Reload Dressing to start a new session.")
        gallery_id = secrets.token_urlsafe(24)
        self.sessions[gallery_id] = dict(references=refs, groups=groups, demo=demo, root=root, canvas=canvas, created=now, origins=sorted(origins))
        return dict(gallery_id=gallery_id, references=copy.deepcopy(refs), groups=groups, demo=demo, saved=False)

    def add(self, args):
        if set(args) != {"gallery_id", "reference_ids", "group_id"}:
            raise DressingError("Choose references and a destination group from the gallery.")
        session = self.sessions.get(args["gallery_id"])
        if session is None or time.monotonic() - session["created"] > 86400:
            raise DressingError("This gallery has expired. Ask Dressing to display it again.")
        selected = args["reference_ids"]
        known = {r["reference_id"]: r for r in session["references"]}
        if not isinstance(selected, list) or not selected or any(not isinstance(i, str) for i in selected) or len(set(selected)) != len(selected) or any(i not in known for i in selected):
            raise DressingError("Select one or more distinct references from this gallery.")
        if args["group_id"] not in {g["id"] for g in session["groups"]}:
            raise DressingError("Choose a destination group from this gallery.")
        if session["demo"]:
            return dict(status="demo_saved", demo=True, saved=False, selected_count=len(selected))
        vault = self.vault_factory()
        if str(vault.root) != session["root"] or vault.locations.styleboard_canvas != session["canvas"]:
            raise DressingError("The configured vault or Styleboard Canvas changed. Open a new gallery before adding references.")
        vault.writable()
        before, board = read_board(vault)
        group = next((n for n in board["nodes"] if n["id"] == args["group_id"] and n["type"] == "group"), None)
        if group is None:
            raise DressingError("The destination group was removed. Open a new gallery.")
        existing = {url_key(n.get("url")) for n in board["nodes"] if n["type"] == "link"}
        added, skipped = [], []
        for identity in selected:
            ref = copy.deepcopy(known[identity])
            if url_key(ref["source_url"]) in existing:
                skipped.append(identity)
                continue
            # Plan all geometry before downloading or writing any attachment.
            ref["file"] = "pending-image"
            picture = place_reference(board, group, ref)
            added.append((ref, picture))
            existing.add(url_key(ref["source_url"]))
        warnings = []
        for ref, picture in added:
            try:
                data = self.downloader(ref["image_url"])
                if len(data) > MAX_BYTES:
                    raise DressingError("Image exceeds 25 MiB.")
                image_extension(data)
            except (OSError, ValueError, DressingError) as error:
                picture.pop("file")
                picture.update(type="text", text="Image unavailable — use the source link below.")
                warnings.append({"reference_id": ref["reference_id"], "message": "Saved as a source link; image unavailable: " + str(error)})
                continue
            with tempfile.TemporaryDirectory(prefix="dressing-selected-image-") as tmp:
                path = Path(tmp) / "image"
                path.write_bytes(data)
                picture["file"] = attach_image(vault, path, "styleboard", apply=True)["file"]
        backup = None
        if added:
            backup = vault.write(vault.locations.styleboard_canvas, yaml_value(board, indent=2) + "\n", before)
            if json.loads(vault.read(vault.locations.styleboard_canvas)) != board:
                raise DressingError("Styleboard write could not be verified. Check the Canvas before retrying.")
        return dict(status="saved" if added else "already_present", saved=bool(added), canvas=vault.locations.styleboard_canvas,
                    group_id=group["id"], group_label=group.get("label", "Untitled group"),
                    added_ids=[r["reference_id"] for r, _ in added], skipped_ids=skipped,
                    warnings=warnings, backup=backup)
