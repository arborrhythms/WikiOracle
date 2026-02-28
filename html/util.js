// util.js — Shared utilities for WikiOracle front-end.
// Loaded after config.js and state.js.
//
// Sections:
//   Debug tap tracing       — _tapDebug, _tapLog
//   CSS / HTML helpers      — cssVar, escapeHtml, decodeEntities, stripTags
//   Text + ID helpers       — truncate, tempId
//   Tree navigation helpers — findInTree, removeFromTree, countTreeMessages
//   Double-tap detection    — onDoubleTap
//   Zoom utility            — setupZoom
//   Modal dialogs           — _createDialog, showErrorDialog, context/output/settings/config/truth/read/search editors

// config, state — declared in config.js and state.js

// ─── Debug tap tracing ───
// Enable from console: _tapDebug = true;   or add ?tapDebug to URL
var _tapDebug = /[?&]tapDebug\b/.test(location.search);
function _tapLog() {
  if (_tapDebug) console.log.apply(console, ["[tap]"].concat(Array.prototype.slice.call(arguments)));
}

// ─── CSS variable helper ───

function cssVar(name, fallback) {
  return getComputedStyle(document.documentElement)
    .getPropertyValue(name).trim() || fallback || "";
}

// ─── HTML escaping ───

function escapeHtml(text) {
  return (text || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function decodeEntities(text) {
  var el = document.createElement("textarea");
  el.innerHTML = text || "";
  return el.value;
}

function stripTags(html) {
  return decodeEntities((html || "").replace(/<[^>]+>/g, ""));
}

// ─── Text truncation ───

function truncate(text, maxLen, suffix) {
  if (maxLen === undefined) maxLen = 40;
  if (suffix === undefined) suffix = "...";
  if (!text || text.length <= maxLen) return text || "";
  return text.slice(0, maxLen - suffix.length) + suffix;
}

// ─── ID generation ───

function tempId(prefix) {
  prefix = prefix || "m_";
  return prefix + Array.from(crypto.getRandomValues(new Uint8Array(8)))
    .map(function(b) { return b.toString(16).padStart(2, "0"); }).join("");
}

/** Generate a RFC4122 v4 UUID string (same format as Python uuid). */
function generateUUID() {
  var bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 1
  var hex = Array.from(bytes).map(function(b) { return b.toString(16).padStart(2, "0"); }).join("");
  return hex.slice(0, 8) + "-" + hex.slice(8, 12) + "-" + hex.slice(12, 16) + "-" + hex.slice(16, 20) + "-" + hex.slice(20, 32);
}

// ─── Tree operations ───

function findInTree(nodes, id) {
  for (var i = 0; i < nodes.length; i++) {
    if (nodes[i].id === id) return nodes[i];
    var found = findInTree(nodes[i].children || [], id);
    if (found) return found;
  }
  return null;
}

function removeFromTree(nodes, id) {
  for (var i = 0; i < nodes.length; i++) {
    if (nodes[i].id === id) { nodes.splice(i, 1); return true; }
    if (removeFromTree(nodes[i].children || [], id)) return true;
  }
  return false;
}

function countTreeMessages(node) {
  var n = (node.messages || []).length;
  var children = node.children || [];
  for (var i = 0; i < children.length; i++) n += countTreeMessages(children[i]);
  return n;
}

// ─── Double-tap detection (mobile) ───
//
// onDoubleTap(element, callback)                       — simplest form
// onDoubleTap(element, callback, opts)                 — with options
//
// Options (all optional):
//   threshold  — max ms between taps (default 400)
//   state      — external object { time, key } that persists across DOM
//                re-creates (e.g. module-level variable).  When omitted a
//                closure-local object is used.
//   key        — function(event) → string.  When supplied, the second tap
//                must return the same key as the first (useful when the
//                DOM element is destroyed and recreated between taps).
//   onFire     — function() called synchronously when a double-tap fires,
//                before the callback.  Use for side-effects like setting a
//                "suppress the next click" flag.
//   namespace  — d3-style event namespace suffix, e.g. "doubletap".
//                When set the handler is registered via d3's selection.on()
//                as "touchend.<namespace>" instead of addEventListener.
//   target     — for background-tap filtering: if set, the handler bails
//                out when event.target !== target.

function onDoubleTap(element, callback, opts) {
  // Legacy 3rd-arg-is-threshold support (wikioracle.js call site)
  if (typeof opts === "number") opts = { threshold: opts };
  opts = opts || {};

  var threshold = opts.threshold || 400;
  var st = opts.state || { time: 0, key: null };
  var keyFn = opts.key || null;
  var onFire = opts.onFire || null;
  var target = opts.target || null;

  var ns = opts.namespace || "anon";

  function handler(e) {
    if (target && e.target !== target) {
      _tapLog(ns, "skip: target mismatch", e.target.tagName, e.target.className);
      return;
    }
    var now = Date.now();
    var k = keyFn ? keyFn(e) : "_";
    var dt = now - st.time;
    if (st.key === k && dt < threshold) {
      _tapLog(ns, "DOUBLE-TAP key=" + k, "dt=" + dt + "ms");
      if (onFire) onFire();
      e.preventDefault();
      var touch = e.changedTouches && e.changedTouches[0];
      var synth = touch
        ? { clientX: touch.clientX, clientY: touch.clientY,
            pageX: touch.pageX, pageY: touch.pageY,
            target: e.target,
            preventDefault: function() {}, stopPropagation: function() {} }
        : e;
      callback(synth, e);
      st.time = 0;
      st.key = null;
    } else {
      _tapLog(ns, "first-tap key=" + k, st.key !== k ? "(key changed from " + st.key + ")" : "(dt=" + dt + "ms, expired)");
      st.time = now;
      st.key = k;
    }
  }

  if (opts.namespace) {
    // d3 selection — element is a d3 selection
    element.on("touchend." + opts.namespace, handler);
  } else {
    // Plain DOM element
    (element.node ? element.node() : element)
      .addEventListener("touchend", handler);
  }
}

// ─── Zoom utility (d3.zoom wrapper) ───

/**
 * Set up d3.zoom on a container with optional double-click/double-tap reset.
 *
 * @param {object} opts
 *   container   — d3 selection to attach zoom behaviour to (e.g. d3.select(svg))
 *   target      — element to transform (SVG <g> or DOM element for CSS scale)
 *   mode        — "svg" (set transform attr on target) or "css" (CSS scale)
 *   scaleExtent — [min, max], default [0.5, 4]
 *   filter      — "pinch" (ctrl+wheel / 2-finger touch only), or a function, or null (all events)
 *   resetOnDblclick — true (default): double-click/double-tap empty area resets zoom
 *                     If a function, called with (zoom, currentTransform) instead
 *                     of the default reset-to-resetTransform behaviour.
 *   resetTarget — DOM element that triggers reset when it is the event.target
 *                 (defaults to container.node())
 * @returns the d3 zoom instance
 */
function setupZoom(opts) {
  var scaleExtent = opts.scaleExtent || [0.5, 4];
  var mode = opts.mode || "css";
  var resetOn = opts.resetOnDblclick !== false;
  var resetTarget = opts.resetTarget || opts.container.node();

  var filter = null;
  if (opts.filter === "pinch") {
    filter = function(event) {
      if (event.type === "wheel") return event.ctrlKey;
      if (event.type === "touchstart" || event.type === "touchmove")
        return event.touches.length >= 2;
      return false;
    };
  } else if (typeof opts.filter === "function") {
    filter = opts.filter;
  }

  var zoom = d3.zoom()
    .scaleExtent(scaleExtent);

  if (filter) zoom.filter(filter);

  // wheelPan: two-finger trackpad scroll pans (translates) instead of zooming.
  // Pinch-to-zoom (ctrl+wheel on macOS) still zooms normally.
  // Touch drag threshold: suppress small touchmove events so that d3.zoom
  // doesn't pan the tree during a tap.  Without this, slight finger movement
  // during a double-tap shifts tree content, causing the second tap to miss
  // its target and breaking d3's internal double-tap detection.
  if (opts.wheelPan) {
    var _touchStartPos = null;
    var _isDragging = false;
    var DRAG_THRESHOLD = 8; // px of Manhattan distance before drag begins

    zoom.filter(function(event) {
      if (event.type === "wheel") return event.ctrlKey; // only pinch-zoom

      if (event.type === "touchstart") {
        _isDragging = false;
        if (event.touches.length === 1) {
          var t = event.touches[0];
          _touchStartPos = [t.clientX, t.clientY];
        } else {
          _isDragging = true; // multi-touch: always allow
        }
        return !event.button;
      }

      if (event.type === "touchmove" && !_isDragging) {
        if (!_touchStartPos || event.touches.length !== 1) {
          _isDragging = true;
          return true;
        }
        var t = event.touches[0];
        if (Math.abs(t.clientX - _touchStartPos[0]) + Math.abs(t.clientY - _touchStartPos[1]) < DRAG_THRESHOLD) {
          return false; // suppress small movement — keep tree still for taps
        }
        _isDragging = true; // threshold exceeded — allow drag from now on
      }

      return !event.button; // allow drag-to-pan, touch
    });
  }

  zoom.on("zoom", function(event) {
    if (mode === "svg") {
      d3.select(opts.target).attr("transform", event.transform);
    } else {
      var k = event.transform.k;
      opts.target.style.transformOrigin = "top center";
      opts.target.style.transform = "scale(" + k + ")";
      // Compensate max-width so scaled content stays within the visible area.
      // Use percentage only when zoomed; clear when back to identity so
      // the CSS default (48rem on desktop, 90% on touch) takes over.
      if (Math.abs(k - 1) > 0.01) {
        opts.target.style.maxWidth = (100 / k) + "%";
      } else {
        opts.target.style.maxWidth = "";
      }
    }
  });

  opts.container.call(zoom);

  // Replace d3's default dblclick.zoom (which zooms in) with our handler.
  // d3.zoom internally detects double-tap on mobile (via g.taps) and
  // programmatically calls the dblclick.zoom handler — so this single
  // handler covers BOTH desktop double-click AND mobile double-tap.
  // (The previous approach — .on("dblclick.zoom", null) + separate
  // touchend.resetzoom — failed because d3.zoom's touchended calls
  // stopImmediatePropagation(), blocking any later touchend handlers.)
  if (resetOn) {
    var resetTo = opts.resetTransform || d3.zoomIdentity;
    var isCallback = typeof opts.resetOnDblclick === "function";

    function _handleBgDblclick() {
      _tapLog("bg", "zoom toggle fired");
      if (isCallback) {
        var curT = d3.zoomTransform(opts.container.node());
        opts.resetOnDblclick(zoom, curT);
      } else {
        opts.container.transition().duration(300)
          .call(zoom.transform, resetTo);
      }
    }

    opts.container.on("dblclick.zoom", function(event) {
      _tapLog("bg-dblclick.zoom", "target=" + event.target.tagName +
        (event.target.className ? "." + event.target.className : ""),
        "match=" + (event.target === resetTarget));
      if (event.target === resetTarget) {
        _handleBgDblclick();
      }
    });
  } else {
    opts.container.on("dblclick.zoom", null);
  }

  // wheelPan: intercept non-ctrl wheel events and translate instead of zoom
  if (opts.wheelPan) {
    opts.container.on("wheel.pan", function(event) {
      if (event.ctrlKey) return; // pinch-zoom handled by d3.zoom
      event.preventDefault();
      var t = d3.zoomTransform(opts.container.node());
      var newT = d3.zoomIdentity
        .translate(t.x - event.deltaX, t.y - event.deltaY)
        .scale(t.k);
      opts.container.call(zoom.transform, newT);
    });
  }

  return zoom;
}

// ─── Modal dialogs ───

// ─── Shared dialog factory ───
// Creates a modal overlay with title bar and close button.
// Returns { overlay, close } where close() hides the dialog.
// bodyHTML is injected into the panel; panelClass adds extra CSS classes.
// onClose is an optional callback invoked after hiding.
function _createDialog(id, title, bodyHTML, panelClass, onClose) {
  const overlay = document.createElement("div");
  overlay.id = id;
  overlay.className = "context-overlay";
  const cls = panelClass ? `context-panel ${panelClass}` : "context-panel";
  overlay.innerHTML =
    `<div class="${cls}">` +
    `<div class="dialog-title-bar"><h2>${title}</h2><button class="dialog-close" data-dialog-close>&times;</button></div>` +
    bodyHTML +
    `</div>`;
  document.body.appendChild(overlay);
  function close() { overlay.classList.remove("active"); if (onClose) onClose(); }
  overlay.querySelectorAll("[data-dialog-close]").forEach(function(btn) {
    btn.addEventListener("click", close);
  });
  return { overlay, close };
}

// ─── Error dialog (lightweight alert for user-facing errors) ───
// Shows a modal with a title and message. Auto-closes on OK or backdrop click.
function showErrorDialog(title, message) {
  const body =
    `<p style="margin:0 0 1rem;white-space:pre-wrap;word-break:break-word;">${escapeHtml(message)}</p>` +
    `<div class="settings-actions"><button class="btn btn-primary" data-dialog-close>OK</button></div>`;
  const dlg = _createDialog("errorDialog_" + Date.now(), title, body, null, function() {
    // Remove from DOM on close to avoid piling up
    if (dlg.overlay.parentNode) dlg.overlay.parentNode.removeChild(dlg.overlay);
  });
  // Close on backdrop click too
  dlg.overlay.addEventListener("click", function(e) {
    if (e.target === dlg.overlay) dlg.close();
  });
  requestAnimationFrame(function() { dlg.overlay.classList.add("active"); });
  return dlg;
}

// ─── Context editor (floating modal, triggered from root node) ───
function _toggleContextEditor() {
  let overlay = document.getElementById("contextOverlay");

  // Toggle off if already open
  if (overlay && overlay.classList.contains("active")) {
    overlay.classList.remove("active");
    return;
  }

  // Create overlay on first use
  if (!overlay) {
    const body = `
        <p>Injected into every LLM call as background information.</p>
        <textarea id="contextTextarea" placeholder="Describe the project, key facts, instructions..."></textarea>
        <div class="settings-actions">
          <button class="btn" id="ctxReset">Reset</button>
          <button class="btn" id="ctxCancel">Cancel</button>
          <button class="btn btn-primary" id="ctxSave">Save</button>
        </div>`;
    var dlg = _createDialog("contextOverlay", "Context", body);
    overlay = dlg.overlay;

    document.getElementById("ctxReset").addEventListener("click", function() {
      var d = config.defaults || {};
      document.getElementById("contextTextarea").value = stripTags(d.context || "<div/>").trim();
    });
    document.getElementById("ctxCancel").addEventListener("click", dlg.close);
    document.getElementById("ctxSave").addEventListener("click", function() {
      const newText = document.getElementById("contextTextarea").value.trim();
      const currentPlain = stripTags(state?.context || "").trim();
      if (state && newText !== currentPlain) {
        state.context = newText;
        _persistState();
        setStatus("Context saved");
      }
      dlg.close();
    });
  }

  // Populate and show
  const rawCtx = state?.context || "";
  document.getElementById("contextTextarea").value = stripTags(rawCtx).trim();
  overlay.classList.add("active");
  document.getElementById("contextTextarea").focus();
}

// ─── Output editor (floating modal, triggered from root context menu) ───
function _toggleOutputEditor() {
  let overlay = document.getElementById("outputOverlay");

  if (overlay && overlay.classList.contains("active")) {
    overlay.classList.remove("active");
    return;
  }

  if (!overlay) {
    const body = `
        <p>Instructions appended to every LLM call describing the desired response format.</p>
        <textarea id="outputTextarea" placeholder="Describe the desired output format..."></textarea>
        <div class="settings-actions">
          <button class="btn" id="outReset">Reset</button>
          <button class="btn" id="outCancel">Cancel</button>
          <button class="btn btn-primary" id="outSave">Save</button>
        </div>`;
    var dlg = _createDialog("outputOverlay", "Output", body);
    overlay = dlg.overlay;

    document.getElementById("outCancel").addEventListener("click", dlg.close);
    document.getElementById("outReset").addEventListener("click", function() {
      var d = config.defaults || {};
      document.getElementById("outputTextarea").value = d.output ?? "";
    });
    document.getElementById("outSave").addEventListener("click", function() {
      const newText = document.getElementById("outputTextarea").value.trim();
      if (state) {
        state.output = newText;
        _persistState();
        setStatus("Output saved");
      }
      dlg.close();
    });
  }

  // Populate from state (always present after server normalization)
  const current = state?.output ?? "";
  document.getElementById("outputTextarea").value = current;
  overlay.classList.add("active");
  document.getElementById("outputTextarea").focus();
}

// ─── Settings panel ───
function openSettings() {
  document.getElementById("setUsername").value = config.user.name || "User";
  document.getElementById("setProvider").value = config.ui.default_provider || "wikioracle";
  _populateModelDropdown(config.ui.default_provider);
  var currentModel = config.ui.model || (config.server.providers[config.ui.default_provider] || {}).model || "";
  if (currentModel) document.getElementById("setModel").value = currentModel;
  document.getElementById("setLayout").value = config.ui.layout || "flat";
  document.getElementById("setTheme").value = config.ui.theme || "system";

  // Chat settings
  const chat = config.chat || {};
  const tempSlider = document.getElementById("setTemp");
  tempSlider.value = chat.temperature ?? 0.7;
  document.getElementById("setTempVal").textContent = tempSlider.value;
  document.getElementById("setRag").checked = chat.rag !== false;
  document.getElementById("setUrlFetch").checked = !!chat.url_fetch;
  document.getElementById("setConfirm").checked = !!chat.confirm_actions;

  document.getElementById("settingsOverlay").classList.add("active");
}
function closeSettings() {
  document.getElementById("settingsOverlay").classList.remove("active");
}
async function saveSettings() {
  const newProvider = document.getElementById("setProvider").value;

  config.ui.default_provider = newProvider;
  config.ui.model = document.getElementById("setModel").value || "";
  config.user.name = document.getElementById("setUsername").value.trim() || "User";
  config.ui.layout = document.getElementById("setLayout").value;
  config.ui.theme = document.getElementById("setTheme").value || "system";

  // Chat settings
  config.chat = {
    ...(config.chat || {}),
    temperature: parseFloat(document.getElementById("setTemp").value),
    rag: document.getElementById("setRag").checked,
    url_fetch: document.getElementById("setUrlFetch").checked,
    confirm_actions: document.getElementById("setConfirm").checked,
  };

  applyLayout(config.ui.layout);
  applyTheme(config.ui.theme);
  _updatePlaceholder();
  closeSettings();

  // Persist: config is the single source of truth
  if (config.server.stateless) {
    _saveLocalConfig(config);
    setStatus("Settings saved (local)");
  } else {
    try {
      await api("POST", "/config", { config: config });
      await _refreshProviderMeta();
      setStatus("Settings saved");
    } catch (e) {
      setStatus("Error saving settings: " + e.message);
    }
  }

  // Redraw to reflect any config-driven UI changes (provider name, layout, etc.)
  if (typeof renderMessages === "function") renderMessages();
}

// ─── Config editor (edit config.yaml) ───
// Uses js-yaml (loaded via CDN) for client-side YAML ↔ JSON conversion.
// Server never sees raw YAML — only parsed dicts via POST /config.
async function _openConfigEditor() {
  // Close the settings panel first
  closeSettings();

  let overlay = document.getElementById("configOverlay");
  if (!overlay) {
    const body = `
        <textarea id="configEditorTextarea" class="config-textarea"></textarea>
        <div id="configEditorError" class="config-error"></div>
        <div class="settings-actions settings-actions-md">
          <button class="btn" id="cfgReset">Reset</button>
          <button class="btn" id="cfgCancel">Cancel</button>
          <button class="btn btn-primary" id="cfgOk">OK</button>
        </div>`;
    var dlg = _createDialog("configOverlay", "config.yaml", body, "config-panel");
    overlay = dlg.overlay;

    document.getElementById("cfgReset").addEventListener("click", function() {
      var factory = _normalizeConfig({});
      document.getElementById("configEditorTextarea").value = jsyaml.dump(factory, { lineWidth: -1 });
    });
    document.getElementById("cfgCancel").addEventListener("click", dlg.close);
    document.getElementById("cfgOk").addEventListener("click", async function() {
      const textarea = document.getElementById("configEditorTextarea");
      const errEl = document.getElementById("configEditorError");
      errEl.style.display = "none";

      // Parse YAML client-side via js-yaml
      var parsed;
      try {
        parsed = jsyaml.load(textarea.value);
        if (parsed !== null && typeof parsed !== "object") {
          errEl.textContent = "config.yaml must be a YAML mapping";
          errEl.style.display = "block";
          return;
        }
        parsed = parsed || {};
      } catch (e) {
        errEl.textContent = "YAML parse error: " + e.message;
        errEl.style.display = "block";
        return;
      }

      // Normalize and adopt as config (preserve runtime fields)
      var newConfig = _normalizeConfig(parsed);
      newConfig.server.providers = config.server.providers;
      newConfig.server.stateless = config.server.stateless;
      newConfig.server.url_prefix = config.server.url_prefix;
      if (config.ui.model) newConfig.ui.model = config.ui.model;

      config = newConfig;
      _saveLocalConfig(config);
      applyLayout(config.ui.layout);
      _updatePlaceholder();

      // Disk write in non-stateless mode
      if (!config.server.stateless) {
        try {
          var resp = await api("POST", "/config", { config: config });
          if (resp.config) config = resp.config;
        } catch (e) {
          errEl.textContent = "Disk write failed: " + e.message + " (saved to sessionStorage)";
          errEl.style.display = "block";
          return;
        }
      }

      dlg.close();
      applyTheme(config.ui.theme);
      await _refreshProviderMeta();
      setStatus("config.yaml saved");
    });
  }

  // Load current config as YAML text
  const textarea = document.getElementById("configEditorTextarea");
  const errEl = document.getElementById("configEditorError");
  errEl.style.display = "none";
  textarea.value = "Loading...";
  overlay.classList.add("active");

  // Get config dict: sessionStorage (stateless) or server
  var parsed = null;
  if (config.server.stateless) {
    parsed = _loadLocalConfig() || config;
  } else {
    try {
      const data = await api("GET", "/config");
      parsed = data.config || {};
    } catch (e) {
      textarea.value = "# Error loading config: " + e.message;
      textarea.focus();
      return;
    }
  }
  textarea.value = jsyaml.dump(parsed || {}, { lineWidth: -1 });
  textarea.focus();
}

// ─── Truth editor ───

let _truthEditing = null; // index into state.truth being edited, or "new"

function _openTruthEditor() {
  closeSettings();

  if (!Array.isArray(state.truth)) state.truth = [];

  let overlay = document.getElementById("truthOverlay");
  if (!overlay) {
    const body = `
        <div id="truthListView">
          <div id="truthEntries" class="trust-entries-scroll"></div>
          <div class="settings-actions settings-actions-xs">
            <select id="truthAddType" class="trust-input" style="max-width:9rem; font-size:0.78rem;">
              <option value="fact">Fact</option>
              <option value="reference">Reference</option>
              <option value="and">AND</option>
              <option value="or">OR</option>
              <option value="not">NOT</option>
              <option value="non">NON</option>
              <option value="provider">Provider</option>
              <option value="authority">Authority</option>
            </select>
            <button class="btn" id="truthAdd">Add</button>
            <button class="btn" id="truthClose">Close</button>
          </div>
        </div>
        <div id="truthEditView" class="hidden">
          <label id="truthEditLabel" class="trust-label"></label>
          <textarea id="truthContent" class="trust-textarea" style="min-height:6rem; font-family:ui-monospace,monospace; font-size:0.82rem;"></textarea>
          <div id="truthEditError" style="color:#dc2626; font-size:0.78rem; min-height:1.2em;"></div>
          <div class="settings-actions settings-actions-sm">
            <button class="btn" id="truthEditCancel">Cancel</button>
            <button class="btn btn-primary" id="truthEditSave">Save</button>
          </div>
        </div>`;
    var dlg = _createDialog("truthOverlay", "Truth", body, "trust-panel", function() { _truthEditing = null; });
    overlay = dlg.overlay;

    document.getElementById("truthClose").addEventListener("click", dlg.close);

    // ─── XHTML template for each subtype ───
    var _truthTemplates = {
      fact: '<fact id="ID" certainty="0.5" title="TITLE">Assertion text here.</fact>',
      reference: '<reference id="ID" certainty="0.5" title="TITLE" href="https://example.com">Link text</reference>',
      and: '<and id="ID" certainty="0.0" title="TITLE">\n  <child id="ENTRY_A"/>\n  <child id="ENTRY_B"/>\n</and>',
      or: '<or id="ID" certainty="0.0" title="TITLE">\n  <child id="ENTRY_A"/>\n  <child id="ENTRY_B"/>\n</or>',
      not: '<not id="ID" certainty="0.0" title="TITLE">\n  <child id="ENTRY_A"/>\n</not>',
      non: '<non id="ID" certainty="0.0" title="TITLE">\n  <child id="ENTRY_A"/>\n</non>',
      provider: '<provider id="ID" certainty="0.8" title="TITLE" name="provider_name" api_url="https://api.example.com" model="model_name"/>',
      authority: '<authority id="ID" certainty="0.5" title="TITLE" did="did:web:example.com" url="https://example.com/kb.jsonl"/>'
    };

    // Brief description shown above the editor for each truth type
    var _truthDescriptions = {
      fact:      "Fact \u2014 a direct assertion with a certainty value.",
      reference: "Reference \u2014 a link to an external source.",
      and:       "AND \u2014 true when all children are true (min certainty).",
      or:        "OR \u2014 true when any child is true (max certainty).",
      not:       "NOT \u2014 negation of a child entry.",
      non:       "NON \u2014 non-affirming negation (weakens certainty toward zero).",
      provider:  "Provider \u2014 an LLM API endpoint.",
      authority: "Authority \u2014 a remote knowledge base (JSONL URL)."
    };

    function _setTruthEditLabel(tag) {
      document.getElementById("truthEditLabel").textContent = _truthDescriptions[tag] || _truthDescriptions.fact;
    }

    document.getElementById("truthAdd").addEventListener("click", function() {
      _truthEditing = "new";
      var subtype = document.getElementById("truthAddType").value;
      var tmpl = _truthTemplates[subtype] || _truthTemplates.fact;
      tmpl = tmpl.replace(/id="ID"/, 'id="' + generateUUID() + '"');
      document.getElementById("truthContent").value = tmpl;
      document.getElementById("truthEditError").textContent = "";
      _setTruthEditLabel(subtype);
      _truthShowEditView();
    });

    document.getElementById("truthEditCancel").addEventListener("click", function() {
      _truthEditing = null;
      _truthShowListView();
    });

    document.getElementById("truthEditSave").addEventListener("click", function() {
      const content = document.getElementById("truthContent").value.trim();
      const errEl = document.getElementById("truthEditError");
      const now = new Date().toISOString().replace(/\.\d+Z$/, "Z");

      // Syntax check: parse as XML
      var parsed = _parseXhtmlContent(content);
      if (!parsed) {
        errEl.textContent = "Invalid XML. Check syntax.";
        return;
      }
      if (!parsed.id) {
        errEl.textContent = 'Missing required id="..." attribute on root element.';
        return;
      }
      errEl.textContent = "";

      var id = parsed.id;
      var certainty = parsed.certainty != null ? Math.min(1, Math.max(-1, parsed.certainty)) : 0.0;
      var title = parsed.title || "Untitled";

      if (_truthEditing === "new") {
        var entry = { id: id, title: title, certainty: certainty, content: content, time: now };
        state.truth.push(entry);
      } else if (typeof _truthEditing === "number") {
        var entry = state.truth[_truthEditing];
        if (entry) {
          entry.id = id;
          entry.title = title;
          entry.certainty = certainty;
          entry.content = content;
          entry.time = now;
        }
      }
      _truthEditing = null;
      _persistState();
      _truthRenderList();
      _truthShowListView();
    });
  }

  _truthEditing = null;
  _truthRenderList();
  _truthShowListView();
  overlay.classList.add("active");
}

function _truthHideAllViews() {
  document.getElementById("truthListView").classList.add("hidden");
  document.getElementById("truthEditView").classList.add("hidden");
}

function _truthShowListView() {
  _truthHideAllViews();
  document.getElementById("truthListView").classList.remove("hidden");
}

function _truthShowEditView() {
  _truthHideAllViews();
  document.getElementById("truthEditView").classList.remove("hidden");
  document.getElementById("truthContent").focus();
}

function _parseXhtmlContent(content) {
  /** Parse XHTML content and extract root tag, id, certainty, title. */
  try {
    var parser = new DOMParser();
    var doc = parser.parseFromString("<root>" + content + "</root>", "text/xml");
    if (doc.querySelector("parsererror")) return null;
    var root = doc.documentElement;
    var recognized = ["fact", "reference", "and", "or", "not", "non", "provider", "authority"];
    for (var i = 0; i < recognized.length; i++) {
      var el = root.querySelector(recognized[i]);
      if (el) {
        var c = parseFloat(el.getAttribute("certainty"));
        return {
          tag: recognized[i],
          id: el.getAttribute("id") || "",
          certainty: isNaN(c) ? null : c,
          title: el.getAttribute("title") || ""
        };
      }
    }
    return null;
  } catch (e) { return null; }
}

function _isOperator(entry) {
  if (!entry || typeof entry.content !== "string") return false;
  var c = entry.content;
  return c.indexOf("<and") !== -1 || c.indexOf("<or") !== -1 || c.indexOf("<not") !== -1 || c.indexOf("<non") !== -1;
}

function _isAuthority(entry) {
  return entry && typeof entry.content === "string" && entry.content.indexOf("<authority") !== -1;
}

function _isReference(entry) {
  return entry && typeof entry.content === "string" && entry.content.indexOf("<reference") !== -1;
}

function _isProvider(entry) {
  return entry && typeof entry.content === "string" && entry.content.indexOf("<provider") !== -1;
}

function _parseAuthContent(content) {
  try {
    var parser = new DOMParser();
    var doc = parser.parseFromString("<root>" + content + "</root>", "text/xml");
    var auth = doc.querySelector("authority");
    if (!auth) return null;
    return {
      did: auth.getAttribute("did") || "",
      orcid: auth.getAttribute("orcid") || "",
      url: auth.getAttribute("url") || "",
      refresh: parseInt(auth.getAttribute("refresh")) || 3600
    };
  } catch (e) { return null; }
}

function _parseOperatorContent(content) {
  try {
    var parser = new DOMParser();
    var doc = parser.parseFromString("<root>" + content + "</root>", "text/xml");
    var operators = ["and", "or", "not", "non"];
    for (var oi = 0; oi < operators.length; oi++) {
      var el = doc.querySelector(operators[oi]);
      if (el) {
        var refs = [];
        // New format: <child id="..."/>
        var childEls = el.querySelectorAll("child");
        for (var ci = 0; ci < childEls.length; ci++) {
          var cid = (childEls[ci].getAttribute("id") || "").trim();
          if (cid) refs.push(cid);
        }
        // Legacy fallback: <ref>text</ref>
        if (refs.length === 0) {
          var refEls = el.querySelectorAll("ref");
          for (var ri = 0; ri < refEls.length; ri++) {
            var txt = refEls[ri].textContent.trim();
            if (txt) refs.push(txt);
          }
        }
        return { operator: operators[oi], refs: refs };
      }
    }
    return null;
  } catch (e) { return null; }
}

function _parseRefContent(content) {
  try {
    var parser = new DOMParser();
    var doc = parser.parseFromString("<root>" + content + "</root>", "text/xml");
    // New format: <reference href="...">text</reference>
    var ref = doc.querySelector("reference");
    if (ref) return { url: ref.getAttribute("href") || "", text: ref.textContent.trim() };
    // Legacy fallback: <a href="...">text</a>
    var a = doc.querySelector("a");
    if (a) return { url: a.getAttribute("href") || "", text: a.textContent.trim() };
    return null;
  } catch (e) { return null; }
}

/* _populateOperandCheckboxes removed — XHTML editor handles operator children directly */

function _truthEntryTag(entry) {
  /** Return the XHTML root tag name for a truth entry (e.g. "fact", "and", "provider"). */
  if (!entry || typeof entry.content !== "string") return "fact";
  var parsed = _parseXhtmlContent(entry.content);
  return parsed ? parsed.tag : "fact";
}

function _truthRenderList() {
  const container = document.getElementById("truthEntries");
  container.innerHTML = "";
  const entries = Array.isArray(state.truth) ? state.truth : [];

  if (entries.length === 0) {
    container.innerHTML = '<div class="trust-empty">No truth entries. Use <b>Add</b> or <b>Open</b> a .jsonl file.</div>';
    return;
  }

  // Build as <table>
  const table = document.createElement("table");
  table.style.cssText = "width:100%; border-collapse:collapse; font-size:0.82rem;";

  const thead = document.createElement("thead");
  thead.innerHTML = '<tr style="border-bottom:2px solid var(--border); font-size:0.72rem; color:var(--fg-muted); text-align:left;">'
    + '<th style="padding:0.25rem 0.3rem; width:1.5em;"></th>'
    + '<th style="padding:0.25rem 0.3rem;">ID</th>'
    + '<th style="padding:0.25rem 0.3rem; text-align:right;">Cert</th>'
    + '<th style="padding:0.25rem 0.3rem;">Title</th>'
    + '<th style="padding:0.25rem 0.3rem; width:5em;"></th>'
    + '</tr>';
  table.appendChild(thead);

  const tbody = document.createElement("tbody");

  for (let i = 0; i < entries.length; i++) {
    const entry = entries[i];
    const tag = _truthEntryTag(entry);
    const icon = (typeof TRUTH_ICONS !== "undefined" && TRUTH_ICONS[tag]) || TRUTH_ICONS.fact;
    const row = document.createElement("tr");
    row.style.cssText = "border-bottom:1px solid var(--border);";

    // Icon cell
    const iconTd = document.createElement("td");
    iconTd.style.cssText = "padding:0.3rem; text-align:center; font-size:0.9rem;";
    iconTd.textContent = icon;
    iconTd.title = tag;
    row.appendChild(iconTd);

    // ID cell
    const idTd = document.createElement("td");
    idTd.style.cssText = "padding:0.3rem; font-family:ui-monospace,monospace; font-size:0.72rem; color:var(--fg-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:10em; user-select:all; cursor:default;";
    idTd.textContent = truncate(entry.id || "?", 18);
    idTd.title = entry.id || "";
    row.appendChild(idTd);

    // Certainty cell
    const certTd = document.createElement("td");
    const c = entry.certainty || 0;
    certTd.textContent = (c >= 0 ? "+" : "") + c.toFixed(2);
    certTd.style.cssText = "padding:0.3rem; text-align:right; font-family:ui-monospace,monospace; font-size:0.72rem; color:" + (c > 0 ? "var(--accent)" : c < 0 ? "#dc2626" : "var(--fg-muted)") + ";";
    row.appendChild(certTd);

    // Title cell
    const titleTd = document.createElement("td");
    titleTd.textContent = truncate(entry.title || "(untitled)", 30);
    titleTd.style.cssText = "padding:0.3rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;";
    titleTd.title = entry.title || "";
    row.appendChild(titleTd);

    // Actions cell
    const actionsTd = document.createElement("td");
    actionsTd.style.cssText = "padding:0.3rem; white-space:nowrap; text-align:right;";

    const editBtn = document.createElement("button");
    editBtn.textContent = "Edit";
    editBtn.className = "btn";
    editBtn.style.cssText = "font-size:0.72rem; padding:0.15rem 0.5rem; margin-right:0.2rem;";
    editBtn.addEventListener("click", (function(idx, entryTag) {
      return function() {
        _truthEditing = idx;
        const e = state.truth[idx];
        document.getElementById("truthContent").value = e.content || "";
        document.getElementById("truthEditError").textContent = "";
        if (typeof _setTruthEditLabel === "function") _setTruthEditLabel(entryTag);
        _truthShowEditView();
      };
    })(i, tag));
    actionsTd.appendChild(editBtn);

    const delBtn = document.createElement("button");
    delBtn.textContent = "Del";
    delBtn.className = "btn";
    delBtn.style.cssText = "font-size:0.72rem; padding:0.15rem 0.5rem; color:#dc2626;";
    delBtn.addEventListener("click", (function(idx) {
      return function() {
        const e = state.truth[idx];
        var kind = _truthEntryTag(e);
        if (confirmAction("Delete " + kind + " \"" + (e.title || "untitled") + "\"?")) {
          state.truth.splice(idx, 1);
          _persistState();
          _truthRenderList();
        }
      };
    })(i));
    actionsTd.appendChild(delBtn);

    row.appendChild(actionsTd);
    tbody.appendChild(row);
  }

  table.appendChild(tbody);
  container.appendChild(table);
}

// ─── Read view (XHTML export to new window) ───

function _serializeConversations(conversations, depth, prefix) {
  if (!conversations || !conversations.length) return "";
  if (depth === undefined) depth = 0;
  if (prefix === undefined) prefix = "";
  let html = "";
  for (let i = 0; i < conversations.length; i++) {
    const conv = conversations[i];
    const number = prefix ? prefix + "." + (i + 1) : String(i + 1);
    const title = escapeHtml(conv.title || "Untitled");
    const msgs = conv.messages || [];
    const qCount = msgs.filter(function(m) { return m.role === "user"; }).length;
    const rCount = msgs.length - qCount;
    let dateStr = "";
    if (msgs.length > 0 && msgs[0].time) {
      try { dateStr = new Date(msgs[0].time).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }); } catch(e) {}
    }
    const isRoot = depth === 0;
    const depthClass = isRoot ? " conv-root" : "";
    // HR between root-level conversations
    if (isRoot && i > 0) html += `<hr class="conv-rule">\n`;
    html += `<div class="conversation${depthClass}" data-id="${conv.id || ''}" data-depth="${depth}">\n`;
    html += `  <div class="conv-title">${escapeHtml(number)}. ${title}</div>\n`;
    if (dateStr || msgs.length > 0) {
      html += `  <div class="conv-meta">${qCount}Q ${rCount}R${dateStr ? " \u2022 " + escapeHtml(dateStr) : ""}</div>\n`;
    }
    for (const msg of msgs) {
      const role = msg.role || "user";
      const username = escapeHtml(msg.username || role);
      const escaped = escapeHtml(stripTags(msg.content).trim());
      html += `  <p class="message ${role}" data-role="${role}"><strong>${username}:</strong> ${escaped}</p>\n`;
    }
    if (conv.children && conv.children.length) {
      html += _serializeConversations(conv.children, depth + 1, number);
    }
    html += `</div>\n`;
  }
  return html;
}

