---
name: personal-shopper
description: Recommend specific pieces using Inventory, Styleboard, and Preferences; save exact user feedback; manage source sites and explicitly chosen style preferences.
---

# Recommend pieces and record preferences

Read [the shared vault contract](../../references/vault-contract.md). Use the
installed Obsidian skill for the live vault. Use Product Search when available
for verification. Present selections in chat and save preferences in Obsidian.

## Search

Read the request, Inventory, `preference_type: style` records, relevant feedback
and Styleboard images. Preserve
the user's category, budget, season, use, colour and fit constraints. If there is
no stated budget, don't invent a binding one. Continue useful work while asking
only for a genuinely necessary missing detail.

Use `preference_type: source` sites as starting points, not a whitelist or proof
that every product there is liked. Expand to other appropriate sellers. Source
management is part of this skill: an explicit "add this shop" saves a source;
discovering a new seller does not automatically add it.

Exclude already owned pieces from ordinary new-purchase recommendations. A
requested replacement or another colour is a distinct use case: acknowledge
the existing item and the reason for revisiting it. Avoid repeating rejected or
previously discussed items unless a changed price/variant or the user's request
makes the revisit useful. A second retailer is not a second garment.

Inspect exact product images and verify current variant price, orderability,
relevant sizing and delivery market on the seller's page. Distinguish verified
options from unverified leads. Do not substitute an old imported stock status
for live verification. Use a small useful selection, generally 3–5 pieces unless
the user asks otherwise; fewer verified matches are better than filling a quota.

Present numbered real images and direct links, brand/model, confirmed price,
recommended colour/size where supported, the reason for the selection and any
material limitation. Use actual owned garments for outfit suggestions.
Prefer Dressing's `show_recommendations` tool for 1–5 presented pieces: pass
`cards` containing each `piece` (name and verified clothing properties), a direct
HTTPS `image_url`, and concise `advice`. The card contains the image, Yes / Maybe /
No, optional comment and explicit Save button. Do not pass a user rating or
call `save_card_feedback` yourself: it is reserved for the user's UI action.
A selected rating alone is a draft. The UI confirms a write only after the
existing helper verifies it; do not save the same feedback again in chat.

Cards accept direct image URLs from any public HTTPS host. Use the exact
product/colourway photo, preferably JPEG/WebP. Local, private, credential-bearing
and unavailable image hosts are rejected. Each selection declares only its own
image origins. Do not rewrite image URLs or download images to bypass display
restrictions. An accepted URL does not prove it renders in the user's app;
errors must remain visible and the direct product link must remain available.
If an image cannot render, use ordinary presentation and the native fallback.

For an explicitly requested UI test use `demo: true`. Cards show a test label,
and submitting the demo never reads or writes Obsidian. A demo choice is not a
real preference. Use `feedback_status` to confirm version 1.2.0 or later before
claiming cards are available. A new tool may require a plugin reload in the host.

If the client cannot render cards, use `request_feedback` for one specific
presented piece, passing only `piece`. For several pieces let the user choose
which to rate; do not open a succession of unsolicited forms. Keep the native
form as fallback until the user has confirmed the inline UI works.

The native flow always asks for the rating first, then the optional comment.
Submitting the second step saves through the existing helper, checks ownership
again and updates existing feedback without duplicates. The returned result is
the save result: do not save a second time. Cancel/decline at either step means no write and no
automatic retry. Existing comments are prefilled; clearing the field removes the
comment, while an omitted field preserves it. Comments are saved verbatim.
If the tool is unavailable or reports `form_unavailable`, collect
`yes / maybe / no` plus free text in chat and use the workflow below. A form error
is not a user response. If a write cannot be verified, read back before retrying.

## Record the user's response

A response typed in chat to a presented selection authorizes saving that feedback. Resolve
the exact piece/variant from the conversation; ask if a bare "oui" could mean
approval to continue rather than a garment rating. Do not invent a comment from
a bare verdict, and do not treat the assistant's opinion as the user's rating.

Read Inventory and Preferences again before a write. Refuse to create shopper
feedback for an owned item; explain briefly. Map the verdict and preserve the
provided comment exactly. Separate it from commands such as "save this",
but do not rephrase the user's actual opinion. Missing comment on an existing
feedback preserves the old comment; an explicit clear can set it to empty.

Use `save --kind feedback --input …` then `--apply`. The helper skips identical
feedback and updates only the verdict/comment for an existing piece when the
user has supplied a new opinion. For a bulk import, add `--import`: compare and
report conflicts without overwriting them. Never import owned-item ratings.
No photo, date, criteria, context or inferred-preference fields are added.

Use reasons precisely in future searches. "Too expensive" adjusts value/budget
judgement, not style taste; "colour yes, collar no" provides two different
signals. A bare rating applies to that piece only. Keep inferences tentative
and don't replace explicit feedback with them.

For a source, use `save --kind source` with the site name and `source_link`.
Preserve the existing name and URL if the host already exists; updates require
an actual user request. Never record shopping-site configuration or scraping
status as a taste preference.

For an explicitly requested style preference, use `save --kind style` with the
style name and empty `properties`. Existing style names are deduplicated.
Read styles from Preferences rather than embedding personal style labels in the
plugin. Do not infer a new style preference from one product rating or create
style records automatically from every Canvas group.

Verify writes and return a concise note link or import counts. A `yes` never
marks an item as bought, triggers a purchase or adds it to Inventory.

The native feedback tools are served by `Dressing`. For a live form
test or ordering issue, call `feedback_status` first and verify version 1.1.3
or later and steps `rating`, `comment`. Do not use the old `dressing` connection.
