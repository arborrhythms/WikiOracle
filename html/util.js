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
//   Modal dialogs           — _createDialog, context/output/settings/config/truth/read/search editors

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
      opts.target.style.transformOrigin = "top center";
      opts.target.style.transform = "scale(" + event.transform.k + ")";
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

// ─── Spec defaults (cached after first fetch) ───
let _specDefaults = null;
async function _getSpecDefaults() {
  if (!_specDefaults) {
    try { _specDefaults = await api("GET", "/spec_defaults"); }
    catch (e) { _specDefaults = { context: "<div/>", output: "", config_parsed: {} }; }
  }
  return _specDefaults;
}


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
  const closeBtn = overlay.querySelector("[data-dialog-close]");
  function close() { overlay.classList.remove("active"); if (onClose) onClose(); }
  closeBtn.addEventListener("click", close);
  return { overlay, close };
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

    document.getElementById("ctxReset").addEventListener("click", async function() {
      const defaults = await _getSpecDefaults();
      document.getElementById("contextTextarea").value = stripTags(defaults.context).trim();
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
    document.getElementById("outReset").addEventListener("click", async function() {
      const defaults = await _getSpecDefaults();
      document.getElementById("outputTextarea").value = defaults.output ?? "";
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
  const winSlider = document.getElementById("setWindow");
  winSlider.value = chat.message_window ?? 40;
  document.getElementById("setWindowVal").textContent = winSlider.value;
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
  const meta = config.server.providers[newProvider];
  if (meta && meta.needs_key && !meta.has_key) {
    setStatus(`${meta.name} requires an API key. Add it to config.yaml (Settings → Edit Config).`);
  }

  config.ui.default_provider = newProvider;
  config.ui.model = document.getElementById("setModel").value || "";
  config.user.name = document.getElementById("setUsername").value.trim() || "User";
  config.ui.layout = document.getElementById("setLayout").value;
  config.ui.theme = document.getElementById("setTheme").value || "system";

  // Chat settings
  config.chat = {
    ...(config.chat || {}),
    temperature: parseFloat(document.getElementById("setTemp").value),
    message_window: parseInt(document.getElementById("setWindow").value, 10),
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

    document.getElementById("cfgReset").addEventListener("click", async function() {
      const defaults = await _getSpecDefaults();
      var parsed = defaults.config_parsed;
      if (parsed && Object.keys(parsed).length) {
        document.getElementById("configEditorTextarea").value = jsyaml.dump(parsed, { lineWidth: -1 });
      } else {
        setStatus("spec/config.yaml not found");
      }
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

let _truthEditing = null; // index into state.truth.trust being edited, or "new"

function _openTruthEditor() {
  closeSettings();

  if (!state.truth) state.truth = {};
  if (!Array.isArray(state.truth.trust)) state.truth.trust = [];

  let overlay = document.getElementById("truthOverlay");
  if (!overlay) {
    const body = `
        <div id="truthListView">
          <div id="truthEntries" class="trust-entries-scroll"></div>
          <div class="settings-actions settings-actions-xs">
            <button class="btn" id="truthAdd">Add Entry</button>
            <button class="btn" id="truthAddImpl">Add Implication</button>
            <button class="btn" id="truthAddAuth">Add Authority</button>
            <button class="btn" id="truthClose">Close</button>
          </div>
        </div>
        <div id="truthEditView" class="hidden">
          <label class="trust-label">Title</label>
          <input id="truthTitle" type="text" class="trust-input">
          <label class="trust-label">Certainty <span class="trust-label-hint">(-1 = false, 0 = unknown, +1 = true)</span></label>
          <input id="truthCertainty" type="number" min="-1" max="1" step="0.05" value="0.5" class="trust-input">
          <label class="trust-label">Content <span class="trust-label-hint">(XHTML: &lt;p&gt; facts, &lt;a href&gt; sources, &lt;provider&gt; LLMs, &lt;implication&gt; rules)</span></label>
          <textarea id="truthContent" class="trust-textarea"></textarea>
          <div class="settings-actions settings-actions-sm">
            <button class="btn" id="truthEditCancel">Cancel</button>
            <button class="btn btn-primary" id="truthEditSave">Save</button>
          </div>
        </div>
        <div id="truthImplView" class="hidden">
          <label class="trust-label">Title</label>
          <input id="implTitle" type="text" class="trust-input" placeholder="A → B (derived)">
          <label class="trust-label">Antecedent <span class="trust-label-hint">(if this entry is believed…)</span></label>
          <select id="implAntecedent" class="trust-input"></select>
          <label class="trust-label">Consequent <span class="trust-label-hint">(…then raise certainty of this entry)</span></label>
          <select id="implConsequent" class="trust-input"></select>
          <label class="trust-label">Certainty <span class="trust-label-hint">(-1 = false, 0 = unknown, +1 = true)</span></label>
          <input id="implCertainty" type="number" min="-1" max="1" step="0.05" value="0.5" class="trust-input">
          <label class="trust-label">Type</label>
          <select id="implType" class="trust-input">
            <option value="material">Material (Strong Kleene)</option>
            <option value="strict">Strict (modal)</option>
            <option value="relevant">Relevant (anti-paradox)</option>
          </select>
          <div class="settings-actions settings-actions-sm">
            <button class="btn" id="implEditCancel">Cancel</button>
            <button class="btn btn-primary" id="implEditSave">Save</button>
          </div>
        </div>
        <div id="truthAuthView" class="hidden">
          <label class="trust-label">Title</label>
          <input id="authTitle" type="text" class="trust-input" placeholder="Authority name">
          <label class="trust-label">DID <span class="trust-label-hint">(Decentralized Identifier, e.g. did:web:example.com)</span></label>
          <input id="authDid" type="text" class="trust-input" placeholder="did:web:...">
          <label class="trust-label">ORCID <span class="trust-label-hint">(optional, e.g. 0000-0002-1825-0097)</span></label>
          <input id="authOrcid" type="text" class="trust-input" placeholder="0000-0000-0000-0000">
          <label class="trust-label">URL <span class="trust-label-hint">(URL to remote llm.jsonl trust table)</span></label>
          <input id="authUrl" type="text" class="trust-input" placeholder="https://example.com/kb.jsonl">
          <label class="trust-label">Certainty <span class="trust-label-hint">(-1 = distrust, 0 = unknown, +1 = full trust)</span></label>
          <input id="authCertainty" type="number" min="-1" max="1" step="0.05" value="0.5" class="trust-input">
          <label class="trust-label">Refresh <span class="trust-label-hint">(seconds between re-fetches, default 3600)</span></label>
          <input id="authRefresh" type="number" min="60" step="60" value="3600" class="trust-input">
          <div class="settings-actions settings-actions-sm">
            <button class="btn" id="authEditCancel">Cancel</button>
            <button class="btn btn-primary" id="authEditSave">Save</button>
          </div>
        </div>`;
    var dlg = _createDialog("truthOverlay", "Trust", body, "trust-panel", function() { _truthEditing = null; });
    overlay = dlg.overlay;

    document.getElementById("truthClose").addEventListener("click", dlg.close);

    document.getElementById("truthAdd").addEventListener("click", function() {
      _truthEditing = "new";
      document.getElementById("truthTitle").value = "";
      document.getElementById("truthCertainty").value = "0.5";
      document.getElementById("truthContent").value = "<p></p>";
      _truthShowEditView();
    });

    document.getElementById("truthEditCancel").addEventListener("click", function() {
      _truthEditing = null;
      _truthShowListView();
    });

    document.getElementById("truthEditSave").addEventListener("click", function() {
      const title = document.getElementById("truthTitle").value.trim() || "Untitled";
      const certainty = Math.min(1, Math.max(-1, parseFloat(document.getElementById("truthCertainty").value) || 0));
      const content = document.getElementById("truthContent").value.trim() || "<p/>";
      const now = new Date().toISOString().replace(/\.\d+Z$/, "Z");

      if (_truthEditing === "new") {
        const entry = { id: tempId("t_"), title: title, certainty: certainty, content: content, time: now };
        state.truth.trust.push(entry);
      } else if (typeof _truthEditing === "number") {
        const entry = state.truth.trust[_truthEditing];
        if (entry) {
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

    // ─── Implication editor handlers ───
    document.getElementById("truthAddImpl").addEventListener("click", function() {
      _truthEditing = "new_impl";
      document.getElementById("implTitle").value = "";
      document.getElementById("implCertainty").value = "0.5";
      document.getElementById("implType").value = "material";
      _populateImplDropdowns();
      _truthShowImplView();
    });

    document.getElementById("implEditCancel").addEventListener("click", function() {
      _truthEditing = null;
      _truthShowListView();
    });

    document.getElementById("implEditSave").addEventListener("click", function() {
      const title = document.getElementById("implTitle").value.trim() || "Untitled implication";
      const ant = document.getElementById("implAntecedent").value;
      const con = document.getElementById("implConsequent").value;
      const certainty = Math.min(1, Math.max(-1, parseFloat(document.getElementById("implCertainty").value) || 0));
      const implType = document.getElementById("implType").value;
      const now = new Date().toISOString().replace(/\.\d+Z$/, "Z");

      if (!ant || !con) {
        const input = document.getElementById("msgInput");
        const savedPH = input.placeholder;
        input.placeholder = "Select both antecedent and consequent";
        setTimeout(() => { input.placeholder = savedPH; }, 3000);
        return;
      }

      const content = "<implication><antecedent>" + ant + "</antecedent><consequent>" + con + "</consequent><type>" + implType + "</type></implication>";

      if (_truthEditing === "new_impl") {
        const entry = { id: tempId("i_"), title: title, certainty: certainty, content: content, time: now };
        state.truth.trust.push(entry);
      } else if (typeof _truthEditing === "number") {
        const entry = state.truth.trust[_truthEditing];
        if (entry) {
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

    // ─── Authority editor handlers ───
    document.getElementById("truthAddAuth").addEventListener("click", function() {
      _truthEditing = "new_auth";
      document.getElementById("authTitle").value = "";
      document.getElementById("authDid").value = "";
      document.getElementById("authOrcid").value = "";
      document.getElementById("authUrl").value = "";
      document.getElementById("authCertainty").value = "0.5";
      document.getElementById("authRefresh").value = "3600";
      _truthShowAuthView();
    });

    document.getElementById("authEditCancel").addEventListener("click", function() {
      _truthEditing = null;
      _truthShowListView();
    });

    document.getElementById("authEditSave").addEventListener("click", function() {
      const title = document.getElementById("authTitle").value.trim() || "Untitled authority";
      const did = document.getElementById("authDid").value.trim();
      const orcid = document.getElementById("authOrcid").value.trim();
      const url = document.getElementById("authUrl").value.trim();
      const certainty = Math.min(1, Math.max(-1, parseFloat(document.getElementById("authCertainty").value) || 0));
      const refresh = parseInt(document.getElementById("authRefresh").value) || 3600;
      const now = new Date().toISOString().replace(/\.\d+Z$/, "Z");

      if (!url) {
        const input = document.getElementById("msgInput");
        const savedPH = input.placeholder;
        input.placeholder = "URL to remote trust table is required";
        setTimeout(() => { input.placeholder = savedPH; }, 3000);
        return;
      }

      if (!did && !orcid) {
        const input = document.getElementById("msgInput");
        const savedPH = input.placeholder;
        input.placeholder = "At least one of DID or ORCID is required";
        setTimeout(() => { input.placeholder = savedPH; }, 3000);
        return;
      }

      var attrs = "";
      if (did) attrs += ' did="' + did.replace(/"/g, "&quot;") + '"';
      if (orcid) attrs += ' orcid="' + orcid.replace(/"/g, "&quot;") + '"';
      attrs += ' url="' + url.replace(/"/g, "&quot;") + '"';
      if (refresh !== 3600) attrs += ' refresh="' + refresh + '"';
      const content = "<authority" + attrs + " />";

      if (_truthEditing === "new_auth") {
        const entry = { id: tempId("a_"), title: title, certainty: certainty, content: content, time: now };
        state.truth.trust.push(entry);
      } else if (typeof _truthEditing === "number") {
        const entry = state.truth.trust[_truthEditing];
        if (entry) {
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

function _truthShowListView() {
  document.getElementById("truthListView").style.display = "";
  document.getElementById("truthEditView").style.display = "none";
  document.getElementById("truthImplView").style.display = "none";
  document.getElementById("truthAuthView").style.display = "none";
}

function _truthShowEditView() {
  document.getElementById("truthListView").style.display = "none";
  document.getElementById("truthEditView").style.display = "";
  document.getElementById("truthImplView").style.display = "none";
  document.getElementById("truthAuthView").style.display = "none";
  document.getElementById("truthTitle").focus();
}

function _truthShowImplView() {
  document.getElementById("truthListView").style.display = "none";
  document.getElementById("truthEditView").style.display = "none";
  document.getElementById("truthImplView").style.display = "";
  document.getElementById("truthAuthView").style.display = "none";
  document.getElementById("implTitle").focus();
}

function _truthShowAuthView() {
  document.getElementById("truthListView").style.display = "none";
  document.getElementById("truthEditView").style.display = "none";
  document.getElementById("truthImplView").style.display = "none";
  document.getElementById("truthAuthView").style.display = "";
  document.getElementById("authTitle").focus();
}

function _isImplication(entry) {
  return entry && typeof entry.content === "string" && entry.content.indexOf("<implication") !== -1;
}

function _isAuthority(entry) {
  return entry && typeof entry.content === "string" && entry.content.indexOf("<authority") !== -1;
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

function _parseImplContent(content) {
  try {
    var parser = new DOMParser();
    var doc = parser.parseFromString("<root>" + content + "</root>", "text/xml");
    var impl = doc.querySelector("implication");
    if (!impl) return null;
    var ant = impl.querySelector("antecedent");
    var con = impl.querySelector("consequent");
    var typ = impl.querySelector("type");
    return {
      antecedent: ant ? ant.textContent.trim() : "",
      consequent: con ? con.textContent.trim() : "",
      type: typ ? typ.textContent.trim() : "material"
    };
  } catch (e) { return null; }
}

function _populateImplDropdowns(selectedAnt, selectedCon) {
  var entries = (state.truth && state.truth.trust) || [];
  var antSel = document.getElementById("implAntecedent");
  var conSel = document.getElementById("implConsequent");
  antSel.innerHTML = "";
  conSel.innerHTML = "";
  var blankA = document.createElement("option");
  blankA.value = ""; blankA.textContent = "— select —";
  antSel.appendChild(blankA);
  var blankC = document.createElement("option");
  blankC.value = ""; blankC.textContent = "— select —";
  conSel.appendChild(blankC);
  for (var i = 0; i < entries.length; i++) {
    var e = entries[i];
    if (_isImplication(e) || _isAuthority(e)) continue; // skip structural entries
    var opt1 = document.createElement("option");
    opt1.value = e.id;
    opt1.textContent = e.id + " — " + truncate(e.title || "(untitled)", 30);
    if (e.id === selectedAnt) opt1.selected = true;
    antSel.appendChild(opt1);
    var opt2 = document.createElement("option");
    opt2.value = e.id;
    opt2.textContent = e.id + " — " + truncate(e.title || "(untitled)", 30);
    if (e.id === selectedCon) opt2.selected = true;
    conSel.appendChild(opt2);
  }
}

function _truthRenderList() {
  const container = document.getElementById("truthEntries");
  container.innerHTML = "";
  const entries = (state.truth && state.truth.trust) || [];

  if (entries.length === 0) {
    container.innerHTML = '<div class="trust-empty">No trust entries. Use <b>Add Entry</b> or <b>Open</b> a .jsonl file.</div>';
    return;
  }

  for (let i = 0; i < entries.length; i++) {
    const entry = entries[i];
    const isImpl = _isImplication(entry);
    const isAuth = _isAuthority(entry);
    const row = document.createElement("div");
    row.style.cssText = "display:flex; align-items:center; gap:0.5rem; padding:0.35rem 0; border-bottom:1px solid var(--border); font-size:0.82rem;";

    if (isAuth) {
      // Authority entry: show shield icon and DID/URL
      const authData = _parseAuthContent(entry.content);
      const badge = document.createElement("span");
      badge.textContent = "\u229e";
      badge.title = "Authority" + (authData && authData.did ? " (" + authData.did + ")" : "");
      badge.style.cssText = "min-width:3.2em; text-align:center; font-size:1rem; color:#7c3aed;";
      row.appendChild(badge);

      const label = document.createElement("span");
      label.style.cssText = "flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;";
      if (authData) {
        var identifier = authData.did || authData.orcid || "";
        label.textContent = truncate(entry.title || identifier, 36);
        label.title = (authData.did ? "DID: " + authData.did + "\n" : "") + (authData.orcid ? "ORCID: " + authData.orcid + "\n" : "") + "URL: " + authData.url;
      } else {
        label.textContent = truncate(entry.title || "(authority)", 36);
      }
      row.appendChild(label);

      const certSpan = document.createElement("span");
      const ac = entry.certainty || 0;
      certSpan.textContent = "c=" + (ac >= 0 ? "+" : "") + ac.toFixed(2);
      certSpan.style.cssText = "font-family:ui-monospace,monospace; font-size:0.72rem; color:var(--fg-muted);";
      row.appendChild(certSpan);
    } else if (isImpl) {
      // Implication entry: show → icon and antecedent/consequent
      const implData = _parseImplContent(entry.content);
      const badge = document.createElement("span");
      badge.textContent = "\u2192";
      badge.title = "Implication (" + (implData ? implData.type : "material") + ")";
      badge.style.cssText = "min-width:3.2em; text-align:center; font-size:1rem; color:var(--accent);";
      row.appendChild(badge);

      const label = document.createElement("span");
      label.style.cssText = "flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;";
      if (implData) {
        label.textContent = implData.antecedent + " \u2192 " + implData.consequent;
        label.title = entry.title || "";
      } else {
        label.textContent = truncate(entry.title || "(implication)", 36);
      }
      row.appendChild(label);

      // Show derived certainty of consequent if available
      if (implData) {
        const derivedSpan = document.createElement("span");
        var conEntry = entries.find(function(e) { return e.id === implData.consequent; });
        if (conEntry) {
          var dc = conEntry._derived_certainty != null ? conEntry._derived_certainty : conEntry.certainty;
          derivedSpan.textContent = "c=" + (dc >= 0 ? "+" : "") + dc.toFixed(2);
          derivedSpan.style.cssText = "font-family:ui-monospace,monospace; font-size:0.72rem; color:var(--fg-muted);";
        }
        row.appendChild(derivedSpan);
      }
    } else {
      // Regular trust entry
      const cert = document.createElement("span");
      const c = entry.certainty || 0;
      const dc = entry._derived_certainty;
      var certText = (c >= 0 ? "+" : "") + c.toFixed(2);
      if (dc != null && Math.abs(dc - c) > 1e-9) {
        certText += "\u2192" + (dc >= 0 ? "+" : "") + dc.toFixed(2);
      }
      cert.textContent = certText;
      cert.style.cssText = "min-width:3.2em; text-align:right; font-family:ui-monospace,monospace; font-size:0.78rem; color:" + (c > 0 ? "var(--accent)" : c < 0 ? "#dc2626" : "var(--fg-muted)") + ";";
      if (dc != null && Math.abs(dc - c) > 1e-9) cert.title = "Stored: " + c.toFixed(2) + ", Derived: " + dc.toFixed(2);
      row.appendChild(cert);

      const title = document.createElement("span");
      title.textContent = truncate(entry.title || "(untitled)", 36);
      title.style.cssText = "flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;";
      row.appendChild(title);
    }

    const editBtn = document.createElement("button");
    editBtn.textContent = "Edit";
    editBtn.className = "btn";
    editBtn.style.cssText = "font-size:0.72rem; padding:0.15rem 0.5rem;";
    editBtn.addEventListener("click", (function(idx, entryIsImpl, entryIsAuth) {
      return function() {
        _truthEditing = idx;
        const e = state.truth.trust[idx];
        if (entryIsAuth) {
          const authData = _parseAuthContent(e.content);
          document.getElementById("authTitle").value = e.title || "";
          document.getElementById("authDid").value = (authData && authData.did) || "";
          document.getElementById("authOrcid").value = (authData && authData.orcid) || "";
          document.getElementById("authUrl").value = (authData && authData.url) || "";
          document.getElementById("authCertainty").value = e.certainty || 0;
          document.getElementById("authRefresh").value = (authData && authData.refresh) || 3600;
          _truthShowAuthView();
        } else if (entryIsImpl) {
          const implData = _parseImplContent(e.content);
          document.getElementById("implTitle").value = e.title || "";
          document.getElementById("implCertainty").value = e.certainty || 0;
          document.getElementById("implType").value = (implData && implData.type) || "material";
          _populateImplDropdowns(implData && implData.antecedent, implData && implData.consequent);
          _truthShowImplView();
        } else {
          document.getElementById("truthTitle").value = e.title || "";
          document.getElementById("truthCertainty").value = e.certainty || 0;
          document.getElementById("truthContent").value = stripTags(e.content || "").trim() ? (e.content || "") : "<p></p>";
          _truthShowEditView();
        }
      };
    })(i, isImpl, isAuth));
    row.appendChild(editBtn);

    const delBtn = document.createElement("button");
    delBtn.textContent = "Del";
    delBtn.className = "btn";
    delBtn.style.cssText = "font-size:0.72rem; padding:0.15rem 0.5rem; color:#dc2626;";
    delBtn.addEventListener("click", (function(idx) {
      return function() {
        const e = state.truth.trust[idx];
        if (confirmAction("Delete " + (_isImplication(e) ? "implication" : "trust entry") + " \"" + (e.title || "untitled") + "\"?")) {
          state.truth.trust.splice(idx, 1);
          _persistState();
          _truthRenderList();
        }
      };
    })(i));
    row.appendChild(delBtn);

    container.appendChild(row);
  }
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