// Build an ordered ancestor path (root → ... → target) for the selected conversation.
function _getAncestorPath(conversations, convId) {
  if (!convId) return null;
  function _search(convs, target) {
    for (var i = 0; i < convs.length; i++) {
      if (convs[i].id === target) return [convs[i]];
      var deeper = _search(convs[i].children || [], target);
      if (deeper) { deeper.unshift(convs[i]); return deeper; }
    }
    return null;
  }
  return _search(conversations, convId);
}

// Serialize the ancestor path as nested conversation divs with correct hierarchical numbers.
// `allConversations` is the full tree (needed to compute sibling indices).
// `path` is an array [root, ..., target] of conversation objects on the path.
function _serializeAncestorPath(allConversations, path) {
  if (!path || !path.length) return "";
  let html = "";
  let closeTags = "";
  // Walk each node on the path, computing its 1-based sibling index
  let siblings = allConversations; // siblings at current level
  let numberParts = [];
  for (let d = 0; d < path.length; d++) {
    const conv = path[d];
    // Find sibling index
    let idx = 0;
    for (let s = 0; s < siblings.length; s++) {
      if (siblings[s].id === conv.id) { idx = s; break; }
    }
    numberParts.push(idx + 1);
    const number = numberParts.join(".");
    const title = escapeHtml(conv.title || "Untitled");
    const msgs = conv.messages || [];
    const qCount = msgs.filter(function(m) { return m.role === "user"; }).length;
    const rCount = msgs.length - qCount;
    let dateStr = "";
    if (msgs.length > 0 && msgs[0].time) {
      try { dateStr = new Date(msgs[0].time).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }); } catch(e) {}
    }
    const depthClass = d === 0 ? " conv-root" : "";
    html += `<div class="conversation${depthClass}" data-id="${conv.id || ''}" data-depth="${d}">\n`;
    html += `  <div class="conv-title">${escapeHtml(number)}. ${title}</div>\n`;
    if (dateStr || msgs.length > 0) {
      html += `  <div class="conv-meta">${qCount}Q ${rCount}R${dateStr ? " \u2022 " + escapeHtml(dateStr) : ""}</div>\n`;
    }
    for (const msg of msgs) {
      const role = msg.role || "user";
      const username = escapeHtml(msg.username || role);
      const escaped = escapeHtml(stripTags(msg.content).trim());
      html += `  <p class="message ${role}" data-role="${role}"><strong>${username}:</strong> ${escaped}</p>\n`;
    }
    closeTags += `</div>\n`;
    // Next level: siblings are this node's children
    siblings = conv.children || [];
  }
  html += closeTags;
  return html;
}

