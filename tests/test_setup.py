"""Check installation and configuration without changing the user's Codex setup."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dressing_setup", ROOT / "setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.enterContext(redirect_stdout(self.output))
        self.enterContext(redirect_stderr(self.output))
        self.values = {"inventory_base": "Wardrobe/Owned.base"}
        self.read = self.enterContext(patch("dressing_settings.read_values", return_value=self.values))
        self.update = self.enterContext(patch("dressing_settings.update_settings",
                                             return_value={"values": self.values}))
        self.vault = self.enterContext(patch("dressing.Vault"))
        self.resolve = self.enterContext(patch("plugin_dependency.obsidian_wrapper"))
        self.enterContext(patch.object(setup.shutil, "which", side_effect=lambda name: "/bin/" + name))
        self.run = self.enterContext(patch.object(setup.subprocess, "run"))

    def test_show_locations_does_not_connect_or_install(self):
        setup.main([])
        self.assertIn("Wardrobe/Owned.base", self.output.getvalue())
        self.vault.assert_not_called()
        self.resolve.assert_not_called()
        self.update.assert_not_called()
        self.run.assert_not_called()

    def test_check_does_not_install_or_write(self):
        setup.main(["--check"])
        self.resolve.assert_called_once()
        self.update.assert_not_called()
        self.run.assert_not_called()

    def test_install_uses_this_checkout_and_marketplace_identity(self):
        setup.main(["--install"])
        self.assertEqual([call.args[0] for call in self.run.call_args_list], [
            ["codex", "plugin", "marketplace", "add", str(ROOT)],
            ["codex", "plugin", "add", "dressing@codex-dressing-plugin"],
        ])
        self.assertTrue(all(call.kwargs["check"] for call in self.run.call_args_list))
        self.update.assert_not_called()

    def test_missing_obsidian_prevents_installation(self):
        self.resolve.side_effect = ValueError("Install and enable the Obsidian plugin.")
        with self.assertRaises(SystemExit) as raised:
            setup.main(["--install"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("Install and enable", self.output.getvalue())
        self.run.assert_not_called()

    def test_only_requested_paths_are_updated(self):
        setup.main(["--inventory-base", "Wardrobe/Owned.base"])
        self.update.assert_called_once_with({"inventory_base": "Wardrobe/Owned.base"}, self.vault.return_value)
        self.run.assert_not_called()

    def test_invalid_destination_does_not_install(self):
        self.update.side_effect = ValueError("Inventory Base does not exist.")
        with self.assertRaises(SystemExit):
            setup.main(["--install", "--inventory-base", "Missing.base"])
        self.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
