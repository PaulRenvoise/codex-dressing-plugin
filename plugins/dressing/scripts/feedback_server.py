#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp==2.3.0", "pillow==12.3.0"]
# ///
"""Native MCP feedback forms, saved through Dressing's existing vault helper."""
import copy
import json
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

import anyio
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from wardrobe import Wardrobe, UI_URI as WARDROBE_URI
from styleboard_gallery import Gallery, UI_URI as GALLERY_URI
from public_images import image_target

from dressing import CLOTHING, LIST_FIELDS, MEASURES, DressingError, Vault, save
from dressing_settings import CAPABILITY, FIELDS, read_settings, update_settings


def piece_schema():
    properties = {}
    for field in sorted(CLOTHING):
        if field in LIST_FIELDS:
            properties[field] = {
                "type": "array", "items": {"type": "string", "minLength": 1},
                "minItems": 1,
            }
        elif field in MEASURES | {"price"}:
            properties[field] = {"type": "number", "minimum": 0}
        else:
            properties[field] = {"type": "string"}
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "properties": {
                "type": "object", "properties": properties,
                "required": ["clothing_link", "clothing_brand"],
                "additionalProperties": False,
            },
        },
        "required": ["name", "properties"],
        "additionalProperties": False,
    }


INPUT_SCHEMA = {
    "type": "object",
    "properties": {"piece": piece_schema()},
    "required": ["piece"],
    "additionalProperties": False,
}

TOOL = types.Tool(
    name="request_feedback",
    title="Give Dressing feedback — rating first",
    description=(
        "Ask for the rating FIRST in a native form, then ask for an optional comment in a SECOND native form for one "
        "specific clothing piece. Accepting saves the user's exact response in "
        "Obsidian Preferences. Cancel/decline saves nothing. Excludes owned pieces "
        "and updates existing feedback without duplicates. Pass verified piece "
        "metadata only: never supply the assistant's verdict or a guessed comment. "
        "Present the product and your advice in chat before opening the form."
    ),
    input_schema=INPUT_SCHEMA,
    annotations=types.ToolAnnotations(
        read_only_hint=False, destructive_hint=False,
        idempotent_hint=False, open_world_hint=False,
    ),
)


VERSION = "1.8.0"
UI_URI = "ui://dressing/recommendations-v2"
CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "piece": piece_schema(),
        "image_url": {"type": "string", "format": "uri"},
        "advice": {"type": "string", "maxLength": 3000},
    },
    "required": ["piece", "image_url", "advice"], "additionalProperties": False,
}
SHOW_TOOL = types.Tool(
    name="show_recommendations", title="Dressing — recommendations",
    description="Show 1–5 verified pieces as interactive cards with photos, Yes/Maybe/No and an optional comment. "
                "No feedback is written until the user clicks Save in the card. For a UI test set demo=true: "
                "even clicking Save then writes nothing to Obsidian. Use verified direct public HTTPS image URLs. "
                "Never pass an assistant verdict as user feedback.",
    input_schema={"type": "object", "properties": {
        "cards": {"type": "array", "items": CARD_SCHEMA, "minItems": 1, "maxItems": 5},
        "demo": {"type": "boolean", "default": False},
    }, "required": ["cards"], "additionalProperties": False},
    annotations=types.ToolAnnotations(read_only_hint=True, destructive_hint=False,
                                     idempotent_hint=False, open_world_hint=True),
    _meta={"openai/widgetAccessible": True},
)
SAVE_TOOL = types.Tool(
    name="save_card_feedback", title="Save my Dressing feedback",
    description="UI-only: save the user's explicit choice for a previously displayed card. Never call on behalf of the user.",
    input_schema={"type": "object", "properties": {
        "card_id": {"type": "string"},
        "feedback_rating": {"type": "string", "enum": ["yes", "maybe", "no"]},
        "feedback_comment": {"type": "string", "maxLength": 20000},
    }, "required": ["card_id", "feedback_rating"], "additionalProperties": False},
    annotations=types.ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                     idempotent_hint=True, open_world_hint=False),
    _meta={"ui": {"visibility": ["app"]}, "openai/visibility": "private",
           "openai/widgetAccessible": True},
)
STATUS_TOOL = types.Tool(
    name="feedback_status",
    title="Check Dressing feedback version",
    description="Read the running feedback server version and step order without opening a form or accessing Obsidian.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    annotations=types.ToolAnnotations(read_only_hint=True, destructive_hint=False,
                                     idempotent_hint=True, open_world_hint=False),
)


