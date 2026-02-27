// d3tree.js — D3.js top-down branching hierarchy for WikiOracle
// State IS the tree (conversations with children).
// Supports: click (navigate), double-click/double-tap (context menu), right-click.
// Tree operations (cut/copy/paste, branch, delete) via context menu.
//
// Data flow:
//   conversationsToHierarchy(conversations, selectedId) -> D3 hierarchy data
//   renderTree(hierarchyData, callbacks) -> SVG in #treeContainer
//
// Layout: d3.tree(), top-down (root at top). Separation 1.2x siblings, 1.8x cousins.
// Colours from CSS custom properties: --accent, --accent-light, --border, --fg,
//   --fg-muted, --bg.
//
// Node shapes:
//   Root       -> circle r=14
//   Selected   -> rounded rect, two-line label (title + "N Qs, M msgs")
//   Default    -> pill (fully rounded rect), single-line truncated title
//
// Interactions:
//   Click -> callbacks.onNavigate(id)
//   Double-click / double-tap / right-click -> context menu (Cut, Copy, Paste, Branch, Delete)
//   Ctrl/meta-click -> context menu

// Internal state
let _doubleTapHandled = false; // suppresses click after double-tap fires context menu
// Shared state object for onDoubleTap — persists across re-renders so a
// navigate-triggered re-render between the two taps doesn't reset the timer.
const _tapState = { time: 0, key: null };
let _savedTransform = null; // persists zoom/pan across re-renders
let _focusOnSelected = false; // when true, next render pans to selected node

// Kept across renders for background-dblclick zoom toggle
let _fitTransform = null;    // d3.zoomIdentity.translate(…).scale(fitScale)
let _zoomInstance = null;     // the d3.zoom() object
let _treeRoot = null;         // d3.hierarchy root
let _treeMargin = null;       // { top, right, bottom, left }
let _treeSvgW = 0;
let _treeSvgH = 0;

/**
 * Convert conversations tree to D3 hierarchy data.
 */
function conversationsToHierarchy(conversations, selectedId) {
  function mapConv(conv) {
    const msgs = conv.messages || [];
    const qCount = msgs.filter(m => m.role === "user").length;
    const childNodes = (conv.children || []).map(mapConv);
    return {
      id: conv.id,
      title: conv.title || "(untitled)",
      messageCount: msgs.length,
      questionCount: qCount,
      messages: msgs,
      selected: conv.id === selectedId,
      children: childNodes.length > 0 ? childNodes : undefined,
    };
  }
  const rootChildren = (conversations || []).map(mapConv);
  return {
    id: "root",
    title: "/",
    messageCount: 0,
    questionCount: 0,
    messages: [],
    selected: selectedId === null,
    children: rootChildren.length > 0 ? rootChildren : undefined,
  };
}

/**
 * Render the conversation tree as a top-down branching hierarchy.
 * @param {object} hierarchyData — output of conversationsToHierarchy
 * @param {{ onNavigate, onBranch, onDelete, onCut, onCopy, onPaste }} callbacks
 */
