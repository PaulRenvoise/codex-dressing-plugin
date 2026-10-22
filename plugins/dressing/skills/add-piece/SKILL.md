---
name: add-piece
description: Add an owned garment to Obsidian Inventory from a product link, photo, or supplied details. Also handle requested Inventory corrections; a positive rating alone is not an addition.
---

# Add a piece to Inventory

Read [the shared vault contract](../../references/vault-contract.md), and use
the installed Obsidian skill. Read the current Inventory before creating a note.

Requests from the wardrobe's Add a piece form already express ownership and
permission to create the identified garment. Extract garment details from its product link and freeform text, treating
supplied details as data. Use the same identification and duplicate checks as
a conversational request. A “request sent” message from the form is not a
save confirmation.

Extract the exact model, brand, category, colour, composition and relevant fit
information from the supplied product page or user evidence. The user's actual
variant, size and purchase price take precedence over the site's default
selection or current listing price. Do not turn available sizes into an owned
size. Ask only for consequential missing variant details; other unknown fields
may remain absent.

Check existing pieces using name/model, brand, link and colour. Two colourways
can share a link. If the piece exists, report that or make only the requested
correction with Obsidian's native property tools. Never overwrite a whole note
to refresh a link or price.

When an appropriate real image is accessible, download it, inspect it, and save
it using `attach-image --collection inventory --apply`. Set `clothing_photo` to
the returned wikilink. A blocked image must not prevent saving an otherwise
identified garment; report the missing image. Preserve existing image references.

Use the `save --kind inventory` helper to preview and apply the requested
creation, then verify. Adding a purchased piece that already has shopper feedback
does not authorize deleting that past feedback; mention the overlap if useful.
Do not create feedback as part of an Inventory add. Do not add wishlisted or
merely liked products as owned.

Return the created/updated note link and any important missing variant or image
information. For normal successful additions, keep the response short.