GALLERY_TOOL = types.Tool(
    name="show_styleboard_gallery", title="Dressing — Styleboard gallery",
    description="Show 1–12 verified visual references for the user to select, with live Canvas destination groups. "
                "Only the user may submit selections using Add selected. Showing the gallery writes nothing. "
                "Provide original direct public HTTPS image URLs. "
                "Use demo=true for a test that never accesses Obsidian.",
    input_schema={"type": "object", "properties": {
        "references": {"type": "array", "minItems": 1, "maxItems": 12, "items": {
            "type": "object", "properties": {
                "title": {"type": "string", "minLength": 1, "maxLength": 200},
                "note": {"type": "string", "minLength": 1, "maxLength": 1500},
                "source_url": {"type": "string", "format": "uri"},
                "image_url": {"type": "string", "format": "uri"},
            }, "required": ["title", "note", "source_url", "image_url"], "additionalProperties": False}},
        "demo": {"type": "boolean", "default": False},
    }, "required": ["references"], "additionalProperties": False},
    annotations=types.ToolAnnotations(read_only_hint=True, destructive_hint=False,
                                     idempotent_hint=False, open_world_hint=True),
    _meta={"openai/widgetAccessible": True},
)
ADD_GALLERY_TOOL = types.Tool(
    name="add_styleboard_selection", title="Add selected references to Styleboard",
    description="UI-only: save the user's explicitly selected gallery references in their chosen Canvas group. "
                "Never call on the user's behalf. Downloads only selected images; unavailable images become source links.",
    input_schema={"type": "object", "properties": {
        "gallery_id": {"type": "string"},
        "reference_ids": {"type": "array", "minItems": 1, "maxItems": 12, "uniqueItems": True, "items": {"type": "string"}},
        "group_id": {"type": "string"},
    }, "required": ["gallery_id", "reference_ids", "group_id"], "additionalProperties": False},
    annotations=types.ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                     idempotent_hint=True, open_world_hint=True),
    _meta={"ui": {"visibility": ["app"]}, "openai/visibility": "private", "openai/widgetAccessible": True},
)
READ_ONLY = types.ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
APP_ONLY = {"ui": {"visibility": ["app"]}, "openai/visibility": "private", "openai/widgetAccessible": True}
EMPTY_SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}
WARDROBE_TOOL = types.Tool(
    name="open_wardrobe", title="Dressing wardrobe",
    description="Open the searchable wardrobe gallery from live Obsidian Inventory. Users can select owned garments "
                "and ask for outfits, comparisons or advice. Read-only; selection never saves preferences. "
                "Also available from the global sidebar and as a Dressing conversation side-panel entrypoint.",
    input_schema=EMPTY_SCHEMA, annotations=READ_ONLY,
    _meta={"ui": {"resourceUri": WARDROBE_URI}, "openai/outputTemplate": WARDROBE_URI,
           "openai/widgetAccessible": True, "openai/ui": {"entrypoints": [{"type": "global"}, {"type": "thread"}]}},
)
REFRESH_WARDROBE_TOOL = types.Tool(
    name="refresh_wardrobe", title="Refresh wardrobe from Obsidian",
    description="UI-only: reload the current Inventory for the wardrobe panel. No writes.",
    input_schema=EMPTY_SCHEMA, annotations=READ_ONLY, _meta=APP_ONLY,
)
WARDROBE_PHOTO_TOOL = types.Tool(
    name="wardrobe_photo", title="Load garment thumbnail",
    description="UI-only: read a thumbnail of the selected Inventory garment's local vault photo. No remote requests or vault writes.",
    input_schema={"type": "object", "properties": {
        "session_id": {"type": "string"}, "garment_id": {"type": "string"},
    }, "required": ["session_id", "garment_id"], "additionalProperties": False},
    annotations=READ_ONLY, _meta=APP_ONLY,
)
WARDROBE_ACTION_TOOL = types.Tool(
    name="prepare_wardrobe_action", title="Prepare a wardrobe conversation request",
    description="UI-only: re-read the selected Inventory garments and prepare the user's outfit, comparison or advice request. "
                "Does not send a message or write records; the UI sends it only after the user's explicit action.",
    input_schema={"type": "object", "properties": {
        "session_id": {"type": "string"},
        "garment_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 12, "uniqueItems": True},
        "action": {"type": "string", "enum": ["outfit", "compare", "advice"]},
        "brief": {"type": "string", "maxLength": 2000},
    }, "required": ["session_id", "garment_ids", "action"], "additionalProperties": False},
    annotations=READ_ONLY, _meta=APP_ONLY,
)
SETTINGS_READ_TOOL = types.Tool(
    name="settings_read", title="Read Dressing settings",
    description="Read the three configured Obsidian file locations and their native settings schema.",
    input_schema=EMPTY_SCHEMA, annotations=READ_ONLY,
    output_schema={"type": "object", "properties": {
        "schema": {"type": "object"}, "values": {"type": "object"},
        "layout": {"type": "array", "items": {"type": "object"}},
    }, "required": ["schema", "values"]},
)
SETTINGS_UPDATE_TOOL = types.Tool(
    name="settings_update", title="Update Dressing settings",
    description="Update selected Obsidian file locations. Paths must exist in the configured vault. "
                "Persists plugin settings only; does not move or edit vault files.",
    input_schema={"type": "object", "properties": {"set": {
        "type": "object", "properties": FIELDS, "additionalProperties": False,
    }}, "required": ["set"], "additionalProperties": False},
    output_schema={"type": "object", "properties": {"values": {"type": "object"}}, "required": ["values"]},
    annotations=types.ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False),
)
TOOLS = [TOOL, STATUS_TOOL, SHOW_TOOL, SAVE_TOOL, GALLERY_TOOL, ADD_GALLERY_TOOL,
         WARDROBE_TOOL, REFRESH_WARDROBE_TOOL, WARDROBE_PHOTO_TOOL, WARDROBE_ACTION_TOOL, SETTINGS_READ_TOOL, SETTINGS_UPDATE_TOOL]