function renderTree(hierarchyData, callbacks) {
  const container = document.getElementById("treeContainer");
  if (!container || typeof d3 === "undefined") return;

  const svgEl = container.querySelector("svg");
  if (!svgEl) return;

  // Use container dimensions (not SVG) — SVG may have auto sizing
  const width = container.clientWidth || 600;
  const height = container.clientHeight || 200;

  // Remove legacy tooltip if present
  var oldTip = container.querySelector(".tree-tooltip");
  if (oldTip) oldTip.remove();

  // CSS vars (via shared cssVar from util.js)
  const accent = cssVar("--accent", "#2563eb");
  const accentLight = cssVar("--accent-light", "#dbeafe");
  const border = cssVar("--border", "#e5e7eb");
  const fg = cssVar("--fg", "#111827");
  const fgMuted = cssVar("--fg-muted", "#6b7280");
  const bg = cssVar("--bg", "#ffffff");

  // Build hierarchy
  const root = d3.hierarchy(hierarchyData);

  const margin = { top: 20, right: 20, bottom: 20, left: 20 };

  // Size tree to its content — nodes only need enough space for clean edges
  const leaves = root.leaves().length || 1;
  const depthCount = root.height;
  const needW = leaves * 100;                  // ~100px per leaf for breadth
  const needH = (depthCount + 1) * 60;        // ~60px per depth level

  const treeLayout = d3.tree()
    .size([needW, needH])
    .separation((a, b) => (a.parent === b.parent ? 1.2 : 1.8));
  treeLayout(root);

  // Content box
  const contentW = needW + margin.left + margin.right;
  const contentH = needH + margin.top + margin.bottom;

  // SVG is always sized to the container — zoom/pan handles navigation
  const svgW = width;
  const svgH = height;

  // Preserve zoom/pan state before clearing SVG
  const svg = d3.select(svgEl);
  const prev = d3.zoomTransform(svgEl);
  if (prev.k !== 1 || prev.x !== 0 || prev.y !== 0) {
    _savedTransform = prev;
  }

  // Clear and draw
  svg.selectAll("*").remove();
  svg.attr("viewBox", `0 0 ${svgW} ${svgH}`)
     .attr("width", svgW).attr("height", svgH);

  // Invisible background rect — guarantees a pointer-event target for taps on
  // empty space.  Without this, mobile touch hit-testing on an unfilled <svg>
  // may return a child <g> (or nothing), so the double-tap zoom toggle never
  // matches resetTarget.  Painted before zoomG so nodes draw on top.
  const bgRect = svg.append("rect")
    .attr("width", svgW).attr("height", svgH)
    .attr("fill", "transparent")
    .attr("pointer-events", "all")
    .node();

  // Zoom container — wraps all tree content for pinch/scroll zoom
  const zoomG = svg.append("g");
  const g = zoomG.append("g")
    .attr("transform", `translate(${margin.left},${margin.top})`);

  // Compute zoom-to-fit transform (used for initial view + double-click reset)
  const fitScaleX = (svgW - margin.left - margin.right) / contentW;
  const fitScaleY = (svgH - margin.top - margin.bottom) / contentH;
  const fitScale = Math.min(fitScaleX, fitScaleY, 1); // never zoom in beyond 1:1
  const fitTx = (svgW - contentW * fitScale) / 2;
  const fitTy = (svgH - contentH * fitScale) / 2;
  const fitTransform = d3.zoomIdentity.translate(fitTx, fitTy).scale(fitScale);

  // Stash for background-dblclick zoom toggle
  _fitTransform = fitTransform;
  _treeRoot = root;
  _treeMargin = margin;
  _treeSvgW = svgW;
  _treeSvgH = svgH;

  // d3.zoom for pinch-zoom and scroll-zoom on the tree (shared setupZoom from util.js)
  // Double-click on empty area toggles between zoom-to-fit and zoom-to-selected.
  const zoom = setupZoom({
    container: svg,
    target: zoomG.node(),
    mode: "svg",
    scaleExtent: [0.05, 4],
    wheelPan: true,           // two-finger scroll pans; pinch zooms
    resetOnDblclick: function(zoomObj, curT) {
      _dblclickZoomToggle(svg, zoomObj, curT);
    },
    resetTarget: bgRect,
    resetTransform: fitTransform
  });

  _zoomInstance = zoom;

  // Restore zoom or pan to selected node (keyboard navigation)
  if (_focusOnSelected) {
    const selNode = root.descendants().find(d => d.data.selected);
    const k = _savedTransform ? _savedTransform.k : fitScale;
    if (selNode) {
      const tx = svgW / 2 - (margin.left + selNode.x) * k;
      const ty = svgH / 2 - (margin.top + selNode.y) * k;
      svg.call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(k));
    } else {
      svg.call(zoom.transform, _savedTransform || fitTransform);
    }
    _focusOnSelected = false;
  } else {
    svg.call(zoom.transform, _savedTransform || fitTransform);
  }

  // Links — curved top-down
  g.selectAll(".conv-link")
    .data(root.links())
    .join("path")
    .attr("class", "conv-link")
    .attr("d", d => {
      const sx = d.source.x, sy = d.source.y;
      const tx = d.target.x, ty = d.target.y;
      const my = (sy + ty) / 2;
      return `M${sx},${sy} C${sx},${my} ${tx},${my} ${tx},${ty}`;
    })
    .attr("fill", "none")
    .attr("stroke", border)
    .attr("stroke-width", 1.5);

  // Nodes
  const node = g.selectAll(".conv-node")
    .data(root.descendants())
    .join("g")
    .attr("class", "conv-node")
    .attr("transform", d => `translate(${d.x},${d.y})`)
    .style("cursor", "pointer");

  // Draw each node shape
  node.each(function(d) {
    const el = d3.select(this);
    const isRoot = d.data.id === "root";
    const isSel = d.data.selected;

    if (isRoot) {
      el.append("circle")
        .attr("class", "node-shape")
        .attr("r", 14)
        .attr("fill", isSel ? accentLight : bg)
        .attr("stroke", isSel ? accent : border)
        .attr("stroke-width", 2);
      el.append("text")
        .attr("text-anchor", "middle")
        .attr("dy", "0.35em")
        .attr("font-size", "12px")
        .attr("font-weight", "600")
        .attr("fill", isSel ? accent : fgMuted)
        .attr("pointer-events", "none")
        .text("/");
    } else if (isSel) {
      const label = d.data.title || "(untitled)";
      const detail = d.data.questionCount + " Q" + (d.data.questionCount !== 1 ? "s" : "") + ", " + d.data.messageCount + " msgs";
      const boxW = Math.min(Math.max(label.length * 6.5 + 24, 90), 200);
      const boxH = 40;
      el.append("rect")
        .attr("class", "node-shape")
        .attr("x", -boxW / 2).attr("y", -boxH / 2)
        .attr("width", boxW).attr("height", boxH)
        .attr("rx", 8)
        .attr("fill", accentLight)
        .attr("stroke", accent)
        .attr("stroke-width", 2);
      el.append("text")
        .attr("text-anchor", "middle")
        .attr("dy", "-0.15em")
        .attr("font-size", "10px")
        .attr("font-weight", "600")
        .attr("fill", fg)
        .attr("pointer-events", "none")
        .text(label.length > 26 ? label.slice(0, 24) + "..." : label);
      el.append("text")
        .attr("text-anchor", "middle")
        .attr("dy", "1.15em")
        .attr("font-size", "8px")
        .attr("fill", fgMuted)
        .attr("pointer-events", "none")
        .text(detail);
    } else {
      const label = d.data.title || "";
      const short = label.length > 20 ? label.slice(0, 18) + ".." : label;
      const pillW = Math.max(short.length * 5.5 + 16, 44);
      const pillH = 22;
      el.append("rect")
        .attr("class", "node-shape")
        .attr("x", -pillW / 2).attr("y", -pillH / 2)
        .attr("width", pillW).attr("height", pillH)
        .attr("rx", pillH / 2)
        .attr("fill", bg)
        .attr("stroke", border)
        .attr("stroke-width", 1);
      el.append("text")
        .attr("text-anchor", "middle")
        .attr("dy", "0.35em")
        .attr("font-size", "9px")
        .attr("fill", fgMuted)
        .attr("pointer-events", "none")
        .text(short);
    }
  });

  // Raise selected node to top of SVG z-order so it isn't overlaid by siblings
  node.filter(d => d.data.selected).raise();

  // ─── Click: navigate; ctrl-click → context menu ───
  node.on("click", function(event, d) {
    // If touchend.doubletap just opened a context menu, don't let this click close it.
    if (_doubleTapHandled) {
      _tapLog("node-click", "SUPPRESSED (doubleTapHandled) id=" + d.data.id);
      _doubleTapHandled = false;
      event.stopPropagation();
      return;
    }
    _tapLog("node-click", "id=" + d.data.id, event.type);
    event.preventDefault();
    event.stopPropagation();
    _hideContextMenu();

    // Ctrl-click / meta-click → context menu (any node)
    if (event.ctrlKey || event.metaKey) {
      _triggerContextMenu(event, d);
      return;
    }

    // Navigate (root → null, else → node id)
    if (callbacks.onNavigate) callbacks.onNavigate(d.data.id === "root" ? null : d.data.id);
  });

  // Double-click opens context menu
  node.on("dblclick", function(event, d) {
    event.preventDefault();
    event.stopPropagation();
    _triggerContextMenu(event, d);
  });

  // Touch double-tap detection (dblclick doesn't fire on most mobile browsers).
  // Uses module-level _tapState so the timer survives navigate-triggered re-renders.
  // onFire sets _doubleTapHandled so the subsequent click event bails out instead
  // of calling _hideContextMenu() and closing the menu we're about to open
  // (on desktop the native dblclick re-opens it; on mobile there's no dblclick).
  onDoubleTap(node, function(synth, raw) {
    // d3 binds datum to `this` inside .on(); for onDoubleTap with namespace
    // the handler runs via selection.on() so `this` is the DOM node.
    // Recover the d3 datum to pass to _triggerContextMenu.
    var d = d3.select(raw.currentTarget || raw.target).datum();
    _triggerContextMenu(synth, d);
  }, {
    namespace: "doubletap",
    state: _tapState,
    key: function(e) {
      var d = d3.select(e.currentTarget || e.target).datum();
      return d && d.data ? d.data.id : "";
    },
    onFire: function() { _doubleTapHandled = true; }
  });

  function _triggerContextMenu(event, d) {
    if (d.data.id === "root") {
      _showRootContextMenu(event, callbacks);
    } else {
      _showContextMenu(event, d.data, callbacks, container);
    }
  }

  // ─── Right-click: also context menu (desktop) ───
  node.on("contextmenu", function(event, d) {
    event.preventDefault();
    event.stopPropagation();
    _triggerContextMenu(event, d);
  });

  // Close context menu when clicking outside of it (with grace period)
  d3.select(document).on("click.tree-ctx", function(event) {
    if (_ctxMenu && !_ctxMenu.contains(event.target) && !_ctxMenu._justOpened) {
      _tapLog("doc-click", "closing menu (target=" + event.target.tagName + ")");
      _hideContextMenu();
    } else if (_ctxMenu) {
      _tapLog("doc-click", "menu kept (contains=" + _ctxMenu.contains(event.target) + " justOpened=" + _ctxMenu._justOpened + ")");
    }
  });

}

