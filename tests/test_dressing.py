import json
from pathlib import Path
import tempfile
import unittest
import sys

SCRIPT = Path(__file__).parents[1] / "plugins/dressing/scripts/dressing.py"
sys.path.insert(0, str(SCRIPT.parent))
import dressing as d


class FakeVault(d.Vault):
    """Exercise real file handling with a small in-memory CLI substitute."""
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.config = {}
        self.locations = d.Locations({})
        for folder in (d.INVENTORY, d.PREFERENCES, d.STYLEBOARD):
            (self.root / folder).mkdir(parents=True)

    def cli(self, command, *args):
        opts = dict(a.split("=", 1) for a in args if "=" in a)
        if command == "files":
            return "\n".join(p.relative_to(self.root).as_posix()
                             for p in self.path(opts["folder"]).rglob("*.md"))
        if command == "properties":
            text = self.read(opts["path"])
            if not text.startswith("---\n"):
                return "No frontmatter found."
            front = text.split("---\n", 2)[1]
            return json.dumps({k: json.loads(v) for k, v in (line.split(": ", 1) for line in front.splitlines())})
        if command == "create":
            path = self.path(opts["path"])
            if path.exists() and "overwrite" not in args:
                raise d.DressingError("Exists")
            # Simulate documented CLI literal newline/tab expansion.
            text = opts["content"].replace("\\n", "\n").replace("\\t", "\t")
            path.write_text(text)
            return "Created"
        raise AssertionError(command)

    def add(self, folder, name, props, body=""):
        path = folder + "/" + d.filename(name)
        self.path(path).write_text(d.note_content(props, body))
        return path


class DressingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vault = FakeVault(self.tmp.name)
        self.payload = {
            "name": "Example Garment - Variant A",
            "properties": {
                "clothing_brand": ["Example Brand"], "color": ["#112233"],
                "clothing_link": "https://example.com/garment",
                "feedback_rating": "yes",
                "feedback_comment": "Example feedback comment.",
            },
        }

    def owned(self, color="#112233", name="Example Garment - Variant A"):
        return self.vault.add(d.INVENTORY, name, {
            "base": "Inventory.base", "clothing_brand": ["Example Brand"],
            "color": [color], "clothing_link": "https://example.com/garment",
        })

    def test_owned_feedback_is_skipped(self):
        self.owned()
        result = d.save(self.vault, "feedback", self.payload, True)
        self.assertEqual(result["status"], "skipped_owned")
        self.assertEqual(self.vault.records(d.PREFERENCES, "Preferences.base"), [])

    def test_same_link_different_colour_is_not_owned(self):
        self.owned("#445566", "Example Garment - Variant B")
        self.assertEqual(d.save(self.vault, "feedback", self.payload, True)["status"], "created")

    def test_unknown_colour_shared_link_stops(self):
        self.owned()
        self.payload["name"] = "Example Garment"
        del self.payload["properties"]["color"]
        with self.assertRaisesRegex(d.DressingError, "Possible owned variant"):
            d.save(self.vault, "feedback", self.payload, True)

    def test_owned_model_at_another_retailer_is_skipped(self):
        self.owned()
        self.payload["properties"]["clothing_link"] = "https://retailer.example/different"
        self.assertEqual(d.save(self.vault, "feedback", self.payload, True)["status"], "skipped_owned")

    def test_exact_comment_roundtrip(self):
        comment = '  Fixture: "café" 🧪\nUnicode sample\twith a tab.\nLiteral \\n and \\t, C:\\notes\\test.  '
        self.payload["properties"]["feedback_comment"] = comment
        result = d.save(self.vault, "feedback", self.payload, True)
        actual = json.loads(self.vault.cli("properties", "path=" + result["path"]))
        self.assertEqual(actual["feedback_comment"], comment)

    def test_repeat_is_idempotent(self):
        first = d.save(self.vault, "feedback", self.payload, True)
        before = self.vault.read(first["path"])
        self.assertEqual(d.save(self.vault, "feedback", self.payload, True)["status"], "unchanged")
        self.assertEqual(self.vault.read(first["path"]), before)

    def test_feedback_update_keeps_metadata_and_body(self):
        first = d.save(self.vault, "feedback", self.payload, True)
        text = self.vault.read(first["path"]) + "\nExisting café fixture body to preserve.\n"
        self.vault.path(first["path"]).write_text(text)
        self.payload["properties"].update(feedback_rating="no", feedback_comment="Updated fixture comment.", price=999)
        result = d.save(self.vault, "feedback", self.payload, True)
        actual = json.loads(self.vault.cli("properties", "path=" + result["path"]))
        self.assertEqual(actual["feedback_comment"], "Updated fixture comment.")
        self.assertNotIn("price", actual)
        self.assertTrue(self.vault.read(result["path"]).endswith("\nExisting café fixture body to preserve.\n"))
        self.assertEqual(Path(result["backup"]).read_text(), text)
        Path(result["backup"]).unlink()
        Path(result["backup"]).parent.rmdir()

    def test_rating_only_keeps_old_comment(self):
        first = d.save(self.vault, "feedback", self.payload, True)
        del self.payload["properties"]["feedback_comment"]
        self.payload["properties"]["feedback_rating"] = "maybe"
        result = d.save(self.vault, "feedback", self.payload, True)
        actual = json.loads(self.vault.cli("properties", "path=" + first["path"]))
        self.assertEqual(actual["feedback_comment"], "Example feedback comment.")
        Path(result["backup"]).unlink()
        Path(result["backup"]).parent.rmdir()

    def test_import_conflict_preserves_note(self):
        first = d.save(self.vault, "feedback", self.payload, True)
        before = self.vault.read(first["path"])
        self.payload["properties"]["feedback_comment"] = "Different"
        with self.assertRaisesRegex(d.DressingError, "Import conflict"):
            d.save(self.vault, "feedback", self.payload, True, importing=True)
        self.assertEqual(self.vault.read(first["path"]), before)

    def test_source_dedup_by_host(self):
        d.save(self.vault, "source", {"name": "Shop", "properties": {"source_link": "https://www.example.com/shop/"}}, True)
        result = d.save(self.vault, "source", {"name": "Another name", "properties": {"source_link": "http://example.com/fr"}}, True)
        self.assertEqual(result["status"], "exists")
        self.assertEqual(len(self.vault.records(d.PREFERENCES, "Preferences.base")), 1)

    def test_removed_fields_and_wrong_types_rejected(self):
        for key, value in (("feedback_date", "2000-01-01"), ("feedback_context", "office"), ("feedback_criteria", ["fit"]), ("clothing_photo", "[[x.png]]"), ("clothing_brand", "Example Brand")):
            with self.subTest(key=key):
                data = json.loads(json.dumps(self.payload))
                data["properties"][key] = value
                with self.assertRaises(d.DressingError):
                    d.save(self.vault, "feedback", data, True)

    def test_preview_does_not_write(self):
        self.assertEqual(d.save(self.vault, "feedback", self.payload)["status"], "would_create")
        self.assertEqual(list(self.vault.path(d.PREFERENCES).iterdir()), [])

    def test_colour_variants_create_two_notes(self):
        d.save(self.vault, "feedback", self.payload, True)
        self.payload["name"] = "Example Garment - Variant B"
        self.payload["properties"]["color"] = ["#445566"]
        self.assertEqual(d.save(self.vault, "feedback", self.payload, True)["status"], "created")
        self.assertEqual(len(self.vault.records(d.PREFERENCES, "Preferences.base")), 2)

    def test_filename_collision_never_overwrites(self):
        first = d.save(self.vault, "feedback", self.payload, True)
        before = self.vault.read(first["path"])
        self.payload["properties"]["clothing_brand"] = ["Different Brand"]
        self.payload["properties"]["clothing_link"] = "https://other.example/item"
        with self.assertRaisesRegex(d.DressingError, "Filename collision"):
            d.save(self.vault, "feedback", self.payload, True)
        self.assertEqual(self.vault.read(first["path"]), before)

    def test_path_escape_and_readonly_fail(self):
        with self.assertRaises(d.DressingError):
            self.vault.path("../outside")
        self.vault.config["read_only"] = True
        with self.assertRaises(d.DressingError):
            d.save(self.vault, "feedback", self.payload, True)

    def test_concurrent_edit_is_preserved(self):
        path = self.vault.add(d.PREFERENCES, "Concurrent", {"base": "Preferences.base"})
        before = self.vault.read(path)
        self.vault.path(path).write_text(before + "User edit\n")
        with self.assertRaisesRegex(d.DressingError, "File changed"):
            self.vault.write(path, "replacement", before)
        self.assertTrue(self.vault.read(path).endswith("User edit\n"))

    def test_images_are_deduplicated_and_html_rejected(self):
        source = Path(self.tmp.name) / "download"
        source.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
        first = d.attach_image(self.vault, source, "styleboard", True)
        second = d.attach_image(self.vault, source, "styleboard", True)
        self.assertEqual(first["file"], second["file"])
        self.assertEqual(second["status"], "exists")
        source.write_text("<html>Access denied</html>")
        with self.assertRaises(d.DressingError):
            d.attach_image(self.vault, source, "styleboard", True)

    def test_canvas_preserves_layout_edges_and_deduplicates(self):
        board = {"nodes": [
            {"id": "g", "type": "group", "label": "Example Group", "x": 0, "y": 0, "width": 400, "height": 600},
            {"id": "n", "type": "text", "text": "Original", "x": 30, "y": 60, "width": 200, "height": 100},
        ], "edges": [{"id": "e", "fromNode": "g", "toNode": "n"}], "custom": {"keep": True}}
        self.vault.path(d.CANVAS).write_text(json.dumps(board))
        image = d.STYLEBOARD + "/reference.png"
        self.vault.path(image).write_bytes(b"\x89PNG\r\n\x1a\nfixture")
        data = {"file": image, "title": "Selected", "note": "Palette", "source_url": "https://example.com/ref", "group": "Example Group"}
        result = d.canvas_add(self.vault, data, True)
        actual = json.loads(self.vault.read(d.CANVAS))
        self.assertEqual(actual["nodes"][:2], board["nodes"])
        self.assertEqual(actual["edges"], board["edges"])
        self.assertEqual(actual["custom"], board["custom"])
        self.assertEqual(len(actual["nodes"]), 6)
        self.assertGreater(actual["nodes"][2]["x"], 400)
        self.assertEqual(d.canvas_add(self.vault, data, True)["status"], "exists")
        Path(result["backup"]).unlink()
        Path(result["backup"]).parent.rmdir()


if __name__ == "__main__":
    unittest.main()
