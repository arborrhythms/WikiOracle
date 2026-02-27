// util.js — Shared utilities for WikiOracle front-end
// Loaded before d3tree.js and wikioracle.js.

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
  if (opts.wheelPan) {
    zoom.filter(function(event) {
      if (event.type === "wheel") return event.ctrlKey; // only pinch-zoom
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