/**
 * Toggle zoom on background double-click/double-tap.
 *
 * If currently zoomed-out (at or near fit scale), zoom in to center the
 * selected node at a legible magnification (scale ≈ 1.0).
 * If currently zoomed-in, zoom back out to fit the whole tree.
 */
function _dblclickZoomToggle(svg, zoomObj, curT) {
  if (!_fitTransform || !_treeRoot) return;

  var fitK = _fitTransform.k;
  // "Near fit" = within 10% of the fit scale
  var atFit = Math.abs(curT.k - fitK) / fitK < 0.10;

  if (atFit || curT.k <= fitK) {
    // Zoom IN to the selected node at legible scale
    var selNode = _treeRoot.descendants().find(function(d) { return d.data.selected; });
    if (!selNode) {
      // Fallback: just zoom to fit
      svg.transition().duration(300).call(zoomObj.transform, _fitTransform);
      return;
    }
    // Target scale: 1.0 (1:1 pixels) but at least fitK (don't zoom out)
    var targetK = Math.max(1.0, fitK);
    var tx = _treeSvgW / 2 - (_treeMargin.left + selNode.x) * targetK;
    var ty = _treeSvgH / 2 - (_treeMargin.top + selNode.y) * targetK;
    var zoomIn = d3.zoomIdentity.translate(tx, ty).scale(targetK);
    svg.transition().duration(300).call(zoomObj.transform, zoomIn);
  } else {
    // Zoom OUT to fit the whole tree
    svg.transition().duration(300).call(zoomObj.transform, _fitTransform);
  }
}

