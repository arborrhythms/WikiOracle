# TODO

## Allow a wider divider to sit next to the edges of screen (but dont let it move out of navigable reach). Then we dont need a "flat" option.
**DONE** (2026-02-24) — Divider widened to 8px (14px on touch), added invisible hit-area expander (::before pseudo-element with ±6px inset). Tree can now collapse to 0 height/width (min-height/min-width set to 0) but divider stays on-screen (max 80% viewport). "Flat" layout option removed from the Settings dropdown. The flat CSS class is kept for backwards compat but now just collapses the tree to zero height instead of hiding the divider. Files: `html/index.html`.

## Double clicks and drags on queries and responses are not working
**DONE** (2026-02-24) — Added `dblclick` handler on message bubbles that opens the context menu (Move up/down, Split, Delete). Added double-tap detection for mobile via `touchend` with 350ms window. Drag-to-reorder is now gated behind `pointer: fine` media query so it only activates on desktop (prevents drag from interfering with touch gestures on mobile). Files: `html/wikioracle.js`.
FEEDBACK: remove the move up/down command, can probably reuse menu from tree node
**ADDRESSED** (2026-02-24) — Removed Move up/Move down from message context menu. Menu now mirrors tree node pattern: "Split..." + separator + "Delete". File: `html/wikioracle.js`.

## File_type formatting is not being respected (xhtml).
**DONE** (2026-02-24) — Four sub-items completed:
  0. Removed `output_format` from `config.yaml` and from the prefs GET/POST endpoints in `WikiOracle.py`. Removed the `_effective_output_format()` helper and the `output_format` plumbing in `prompt_bundle.py`.
  1. Added hardcoded XHTML system instruction to every prompt bundle: `"Return strictly valid XHTML: no Markdown, close all tags, escape entities, one root element."` — appended to the system context in `build_prompt_bundle()`.
  2. Added client-side XHTML validation in `wikioracle.js` using DOMParser with `application/xhtml+xml` to detect parse errors.
  3. Added deterministic repair pass (`repairXhtml()`) that uses the browser's HTML parser to fix broken markup and self-close void elements. Falls back to escaping and wrapping in `<p>` if repair also fails. `ensureXhtml()` is called on every message bubble during rendering.
  Files: `html/wikioracle.js`, `bin/prompt_bundle.py`, `WikiOracle.py`, `config.yaml`.

## Allow interface pinch-zoom via d3 in both panels
**DONE** (2026-02-24) — Added d3.zoom() to the tree SVG (scaleExtent 0.3–4x, wraps all tree content in a zoomG group; double-click zoom disabled to preserve context menu). Added d3.zoom() to the chat panel with CSS transform on the chat wrapper (scaleExtent 0.5–3x). Both zoom behaviors filter to only respond to pinch gestures (2+ touch fingers) or ctrl+wheel (trackpad pinch), so normal scrolling is unaffected. Files: `html/d3tree.js`, `html/index.html`.

## "Edit config.yaml" is not working for stateless operation
**DONE** (2026-02-24) — Added fallback in the config editor's OK handler: if the POST to `/config` returns a 403 (stateless mode), it now saves to localStorage instead of showing an error. This covers the case where `_serverInfo.stateless` isn't set correctly (e.g. `/server_info` failed). File: `html/wikioracle.js`.
FEEDBACK: always modify localStorage, then write to disk if available. so code path is shared.
**ADDRESSED** (2026-02-24) — Refactored config editor OK handler: always writes to localStorage first (shared path), then attempts POST to /config for disk persistence. If disk write fails with 403 or other error, localStorage already has the data. Single code path for both modes. File: `html/wikioracle.js`.

## Import/export state buttons are unclear. So buttons should be labelled "Open, Read, Save, Settings" (oepn and save replace import/export)
**DONE** (2026-02-24) — Relabeled header buttons: "Import State" → "Open", "Export State" → "Save". Reordered to: Open, Read, Save, Settings. Tooltips updated accordingly. File: `html/index.html`.

## "Read" should allow popups as separate pages that allow reading mode (in iOS). It is a nice to have for that to be zoomable also, so maybe it can use d3 and the same CSS?
**DONE** (2026-02-24) — Read view now opens in a new tab as a proper `<article>` element (helps iOS Safari Reader Mode detect article content). Added `user-scalable=yes` to viewport meta. Injected d3.js and a pinch-zoom script (same pattern as main UI: ctrl+wheel or 2-finger pinch, scaleExtent 0.5–4x). Uses the same `reading.css` styles. File: `html/wikioracle.js`.

## Hover on tree nodes should show metadata, not text
**DONE** (2026-02-24) — Tooltip now shows: id, message count (with Q count), branch count, and time range (first/last message timestamps). No longer shows title or message content previews. File: `html/d3tree.js`.
FEEDBACK: show title, short date, number of contained nodes (Q+R)
**ADDRESSED** (2026-02-24) — Tooltip now shows: title, short date (e.g. "Feb 24" from first message), and Q+R count (e.g. "3Q + 3R"). Removed raw id, branch count, and full ISO timestamps. File: `html/d3tree.js`.

## Editing "system/context" and "output" on "/" node is redundant: we only need to "Edit context" on / (and add a delete there two that removes all child nodes and renders an empty tree).
**DONE** (2026-02-24) — Removed "Edit Output" from root context menu. Added "Delete All" option (with separator) that removes all conversations after a confirmation dialog showing root count and total message count. Added `_deleteAllConversations()` function. Files: `html/d3tree.js`, `html/wikioracle.js`.

## Add a CSS section to the config that allows overrides of the default .css file. For example specify light/dark mode in the css as inherited from the system, and allow the override there.
**DONE** (2026-02-24) — Added `ui.css` field in `config.yaml` (multiline string with pipe syntax). Default includes a `@media (prefers-color-scheme: dark)` block that overrides all CSS custom properties for dark mode. Server exposes the CSS string in the `/prefs` GET response. Client injects it as a `<style id="wikioracle-css-override">` element in `<head>` on init. Users can edit the CSS via the config.yaml editor to customize colors, fonts, etc. Files: `config.yaml`, `WikiOracle.py`, `html/wikioracle.js`.