def form_schema(previous_comment=None):
    comment = {
        "type": "string",
        "title": "Comment (optional)",
        "description": "Saved exactly as written. You can leave this empty.",
    }
    if previous_comment is not None:
        comment["default"] = previous_comment
        comment["description"] = (
            "Your existing comment is shown. Edit it, or clear it to remove it. "
            "Saved exactly as written."
        )
    return {
        "type": "object",
        "properties": {
            "feedback_rating": {
                "type": "string",
                "title": "Your opinion",
                "oneOf": [
                    {"const": "yes", "title": "Yes"},
                    {"const": "maybe", "title": "Maybe"},
                    {"const": "no", "title": "No"},
                ],
            },
            "feedback_comment": comment,
        },
        "required": ["feedback_rating"],
    }


def validate_piece(piece):
    if not isinstance(piece, dict) or set(piece) != {"name", "properties"}:
        raise DressingError("Provide a piece with name and properties.")
    props = piece["properties"]
    if not isinstance(props, dict) or set(props) - CLOTHING:
        raise DressingError("Pass clothing metadata only; the user supplies the feedback.")
    if not props.get("clothing_link") or not props.get("clothing_brand"):
        raise DressingError("A verified product link and brand are required.")
    payload = copy.deepcopy(piece)
    # This value is used only to run the existing read-only validation/dedup path.
    # It is never displayed, persisted, or used if the user omits their rating.
    payload["properties"]["feedback_rating"] = "maybe"
    return payload


def prepare(vault, piece):
    payload = validate_piece(piece)
    vault.writable()
    preview = save(vault, "feedback", payload)
    previous_comment = None
    if preview["status"] in {"would_update", "unchanged"}:
        props = json.loads(vault.cli(
            "properties", "path=" + preview["path"], "format=json",
        ))
        previous_comment = props.get("feedback_comment")
    return preview, form_schema(previous_comment)


def apply_response(vault, piece, response):
    if response.action != "accept":
        return {"status": response.action, "saved": False}
    content = response.content
    if not isinstance(content, dict) or set(content) - {"feedback_rating", "feedback_comment"}:
        raise DressingError("Invalid feedback response; nothing was saved.")
    if content.get("feedback_rating") not in {"yes", "maybe", "no"}:
        raise DressingError("Choose Yes, Maybe or No; nothing was saved.")
    if "feedback_comment" in content and not isinstance(content["feedback_comment"], str):
        raise DressingError("The comment must be text; nothing was saved.")
    payload = copy.deepcopy(piece)
    payload["properties"].update(content)
    # Re-read ownership and existing feedback after the user submits.
    result = save(vault, "feedback", payload, apply=True)
    result["saved"] = result["status"] in {"created", "updated", "unchanged"}
    return result


def tool_result(data, error=False, meta=None):
    data = dict(data, server_version=VERSION)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(data, ensure_ascii=False))],
        structured_content=data,
        is_error=error,
        _meta=meta,
    )


