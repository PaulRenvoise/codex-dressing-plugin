# Dressing

A local Codex plugin for browsing your wardrobe, building outfits, collecting style references, and getting shopping advice grounded in your Obsidian notes.

Dressing uses three collections: **Inventory** for owned garments, **Styleboard** for visual references, and **Preferences** for your explicit feedback, styles, and shopping sources. It connects through the [Obsidian plugin](https://github.com/PaulRenvoise/codex-obsidian-plugin), sharing that plugin's vault selection and read-only setting.

## Features

- Browse owned garments and local photos in a searchable wardrobe panel. Select pieces to build an outfit, compare them, or ask how to wear them.
- Add owned pieces from a product link, photo, or supplied details.
- Get candid styling opinions and shopping recommendations based on your actual wardrobe and preferences.
- Rate shopping suggestions with Yes / Maybe / No and an optional comment. Feedback is saved only when you submit it.
- Select visual references and add them to an existing Styleboard Canvas group.
- Configure the three collection locations in native plugin settings.

The package includes five skills, three MCP App views, and a local Python MCP server. The current runtime is Dressing **1.8.1**.

## Requirements

- Codex with plugin support and the `codex` command on PATH. The interactive panels require a desktop host with MCP Apps support; native feedback forms require elicitation support.
- Python **3.11 or later** and [uv](https://docs.astral.sh/uv/).
- macOS or Linux. Windows is not supported by the current file locking and process handling.
- The [Obsidian plugin](https://github.com/PaulRenvoise/codex-obsidian-plugin), installed, enabled, and configured. Version 1.2.1 is the reference integration; Dressing discovers the single enabled installation through `codex plugin list --json` and requires its settings-aware CLI wrapper.
- Obsidian running with its official CLI enabled and your vault registered in the app.

`uv` resolves the server's pinned MCP and Pillow dependencies from the committed script lockfile. The first server launch needs network access to download those dependencies. The standalone vault helper uses only the Python standard library.

## Install

First install and configure the Obsidian plugin using its [setup instructions](https://github.com/PaulRenvoise/codex-obsidian-plugin#install). Dressing does not install dependencies or select a vault automatically.

Clone this repository into a folder you intend to keep:

```sh
git clone https://github.com/PaulRenvoise/codex-dressing-plugin.git
cd codex-dressing-plugin
python3 setup.py --check
python3 setup.py --install
```

The installer registers this checkout as the `codex-dressing-plugin` marketplace and installs `dressing@codex-dressing-plugin`. Reload Codex or start a new conversation afterwards. The prerequisite check verifies executable availability and the enabled Obsidian package; it does not test a live vault connection.

Alternatively, register the Git repository directly:

```sh
codex plugin marketplace add https://github.com/PaulRenvoise/codex-dressing-plugin.git --ref main
codex plugin add dressing@codex-dressing-plugin
```

If you previously installed Dressing from a development marketplace such as `dressing-local-source`, disable or uninstall that copy before enabling this one. Settings are stored separately from the installed package and are shared by installations with the same plugin name.

The repository follows the same `.agents/plugins/marketplace.json` and `plugins/<name>` layout as the Obsidian reference, using Codex's supported compatibility manifest. See the [official plugin packaging documentation](https://developers.openai.com/plugins/build/plugins) for marketplace behaviour.

## Configure your collections

Open **Dressing → Settings** in Codex. The default vault-relative paths are:

| Setting | Default |
| --- | --- |
| Inventory Base | `Dressing/Inventory/Inventory.base` |
| Preferences Base | `Dressing/Preferences/Preferences.base` |
| Styleboard Canvas | `Dressing/Styleboard/Styleboard.canvas` |

These files must already exist. For a new wardrobe, copy the empty [starter Dressing folder](examples/vault/Dressing) into your vault. Merge carefully if a Dressing folder already exists; do not replace your existing collections. The starter Canvas contains one empty **Inspiration** group, which you can rename or replace with your own groups in Obsidian. No personal wardrobe records, photos, ratings, or style preferences are bundled.

To use existing collections elsewhere, select them in settings. Inventory and Preferences notes must live directly beside their Base file and have a `base` property matching that file's name. A settings change does not move files, update note properties, or rewrite Base filters. Garment photos use local image wikilinks in `clothing_photo`.

If native settings are unavailable, use the repository helper:

```sh
python3 setup.py --inventory-base 'Wardrobe/Owned/Owned.base' \
  --preferences-base 'Wardrobe/Preferences/Preferences.base' \
  --styleboard-canvas 'Wardrobe/References/References.canvas'
```

Run `python3 setup.py` without arguments to show the effective paths. Dressing settings live at `$CODEX_HOME/plugin-data/dressing/settings.json`, defaulting to `~/.codex/plugin-data/dressing/settings.json`. Vault selection and read-only mode remain in the Obsidian plugin's settings.

See the [vault contract](plugins/dressing/references/vault-contract.md) for note properties, units, duplicate handling, and feedback rules. The current schema uses EUR prices and centimetre measurements.

## Use

Ask Codex to:

- “Open my wardrobe and build an outfit around these pieces.”
- “Add this shirt I own to Inventory.”
- “Would this jacket work with my wardrobe?”
- “Find a few knitwear options that fit my preferences.”
- “Find visual references for my Styleboard.”

Wardrobe selections are temporary context, not ratings. The Add a piece form starts a conversation workflow; it does not immediately create a note. Shopping feedback never creates ownership, and owned items are excluded from shopper feedback. Only the user's submitted choices are saved by the recommendation cards and Styleboard gallery.

## Data and network access

Garment records and photos remain in your configured local Obsidian vault. Dressing reads selected records and serves thumbnails to the Codex host for display and styling context. Recommendation and Styleboard views load verified public HTTPS images; adding selected references can download those images into the vault. No separate Dressing backend or account is required.

Vault writes use the configured Obsidian connection and respect its read-only mode. Local CLI communication may require sandbox permission. Preview/demo flows do not save feedback; no personal settings, notes, or credentials are included in this repository.

## Development

Verify the plugin's behaviour and interactive rendering manually in Codex. Use demo mode when checking recommendation cards or the Styleboard gallery to avoid writing feedback or references to Obsidian.

The wardrobe entry uses bundled light and dark T-shirt icons from `assets/`, embedded as data URLs in its MCP tool metadata. The plugin listing and composer use the matching blue icon.

The MCP launch configuration lives in `plugins/dressing/.mcp.json`. Server dependencies are pinned in `scripts/feedback_server.py` and its adjacent `.lock` file. Keep both in sync when changing dependencies. For runtime releases, update the plugin manifest and server version together.

To refresh a Git-backed marketplace installation after changes:

```sh
codex plugin marketplace upgrade codex-dressing-plugin
codex plugin add dressing@codex-dressing-plugin
```

For a local checkout, pull changes in that checkout first. Reload Codex after refreshing the installed copy.

## License

[MIT](LICENSE)
