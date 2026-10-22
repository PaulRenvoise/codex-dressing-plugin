---
name: curate-styleboard
description: Find and present visual style references, collect the user's choices, and add only selected references to the Obsidian Styleboard Canvas.
---

# Curate the Styleboard

Read [the shared vault contract](../../references/vault-contract.md). Load the
current Styleboard and relevant Inventory and Preferences, including explicit
`preference_type: style` records. Inspect representative
reference images rather than inferring style solely from group names.

Find a small, varied visual selection matching the requested direction. Show
numbered images with original source links and explain each reference's useful
features: silhouette, proportions, palette, texture or layering. Distinguish
real inspiration from purchasable items; an inspiration search does not require
every garment to be in stock. Explain relevant differences from the user's
existing board instead of treating superficial colour similarity as a match.

Prefer `Dressing.show_styleboard_gallery` for a visual selection. Pass 1–12
references with `title`, `note`, `source_url` (the original reference page) and
`image_url` (the original direct image). The gallery loads existing Canvas groups,
starts with no selection or destination, and lets the user select multiple images
and choose one destination group for that batch. Only the user may invoke the
UI-only `add_styleboard_selection` action; never call it on their behalf.
Showing a gallery writes nothing. `demo: true` uses sample groups and never reads
or writes Obsidian, including when the user clicks Test add.

The gallery accepts direct image URLs from any public HTTPS host. Local, private,
credential-bearing and unavailable image hosts are rejected. Each gallery declares
only the image origins used by its references. Do not rewrite URLs or download
images to bypass preview restrictions. If the client cannot render the gallery,
collect selections in chat and follow the existing save workflow below.

The gallery downloads only selected images and places references inside the chosen
group, using its ID rather than its label. It preserves existing nodes and edges,
and may expand only that group's boundary into empty space. If there is no room,
it reports the problem without rearranging other items. Existing source links are
skipped. Failed image downloads produce source-link references with an explicit
warning. A changed vault, removed group, or concurrent Canvas edit stops the save.
Read save outcomes; do not claim an image was saved when only its link was added.

Wait for the user's selection before adding proposed references. Their selection
authorizes the corresponding addition; do not ask a second time. For an
explicitly supplied reference and "add this", proceed directly.

Download only selected real images, inspect them and save them with
`attach-image --collection styleboard --apply`. If the source image is
inaccessible, use a source-link Canvas card when useful and explicitly identify
the missing image; do not generate a stand-in. Check existing Canvas file/link
nodes to avoid duplicates.

Read the Canvas again immediately before editing. Use `canvas-add` for an
additive adjacent reference group with an image, source and short explanation.
Preserve all existing nodes, edges, IDs and layouts. The helper associates the
new group with a named existing style group without moving that group. If exact
in-group placement is requested, inspect the actual geometry before a targeted
edit, preserving a backup and checking for concurrent changes.

Verify the saved image path and Canvas contents, and visually inspect the board
when tools permit. Report the selected references saved and link the Canvas.
Never treat one liked reference as proof that every garment or detail in it is
liked. Do not save inferred taste rules as user feedback.
