"""Exercise the actual stdio MCP exchange against an isolated fake vault."""
import copy
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest

from test_dressing import FakeVault, d


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/dressing/scripts"
VERSION = json.loads((SCRIPTS.parent / ".codex-plugin/plugin.json").read_text())["version"]

BOOT = """
import sys
sys.path[:0] = [sys.argv[1], sys.argv[2]]
import anyio
import socket
from unittest.mock import patch
from test_dressing import FakeVault
from feedback_server import build_server
from mcp.server.stdio import stdio_server
vault = FakeVault(sys.argv[3])
async def main():
    server = build_server(lambda: vault)
    # Keep the real URL validation, but avoid external DNS in fake-vault tests.
    with patch('public_images.socket.getaddrinfo', return_value=[
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))
    ]):
        async with stdio_server() as (r, w):
            await server.run(r, w, server.create_initialization_options())
anyio.run(main)
"""


class FeedbackServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vault = FakeVault(self.tmp.name)
        self.piece = {
            "name": "Test shirt - Navy",
            "properties": {
                "clothing_brand": ["Test Brand"],
                "clothing_link": "https://example.com/shirt",
                "color": ["#112233"],
                "price": 85,
            },
        }

    def start(self, forms=True, packaged=False):
        # FakeVault normally creates folders; reuse the parent's existing vault.
        boot = BOOT.replace(
            "vault = FakeVault(sys.argv[3])",
            "vault = FakeVault.__new__(FakeVault)\n"
            "from pathlib import Path\nfrom dressing_settings import Locations\n"
            "vault.root = Path(sys.argv[3]).resolve(); vault.config = {}; vault.locations = Locations({})",
        )
        command = [sys.executable, "-c", boot, str(SCRIPTS), str(ROOT / "tests"), self.tmp.name]
        cwd = None
        if packaged:
            plugin = ROOT / "plugins/dressing"
            config = json.loads((plugin / ".mcp.json").read_text())["mcpServers"]["Dressing"]
            # Match the installed host: cwd is relative to the plugin, while
            # arguments are passed literally. Never expand invented placeholders.
            cwd = plugin / config["cwd"]
            command = [config["command"], *config["args"]]
        self.proc = subprocess.Popen(
            command, cwd=cwd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        self.addCleanup(self.stop)
        self.messages = queue.Queue()
        self.reader = threading.Thread(
            target=lambda: [self.messages.put(line) for line in self.proc.stdout],
            daemon=True,
        )
        self.reader.start()
        self.send({
            "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {"elicitation": {"form": {}}} if forms else {},
                "clientInfo": {"name": "dressing-test", "version": "1"},
            },
        })
        reply = self.receive()
        self.assertEqual(reply["result"]["serverInfo"]["version"], VERSION)
        self.send({"method": "notifications/initialized"})

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            stream.close()

    def send(self, message):
        self.proc.stdin.write(json.dumps(dict(jsonrpc="2.0", **message)) + "\n")
        self.proc.stdin.flush()

    def receive(self):
        try:
            return json.loads(self.messages.get(timeout=120))
        except queue.Empty:
            self.fail("MCP response timed out")

    def request(self, piece=None):
        self.send({
            "id": 2, "method": "tools/call",
            "params": {"name": "request_feedback", "arguments": {"piece": piece or self.piece}},
        })
        return self.receive()

    def reply_form(self, request, action="accept", content=None):
        result = {"action": action}
        if content is not None:
            result["content"] = content
        self.send({"id": request["id"], "result": result})
        return self.receive()

    def answer(self, request, action="accept", content=None):
        rating = {k: v for k, v in (content or {}).items() if k == "feedback_rating"}
        reply = self.reply_form(request, action, rating)
        if reply.get("method") == "elicitation/create":
            self.comment_form = reply
            comment = {k: v for k, v in (content or {}).items() if k == "feedback_comment"}
            reply = self.reply_form(reply, action, comment)
        self.assertEqual(reply["id"], 2)
        return reply["result"]

    def records(self):
        return self.vault.records(d.PREFERENCES, "Preferences.base")

    def seed_feedback(self):
        payload = copy.deepcopy(self.piece)
        payload["properties"].update(feedback_rating="no", feedback_comment="Old comment")
        return d.save(self.vault, "feedback", payload, apply=True)

    def test_packaged_launch_with_host_path_resolution(self):
        self.start(packaged=True)
        self.send({"id": 2, "method": "tools/list"})
        tools = self.receive()["result"]["tools"]
        self.assertEqual({tool["name"] for tool in tools}, {
            "request_feedback", "feedback_status", "show_recommendations", "save_card_feedback",
            "show_styleboard_gallery", "add_styleboard_selection", "open_wardrobe", "refresh_wardrobe",
            "wardrobe_photo", "prepare_wardrobe_action", "settings_read", "settings_update",
        })

    def test_status_identifies_the_running_flow_without_forms_or_writes(self):
        self.start(forms=False)
        self.send({"id": 2, "method": "tools/call",
                   "params": {"name": "feedback_status", "arguments": {}}})
        status = self.receive()["result"]["structuredContent"]
        self.assertEqual(status["server_version"], VERSION)
        self.assertEqual(status["steps"], ["rating", "comment"])
        self.assertEqual(self.records(), [])

    def test_tool_catalog_exposes_no_model_supplied_vote(self):
        self.start()
        self.send({"id": 2, "method": "tools/list"})
        tool = self.receive()["result"]["tools"][0]
        props = tool["inputSchema"]["properties"]["piece"]["properties"]["properties"]
        self.assertNotIn("feedback_rating", props["properties"])
        self.assertFalse(tool["annotations"]["readOnlyHint"])

    def test_accept_preserves_exact_comment_and_rating(self):
        self.start()
        form = self.request()
        self.assertEqual(form["method"], "elicitation/create")
        fields = form["params"]["requestedSchema"]["properties"]
        self.assertEqual([x["title"] for x in fields["feedback_rating"]["oneOf"]],
                         ["Yes", "Maybe", "No"])
        self.assertNotIn("default", fields["feedback_rating"])
        self.assertEqual(self.records(), [])
        comment = '  Fixture café 🧪\nSecond fixture line.\tLiteral \\n and "quoted".  '
        result = self.answer(form, content={"feedback_rating": "maybe", "feedback_comment": comment})
        self.assertFalse(result.get("isError"))
        self.assertEqual(result["structuredContent"]["status"], "created")
        self.assertEqual(self.records()[0]["properties"]["feedback_comment"], comment)
        self.assertEqual(self.records()[0]["properties"]["feedback_rating"], "maybe")

    def test_rating_precedes_comment_and_cancelling_second_step_saves_nothing(self):
        original = self.seed_feedback()
        before = self.vault.read(original["path"])
        self.start()
        first = self.request()
        self.assertEqual(list(first["params"]["requestedSchema"]["properties"]), ["feedback_rating"])
        second = self.reply_form(first, content={"feedback_rating": "yes"})
        self.assertEqual(second["method"], "elicitation/create")
        self.assertEqual(list(second["params"]["requestedSchema"]["properties"]), ["feedback_comment"])
        self.assertEqual(self.vault.read(original["path"]), before)
        result = self.reply_form(second, action="cancel")
        self.assertFalse(result["result"]["structuredContent"]["saved"])
        self.assertEqual(self.vault.read(original["path"]), before)

    def test_cancel_does_not_write(self):
        self.start()
        result = self.answer(self.request(), action="cancel")
        self.assertEqual(result["structuredContent"], {"status": "cancel", "saved": False, "server_version": VERSION})
        self.assertEqual(self.records(), [])

    def test_decline_is_not_a_no_vote(self):
        self.start()
        result = self.answer(self.request(), action="decline")
        self.assertEqual(result["structuredContent"]["saved"], False)
        self.assertEqual(self.records(), [])

    def test_invalid_vote_never_saves(self):
        self.start()
        result = self.answer(self.request(), content={"feedback_rating": "love"})
        self.assertTrue(result["isError"])
        self.assertEqual(self.records(), [])

    def test_missing_vote_never_defaults(self):
        self.start()
        result = self.answer(self.request(), content={"feedback_comment": "A comment"})
        self.assertTrue(result["isError"])
        self.assertEqual(self.records(), [])

    def test_existing_feedback_prefilled_and_updated_without_duplicate(self):
        original = self.seed_feedback()
        self.vault.path(original["path"]).write_text(self.vault.read(original["path"]) + "\nKeep my note.\n")
        self.start()
        form = self.request()
        result = self.answer(form, content={"feedback_rating": "yes", "feedback_comment": ""})
        self.assertEqual(self.comment_form["params"]["requestedSchema"]["properties"]["feedback_comment"]["default"],
                         "Old comment")
        self.assertEqual(result["structuredContent"]["status"], "updated")
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(self.records()[0]["properties"]["feedback_comment"], "")
        self.assertTrue(self.vault.read(original["path"]).endswith("\nKeep my note.\n"))

    def test_omitted_comment_keeps_existing(self):
        self.seed_feedback()
        self.start()
        self.answer(self.request(), content={"feedback_rating": "yes"})
        self.assertEqual(self.records()[0]["properties"]["feedback_comment"], "Old comment")

    def test_owned_piece_does_not_open_form(self):
        self.vault.add(d.INVENTORY, self.piece["name"],
                       dict(self.piece["properties"], base="Inventory.base"))
        self.start()
        reply = self.request()
        self.assertEqual(reply["result"]["structuredContent"]["status"], "skipped_owned")
        self.assertEqual(self.records(), [])

    def test_ownership_checked_again_after_form(self):
        self.start()
        form = self.request()
        self.vault.add(d.INVENTORY, self.piece["name"],
                       dict(self.piece["properties"], base="Inventory.base"))
        result = self.answer(form, content={"feedback_rating": "yes"})
        self.assertEqual(result["structuredContent"]["status"], "skipped_owned")
        self.assertEqual(self.records(), [])

    def test_unavailable_form_does_not_write(self):
        self.start(forms=False)
        reply = self.request()
        self.assertEqual(reply["result"]["structuredContent"]["status"], "form_unavailable")
        self.assertEqual(self.records(), [])

    def test_model_cannot_inject_rating(self):
        self.start()
        self.piece["properties"]["feedback_rating"] = "yes"
        reply = self.request()
        self.assertTrue(reply["result"]["isError"])
        self.assertEqual(self.records(), [])

    def call(self, name, arguments):
        self.send({"id": 8, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
        return self.receive()["result"]

    def show(self, demo=False, image_url="https://cdn.shopify.com/test.jpg"):
        return self.call("show_recommendations", {"cards": [{
            "piece": self.piece, "image_url": image_url, "advice": "Test advice",
        }], "demo": demo})

    def test_card_demo_never_writes(self):
        self.start(forms=False)
        card = self.show(demo=True)["structuredContent"]["cards"][0]
        self.assertEqual(self.records(), [])
        result = self.call("save_card_feedback", {"card_id": card["card_id"],
            "feedback_rating": "yes", "feedback_comment": "Test only"})["structuredContent"]
        self.assertEqual(result["status"], "demo_saved")
        self.assertFalse(result["saved"])
        self.assertEqual(self.records(), [])

    def test_card_exact_comment_and_repeat_do_not_duplicate(self):
        self.start(forms=False)
        card = self.show()["structuredContent"]["cards"][0]
        self.assertEqual(self.records(), [])
        comment = '  Fixture café…\nQuoted value: "sample". Literal \\n  '
        args = {"card_id": card["card_id"], "feedback_rating": "maybe", "feedback_comment": comment}
        self.assertTrue(self.call("save_card_feedback", args)["structuredContent"]["saved"])
        self.assertEqual(self.call("save_card_feedback", args)["structuredContent"]["status"], "unchanged")
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(self.records()[0]["properties"]["feedback_comment"], comment)

    def test_card_existing_comment_prefilled_and_owned_checked_again(self):
        self.seed_feedback()
        self.start(forms=False)
        card = self.show()["structuredContent"]["cards"][0]
        self.assertEqual(card["previous_comment"], "Old comment")
        self.vault.add(d.INVENTORY, self.piece["name"], dict(self.piece["properties"], base="Inventory.base"))
        result = self.call("save_card_feedback", {"card_id": card["card_id"],
            "feedback_rating": "yes"})["structuredContent"]
        self.assertEqual(result["status"], "skipped_owned")
        self.assertEqual(self.records()[0]["properties"]["feedback_rating"], "no")
        self.assertEqual(self.show()["structuredContent"]["cards"], [])

    def test_card_rejects_unknown_id_and_private_image(self):
        self.start(forms=False)
        self.assertTrue(self.call("save_card_feedback", {"card_id": "invented", "feedback_rating": "yes"})["isError"])
        self.assertTrue(self.show(image_url="https://127.0.0.1/image.jpg")["isError"])
        self.assertEqual(self.records(), [])

    def test_resource_and_app_only_action_are_discoverable(self):
        self.start(forms=False)
        self.send({"id": 2, "method": "tools/list"})
        catalog = {t["name"]: t for t in self.receive()["result"]["tools"]}
        self.assertEqual(catalog["save_card_feedback"]["_meta"]["ui"]["visibility"], ["app"])
        # Each selection gets its own resource and exact image-origin CSP.
        self.assertNotIn("ui", catalog["show_recommendations"].get("_meta", {}))
        uri = self.show(demo=True)["_meta"]["ui"]["resourceUri"]
        self.send({"id": 3, "method": "resources/read", "params": {"uri": uri}})
        resource = self.receive()["result"]["contents"][0]
        self.assertEqual(resource["mimeType"], "text/html;profile=mcp-app")
        self.assertIn("https://cdn.shopify.com", resource["_meta"]["ui"]["csp"]["resourceDomains"])
        self.assertIn("ui/initialize", resource["text"])


if __name__ == "__main__":
    unittest.main()
