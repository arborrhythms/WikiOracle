// util.js — Shared utilities for WikiOracle front-end
// Loaded before d3tree.js and wikioracle.js.

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

function onDoubleTap(element, callback, threshold) {
  if (!threshold) threshold = 350;
  var lastTap = 0;
  element.addEventListener("touchend", function(e) {
    var now = Date.now();
    if (now - lastTap < threshold) {
      e.preventDefault();
      var touch = e.changedTouches && e.changedTouches[0];
      var synth = touch
        ? { clientX: touch.clientX, clientY: touch.clientY,
            pageX: touch.pageX, pageY: touch.pageY,
            target: e.target,
            preventDefault: function() {}, stopPropagation: function() {} }
        : e;
      callback(synth, e);
      lastTap = 0;
    } else {
      lastTap = now;
    }
  });
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

  opts.container.call(zoom)
    .on("dblclick.zoom", null); // disable d3's default double-click zoom

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

  if (resetOn) {
    var resetTo = opts.resetTransform || d3.zoomIdentity;
    var isCallback = typeof opts.resetOnDblclick === "function";

    function _handleBgDblclick() {
      if (isCallback) {
        var curT = d3.zoomTransform(opts.container.node());
        opts.resetOnDblclick(zoom, curT);
      } else {
        opts.container.transition().duration(300)
          .call(zoom.transform, resetTo);
      }
    }

    // Desktop: double-click on empty area
    opts.container.on("dblclick", function(event) {
      if (event.target === resetTarget) {
        _handleBgDblclick();
      }
    });
    // Mobile: double-tap on empty area
    var bgLastTap = 0;
    opts.container.on("touchend.resetzoom", function(event) {
      if (event.target !== resetTarget) return;
      var now = Date.now();
      if (now - bgLastTap < 350) {
        event.preventDefault();
        _handleBgDblclick();
        bgLastTap = 0;
      } else {
        bgLastTap = now;
      }
    });
  }

  return zoom;
}
