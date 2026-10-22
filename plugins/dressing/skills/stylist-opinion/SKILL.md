---
name: stylist-opinion
description: Give a candid yes, maybe, or no opinion on a linked or pictured garment, with colour and sizing advice grounded in Inventory, Styleboard, and Preferences.
---

# Give a stylist's opinion

Read [the shared vault contract](../../references/vault-contract.md). Consult
current Inventory, style preferences, relevant Styleboard images and explicit feedback before a
personal assessment. If a collection is unavailable, explain what the opinion
can and cannot be grounded in; do not pretend to have seen it.

Inspect the exact piece and colourway visually. For purchase-related checks, use
the installed Product Search skill when available. Verify current price, stock,
size information and relevant composition on the exact product page. Keep an
informational follow-up scoped to its question.

Lead with a candid **yes / no / maybe**, meaning the stylist's recommendation.
Explain the decisive reasons: style direction, proportions, wardrobe usefulness,
redundancy, intended use, material or price. A no can be "good garment, little
use in this wardrobe." A maybe must have an identifiable condition or uncertainty.
Avoid automatic praise, unsupported quality claims, numerical taste scores and
purchase probabilities.

Offer the best colour among actually available relevant variants, with reasons.
Distinguish palette compatibility from claims about complexion: do not infer
personal colouring from product images. For sizing, compare exact-size garment
measurements and their conventions with known comfortable owned garments.
Brand size labels and model height alone cannot establish fit. State confidence
and the specific missing measurement when needed; do not manufacture certainty.

When helpful, give one or two ways to wear the item with actual owned pieces.
Do not invent garments or imply that referenced Styleboard pieces are owned.
Respect explicit negative feedback but keep its reason scoped: price rejection
does not equal dislike of the cut; a liked reference is not a universal rule.

This is advice, not a user vote. Do not write the assistant's verdict into
Preferences. After presenting advice about a potential purchase, use Dressing's
native `request_feedback` tool for the user's own Yes / Maybe / No and optional
comment. Pass only the exact piece's name and verified clothing properties,
including its link and list-valued brand; never pass the assistant's verdict.
The tool saves accepted responses and returns the outcome, so do not write again.
Cancelling or declining saves nothing; do not reopen the form automatically.
If forms are unavailable, or the user already gave their opinion in chat, use
the [shopper workflow](../personal-shopper/SKILL.md) to record it, checking
ownership first. Advice on an owned piece remains valid but does not open a
feedback form or create a shopper feedback note.

The native feedback tools are served by `Dressing`. For a live form
test or ordering issue, call `feedback_status` first and verify version 1.1.3
or later and steps `rating`, `comment`. Do not use the old `dressing` connection.