def feedback_destination(vault):
    return vault.locations.identity(vault, "inventory_base", "preferences_base")


def check_feedback_destination(vault, expected):
    if feedback_destination(vault) != expected:
        raise DressingError("The configured vault or Base changed. Display this piece again before saving feedback.")


class DressingServer(Server):
    def get_capabilities(self, *args, **kwargs):
        capabilities = super().get_capabilities(*args, **kwargs)
        # Legacy initialize and modern server/discover both expose native settings.
        capabilities.experimental = dict(capabilities.experimental or {}, **CAPABILITY)
        capabilities.extensions = dict(capabilities.extensions or {}, **CAPABILITY)
        return capabilities


def build_server(vault_factory=Vault):
    # Serialize this server's reads/writes, but don't hold the lock while a form is open.
    vault_lock = anyio.Lock()
    cards = {}
    gallery = Gallery(vault_factory)
    wardrobe = Wardrobe(vault_factory)

    resources = {
        WARDROBE_URI: ("Dressing wardrobe", "wardrobe.html", [], None),
    }

    def expire_resources():
        now = time.monotonic()
        for uri, (_, _, _, created) in list(resources.items()):
            if created is not None and now - created > 86400:
                del resources[uri]

    def selection_resource(prefix, name, filename, origins):
        expire_resources()
        if len(resources) >= 551:
            raise DressingError("Too many open selections. Reload Dressing to start a new session.")
        uri = prefix + "/" + secrets.token_urlsafe(24) + ".html"
        resources[uri] = (name, filename, sorted(set(origins)), time.monotonic())
        # The host caches by URI. Bind after the selection is known, and never
        # declare a shared template on these tools: it would override this URI.
        return {"ui": {"resourceUri": uri}, "openai/outputTemplate": uri}

    async def list_resources(ctx, params):
        expire_resources()
        return types.ListResourcesResult(resources=[types.Resource(
            uri=uri, name=name, mime_type="text/html;profile=mcp-app",
        ) for uri, (name, _, _, _) in resources.items()])

    async def read_resource(ctx, params):
        expire_resources()
        uri = str(params.uri)
        if uri not in resources:
            raise ValueError("Unknown or expired Dressing UI resource")
        _, filename, origins, _ = resources[uri]
        return types.ReadResourceResult(contents=[types.TextResourceContents(
            uri=uri, mime_type="text/html;profile=mcp-app",
            text=(Path(__file__).parent.parent / "ui" / filename).read_text(),
            _meta={"ui": {"prefersBorder": True, "csp": {
                "connectDomains": [], "resourceDomains": origins,
            }}, "openai/widgetCSP": {"connect_domains": [], "resource_domains": origins}},
        )])

    async def show_cards(args):
        if set(args) - {"cards", "demo"} or not isinstance(args.get("cards"), list):
            raise DressingError("Expected cards and optional demo flag.")
        if not 1 <= len(args["cards"]) <= 5 or not isinstance(args.get("demo", False), bool):
            raise DressingError("Choose 1–5 cards and a boolean demo flag.")
        # Expired UI actions must not silently save a different recommendation.
        now = time.monotonic()
        for key in list(cards):
            if now - cards[key]["created"] > 86400:
                del cards[key]
        if len(cards) + len(args["cards"]) > 500:
            raise DressingError("Too many open cards. Reload Dressing to start a new session.")
        output, pending, origins = [], {}, set()
        demo = args.get("demo", False)
        vault = None if demo else vault_factory()
        for item in args["cards"]:
            if not isinstance(item, dict) or set(item) != {"piece", "image_url", "advice"}:
                raise DressingError("Each card needs piece, image_url and advice.")
            validate_piece(item["piece"])
            image_url = item["image_url"]
            if not isinstance(image_url, str) or not isinstance(item["advice"], str):
                raise DressingError("Image URL and advice must be text.")
            canonical, origin, *_ = await anyio.to_thread.run_sync(image_target, image_url)
            link = urlsplit(item["piece"]["properties"]["clothing_link"])
            if link.scheme != "https" or not link.hostname or link.username or link.password:
                raise DressingError("The product link must be HTTPS.")
            previous_comment = ""
            if not demo:
                preview, schema = await anyio.to_thread.run_sync(prepare, vault, item["piece"])
                if preview["status"] == "skipped_owned":
                    continue
                previous_comment = schema["properties"]["feedback_comment"].get("default", "")
            card_id = secrets.token_urlsafe(24)
            pending[card_id] = {"piece": copy.deepcopy(item["piece"]), "demo": demo, "created": now,
                                "destination": None if demo else feedback_destination(vault)}
            origins.add(origin)
            output.append(dict(copy.deepcopy(item), image_url=canonical, card_id=card_id, previous_comment=previous_comment))
        meta = selection_resource(UI_URI, "Dressing recommendations", "recommendations.html", origins)
        cards.update(pending)
        return tool_result({"cards": output, "demo": demo, "saved": False}, meta=meta)

    async def save_card(args):
        if set(args) - {"card_id", "feedback_rating", "feedback_comment"}:
            raise DressingError("Invalid feedback fields.")
        card = cards.get(args.get("card_id"))
        if card is None or time.monotonic() - card["created"] > 86400:
            raise DressingError("This card has expired. Ask Dressing to display it again.")
        content = {k: v for k, v in args.items() if k != "card_id"}
        if content.get("feedback_rating") not in {"yes", "maybe", "no"}:
            raise DressingError("Choose Yes, Maybe or No before saving.")
        if "feedback_comment" in content and not isinstance(content["feedback_comment"], str):
            raise DressingError("The comment must be text.")
        if card["demo"]:
            return tool_result({"status": "demo_saved", "saved": False, "demo": True})
        vault = vault_factory()
        check_feedback_destination(vault, card["destination"])
        result = await anyio.to_thread.run_sync(
            apply_response, vault, card["piece"], types.ElicitResult(action="accept", content=content),
        )
        return tool_result(result)

    async def list_tools(ctx, params):
        return types.ListToolsResult(tools=TOOLS)

    async def call_tool(ctx, params):
        if params.name in {SETTINGS_READ_TOOL.name, SETTINGS_UPDATE_TOOL.name}:
            try:
                async with vault_lock:
                    args = params.arguments or {}
                    if params.name == SETTINGS_READ_TOOL.name:
                        if args:
                            raise DressingError("Read settings without arguments.")
                        return tool_result(await anyio.to_thread.run_sync(read_settings))
                    if set(args) != {"set"}:
                        raise DressingError("Provide only the settings to change in set.")
                    return tool_result(await anyio.to_thread.run_sync(update_settings, args["set"], vault_factory()))
            except (DressingError, OSError, ValueError, TypeError) as error:
                return tool_result({"error": str(error)}, error=True)
        if params.name == STATUS_TOOL.name:
            return tool_result({"steps": ["rating", "comment"], "save_after": "comment",
                                "connection": "Dressing", "cards": True,
                                "image_policy": "public_https", "selection_scoped_csp": True,
                                "styleboard_gallery": True, "gallery_resource": GALLERY_URI,
                                "wardrobe_panel": True, "wardrobe_resource": WARDROBE_URI})
        if params.name in {WARDROBE_TOOL.name, REFRESH_WARDROBE_TOOL.name, WARDROBE_PHOTO_TOOL.name, WARDROBE_ACTION_TOOL.name}:
            try:
                async with vault_lock:
                    args = params.arguments or {}
                    if params.name in {WARDROBE_TOOL.name, REFRESH_WARDROBE_TOOL.name}:
                        data = await anyio.to_thread.run_sync(wardrobe.show, args)
                        return types.CallToolResult(
                            content=[types.TextContent(type="text", text=f"Wardrobe loaded: {data['total']} garments from Obsidian Inventory.")],
                            structured_content={"total": data["total"], "source": data["source"], "read_only": True, "server_version": VERSION},
                            _meta={"wardrobe": data},
                        )
                    if params.name == WARDROBE_PHOTO_TOOL.name:
                        result, meta = await anyio.to_thread.run_sync(wardrobe.photo, args)
                        return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(result))],
                                                    structured_content=result, _meta=meta)
                    return tool_result(await anyio.to_thread.run_sync(wardrobe.prepare, args))
            except (DressingError, OSError, ValueError, KeyError, TypeError) as error:
                return tool_result({"error": str(error), "saved": False}, error=True)
        if params.name in {GALLERY_TOOL.name, ADD_GALLERY_TOOL.name}:
            try:
                async with vault_lock:
                    action = gallery.show if params.name == GALLERY_TOOL.name else gallery.add
                    data = await anyio.to_thread.run_sync(action, params.arguments or {})
                    meta = None
                    if params.name == GALLERY_TOOL.name:
                        origins = gallery.sessions[data["gallery_id"]]["origins"]
                        meta = selection_resource(GALLERY_URI, "Dressing Styleboard gallery", "styleboard-gallery.html", origins)
                    return tool_result(data, meta=meta)
            except (DressingError, OSError, ValueError, KeyError, TypeError) as error:
                return tool_result({"error": str(error), "saved": False,
                                    "message": "No Canvas save was confirmed. Check the Styleboard before retrying; downloaded attachments may remain."}, error=True)
        if params.name in {SHOW_TOOL.name, SAVE_TOOL.name}:
            try:
                async with vault_lock:
                    return await (show_cards(params.arguments or {}) if params.name == SHOW_TOOL.name
                                  else save_card(params.arguments or {}))
            except (DressingError, OSError, ValueError, KeyError, TypeError) as error:
                return tool_result({"error": str(error), "saved": False}, error=True)
        if params.name != TOOL.name:
            return tool_result({"error": "Unknown Dressing tool."}, error=True)
        args = params.arguments or {}
        if set(args) != {"piece"}:
            return tool_result({"error": "Expected only a piece argument."}, error=True)
        capability = types.ClientCapabilities(
            elicitation=types.ElicitationCapability(form=types.FormElicitationCapability()),
        )
        if not ctx.session.check_client_capability(capability):
            return tool_result({
                "status": "form_unavailable", "saved": False,
                "message": "This client does not support native forms. Ask for the "
                           "user's rating and comment in chat, then use the existing "
                           "Dressing save workflow. Do not infer their response.",
            })
        try:
            piece = args["piece"]
            async with vault_lock:
                vault = vault_factory()
                destination = feedback_destination(vault)
                preview, schema = await anyio.to_thread.run_sync(prepare, vault, piece)
            if preview["status"] == "skipped_owned":
                return tool_result(dict(preview, saved=False))
            rating_response = await ctx.session.elicit_form(
                message=(
                    f"Step 1 of 2 — Your opinion on {piece['name']}\n"
                    f"{piece['properties']['clothing_link']}\n\n"
                    "Choose your rating. Next you can add an optional comment. "
                    "Nothing is saved until you submit step 2."
                ),
                requested_schema={
                    "type": "object",
                    "properties": {"feedback_rating": schema["properties"]["feedback_rating"]},
                    "required": ["feedback_rating"],
                },
                related_request_id=ctx.request_id,
            )
            if rating_response.action != "accept":
                return tool_result({"status": rating_response.action, "saved": False})
            rating = rating_response.content
            if (not isinstance(rating, dict) or set(rating) != {"feedback_rating"}
                    or rating["feedback_rating"] not in {"yes", "maybe", "no"}):
                raise DressingError("Choose Yes, Maybe or No; nothing was saved.")
            comment_response = await ctx.session.elicit_form(
                message=(
                    f"Step 2 of 2 — Comment on {piece['name']}\n"
                    f"Your rating: {rating['feedback_rating'].title()}\n\n"
                    "Add an optional comment, then submit to save your feedback "
                    "in Obsidian Preferences. Cancel to discard both steps."
                ),
                requested_schema={
                    "type": "object",
                    "properties": {"feedback_comment": schema["properties"]["feedback_comment"]},
                },
                related_request_id=ctx.request_id,
            )
            if comment_response.action != "accept":
                return tool_result({"status": comment_response.action, "saved": False})
            comment = comment_response.content
            if comment is None:
                comment = {}
            if not isinstance(comment, dict) or set(comment) - {"feedback_comment"}:
                raise DressingError("Invalid comment response; nothing was saved.")
            response = types.ElicitResult(action="accept", content={**rating, **comment})
            async with vault_lock:
                vault = vault_factory()
                check_feedback_destination(vault, destination)
                result = await anyio.to_thread.run_sync(apply_response, vault, piece, response)
            return tool_result(result)
        except (DressingError, OSError, ValueError, KeyError) as error:
            return tool_result({"error": str(error)}, error=True)

    return DressingServer(
        "Dressing", version=VERSION,
        instructions="Use open_wardrobe to browse owned garments in the Dressing panel. "
                     "Present recommendations with show_recommendations. Only the user may submit card feedback. "
                     "Use show_styleboard_gallery for visual references; only the user may submit gallery selections. "
                     "Use request_feedback as a native form fallback. "
                     "Never use the stylist's verdict as the user's preference.",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        on_list_resources=list_resources,
        on_read_resource=read_resource,
        get_tool_input_schema=lambda name: next((t.input_schema for t in
            TOOLS if t.name == name), None),
    )


async def main():
    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(main)