async function _openReadView() {
  if (!state || !state.conversations || !state.conversations.length) {
    setStatus("No conversations to display.");
    return;
  }

  // Base URL for referencing server-hosted assets (CSS, JS)
  const baseUrl = window.location.origin + (config.server.url_prefix || "");

  // Default: serialize only the ancestor path (root → selected node).
  // If nothing is selected, show all root conversations.
  let body = "";
  let pathDesc = "";
  const ancestorPath = state.selected_conversation ? _getAncestorPath(state.conversations, state.selected_conversation) : null;
  let pathLine = "";
  if (ancestorPath && ancestorPath.length > 0) {
    body = _serializeAncestorPath(state.conversations, ancestorPath);
    pathLine = ancestorPath.map(function(c) { return c.title || "Untitled"; }).join(" \u2192 ");
  } else {
    body = _serializeConversations(state.conversations);
    pathLine = state.conversations.length + " root conversation" + (state.conversations.length !== 1 ? "s" : "");
  }
  const now = new Date().toLocaleString();
  const doc = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">
<title>WikiOracle — Read View</title>
<link rel="stylesheet" href="${baseUrl}/reading.css">
</head>
<body>
<article id="reading-content">
<h1>WikiOracle</h1>
<div class="meta"><span class="meta-label">Date:</span> ${escapeHtml(now)}<br><span class="meta-label">Path:</span> ${escapeHtml(pathLine)}</div>
<hr class="meta-rule">
${body}
</article>
</body>
</html>`;

  const blob = new Blob([doc], { type: "text/html" });
  const url = URL.createObjectURL(blob);
  const win = window.open(url, "_blank");
  if (!win) {
    // Fallback for aggressive popup blockers: navigate in current tab
    window.location.href = url;
    return;
  }
  // Revoke after a delay so the new tab has time to load
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

// ─── Search ───

function _openSearch() {
  var overlay = document.getElementById("searchOverlay");

  if (overlay && overlay.classList.contains("active")) {
    overlay.classList.remove("active");
    return;
  }

  if (!overlay) {
    var body = '<div class="search-bar">' +
      '<input id="searchInput" type="text" placeholder="Regex search through conversations...">' +
      '<button class="btn btn-primary" id="searchGo">Search</button>' +
      '</div>' +
      '<div id="searchInfo" class="search-info"></div>' +
      '<div id="searchResults" class="search-results"></div>';
    var dlg = _createDialog("searchOverlay", "Search", body, "search-panel");
    overlay = dlg.overlay;

    var searchInput = document.getElementById("searchInput");
    var searchGo = document.getElementById("searchGo");

    function doSearch() {
      var query = searchInput.value.trim();
      if (!query || !state) return;
      var results = [];
      var re;
      try { re = new RegExp(query, "gi"); } catch (e) {
        document.getElementById("searchInfo").textContent = "Invalid regex: " + e.message;
        return;
      }

      // Walk entire conversation tree
      function walkConvs(convs, path) {
        for (var i = 0; i < convs.length; i++) {
          var conv = convs[i];
          var convPath = path.concat(conv.title || "(untitled)");
          var msgs = conv.messages || [];
          for (var j = 0; j < msgs.length; j++) {
            var text = stripTags(msgs[j].content || "");
            re.lastIndex = 0;
            var match = re.exec(text);
            if (match) {
              // Build snippet around match
              var start = Math.max(0, match.index - 30);
              var end = Math.min(text.length, match.index + match[0].length + 30);
              var snippet = (start > 0 ? "..." : "") +
                escapeHtml(text.slice(start, match.index)) +
                "<mark>" + escapeHtml(match[0]) + "</mark>" +
                escapeHtml(text.slice(match.index + match[0].length, end)) +
                (end < text.length ? "..." : "");
              results.push({
                convId: conv.id,
                convTitle: conv.title || "(untitled)",
                msgIdx: j,
                msgId: msgs[j].id,
                role: msgs[j].role || "user",
                snippet: snippet,
                path: convPath.join(" > ")
              });
            }
          }
          walkConvs(conv.children || [], convPath);
        }
      }
      walkConvs(state.conversations || [], []);

      document.getElementById("searchInfo").textContent = results.length + " match" + (results.length !== 1 ? "es" : "") + " found";
      var container = document.getElementById("searchResults");
      container.innerHTML = "";

      for (var k = 0; k < results.length; k++) {
        (function(r) {
          var div = document.createElement("div");
          div.className = "search-result";
          div.innerHTML = '<div class="search-result-title">' + escapeHtml(r.convTitle) + ' <span style="color:var(--fg-muted);font-weight:normal">(' + r.role + ')</span></div>' +
            '<div class="search-result-snippet">' + r.snippet + '</div>';
          div.addEventListener("click", function() {
            dlg.close();
            navigateToNode(r.convId);
            // Scroll to the matching message after render
            setTimeout(function() {
              var msgEl = document.querySelector('[data-msg-id="' + r.msgId + '"]') ||
                          document.querySelector('[data-msg-idx="' + r.msgIdx + '"]');
              if (msgEl) {
                msgEl.scrollIntoView({ behavior: "smooth", block: "center" });
                var bubble = msgEl.querySelector(".msg-bubble");
                if (bubble) {
                  bubble.classList.add("msg-selected");
                  setTimeout(function() { bubble.classList.remove("msg-selected"); }, 2000);
                }
              }
            }, 100);
          });
          container.appendChild(div);
        })(results[k]);
      }
    }

    searchGo.addEventListener("click", doSearch);
    searchInput.addEventListener("keydown", function(e) {
      if (e.key === "Enter") { e.preventDefault(); doSearch(); }
    });
  }

  // Clear and show
  document.getElementById("searchInput").value = "";
  document.getElementById("searchInfo").textContent = "";
  document.getElementById("searchResults").innerHTML = "";
  overlay.classList.add("active");
  document.getElementById("searchInput").focus();
}