/**
 * Request that the next renderTree() pans to center the selected node.
 * Call before navigateToNode() for keyboard-driven navigation.
 */
function treeRequestFocus() {
  _focusOnSelected = true;
}

// ─── Context menu helpers ───
let _ctxMenu = null;

function _hideContextMenu() {
  if (_ctxMenu) {
    _ctxMenu.remove();
    _ctxMenu = null;
  }
  // Also dismiss chat-pane context menu if present
  if (typeof _hideMsgContextMenu === "function") _hideMsgContextMenu();
}

function _showRootContextMenu(event, callbacks) {
  _hideContextMenu();

  var menu = document.createElement("div");
  menu.className = "tree-context-menu";
  menu.style.position = "fixed";
  menu.style.left = (event.clientX + 4) + "px";
  menu.style.top = (event.clientY + 4) + "px";

  menu._justOpened = true;
  setTimeout(function() { menu._justOpened = false; }, 300);

  // Paste at root level (only if clipboard holds a conversation)
  if (callbacks.hasClipboard && callbacks.hasClipboard()) {
    var pasteItem = document.createElement("div");
    pasteItem.className = "ctx-item";
    pasteItem.textContent = "Paste";
    pasteItem.addEventListener("click", function(e) {
      e.stopPropagation(); _hideContextMenu();
      if (callbacks.onPaste) callbacks.onPaste("root");
    });
    menu.appendChild(pasteItem);

    var sep0 = document.createElement("div");
    sep0.className = "ctx-sep";
    menu.appendChild(sep0);
  }

  var ctxItem = document.createElement("div");
  ctxItem.className = "ctx-item";
  ctxItem.textContent = "Context\u2026";
  ctxItem.addEventListener("click", function(e) {
    e.stopPropagation(); _hideContextMenu();
    if (callbacks.onEditContext) callbacks.onEditContext();
  });
  menu.appendChild(ctxItem);

  var truthItem = document.createElement("div");
  truthItem.className = "ctx-item";
  truthItem.textContent = "Trust\u2026";
  truthItem.addEventListener("click", function(e) {
    e.stopPropagation(); _hideContextMenu();
    if (callbacks.onEditTruth) callbacks.onEditTruth();
  });
  menu.appendChild(truthItem);

  var sep = document.createElement("div");
  sep.className = "ctx-sep";
  menu.appendChild(sep);

  var deleteAllItem = document.createElement("div");
  deleteAllItem.className = "ctx-item ctx-danger";
  deleteAllItem.textContent = "Delete All";
  deleteAllItem.addEventListener("click", function(e) {
    e.stopPropagation(); _hideContextMenu();
    if (callbacks.onDeleteAll) callbacks.onDeleteAll();
  });
  menu.appendChild(deleteAllItem);

  document.body.appendChild(menu);
  _ctxMenu = menu;
}


// Context menu: appended to document.body with position:fixed to avoid
// clipping by the tree container's overflow:hidden. The _justOpened flag
// with a 300ms grace period prevents the document-level click handler
// from immediately closing the menu on the same event.
function _showContextMenu(event, nodeData, callbacks, container) {
  _hideContextMenu();

  var menu = document.createElement("div");
  menu.className = "tree-context-menu";
  menu.style.position = "fixed";
  menu.style.left = (event.clientX + 4) + "px";
  menu.style.top = (event.clientY + 4) + "px";

  // Prevent the initial event from closing the menu
  menu._justOpened = true;
  setTimeout(function() { menu._justOpened = false; }, 300);

  // Cut
  var cutItem = document.createElement("div");
  cutItem.className = "ctx-item";
  cutItem.textContent = "Cut";
  cutItem.addEventListener("click", function(e) {
    e.stopPropagation(); _hideContextMenu();
    if (callbacks.onCut) callbacks.onCut(nodeData.id);
  });
  menu.appendChild(cutItem);

  // Copy (copies text + sets clipboard for paste-to-duplicate)
  var copyItem = document.createElement("div");
  copyItem.className = "ctx-item";
  copyItem.textContent = "Copy";
  copyItem.addEventListener("click", function(e) {
    e.stopPropagation(); _hideContextMenu();
    if (callbacks.onCopy) callbacks.onCopy(nodeData.id);
  });
  menu.appendChild(copyItem);

  // Paste (only if clipboard holds a conversation)
  if (callbacks.hasClipboard && callbacks.hasClipboard()) {
    var pasteItem = document.createElement("div");
    pasteItem.className = "ctx-item";
    pasteItem.textContent = "Paste";
    pasteItem.addEventListener("click", function(e) {
      e.stopPropagation(); _hideContextMenu();
      if (callbacks.onPaste) callbacks.onPaste(nodeData.id);
    });
    menu.appendChild(pasteItem);
  }

  // Delete
  var deleteItem = document.createElement("div");
  deleteItem.className = "ctx-item ctx-danger";
  deleteItem.textContent = "Delete";
  deleteItem.addEventListener("click", function(e) {
    e.stopPropagation(); _hideContextMenu();
    if (callbacks.onDelete) callbacks.onDelete(nodeData.id);
  });
  menu.appendChild(deleteItem);

  var sep = document.createElement("div");
  sep.className = "ctx-sep";
  menu.appendChild(sep);

  // Branch
  var branchItem = document.createElement("div");
  branchItem.className = "ctx-item";
  branchItem.textContent = "Branch\u2026";
  branchItem.addEventListener("click", function(e) {
    e.stopPropagation(); _hideContextMenu();
    if (callbacks.onBranch) callbacks.onBranch(nodeData.id);
  });
  menu.appendChild(branchItem);

  document.body.appendChild(menu);
  _ctxMenu = menu;
}
