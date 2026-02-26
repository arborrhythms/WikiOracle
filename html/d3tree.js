// d3tree.js — D3.js top-down branching hierarchy for WikiOracle
// State IS the tree (conversations with children).
// Supports: click (navigate), double-click/double-tap (context menu), right-click,
//           drag-and-drop (merge: reparent dragged node under drop target).
//
// Data flow:
//   conversationsToHierarchy(conversations, selectedId) -> D3 hierarchy data
//   renderTree(hierarchyData, callbacks) -> SVG in #treeContainer
//
// Layout: d3.tree(), top-down (root at top). Separation 1.2x siblings, 1.8x cousins.
// Colours from CSS custom properties: --accent, --accent-light, --border, --fg,
//   --fg-muted, --bg. Merge target highlight: amber #f59e0b.
//
// Node shapes:
//   Root       -> circle r=14
//   Selected   -> rounded rect, two-line label (title + "N Qs, M msgs")
//   Default    -> pill (fully rounded rect), single-line truncated title
//
// Interactions:
//   Click (200ms timer) -> callbacks.onNavigate(id)
//   Double-click (cancels click timer) -> context menu (Branch, Delete)
//   Right-click -> same context menu
//   Drag (left button, non-root) -> highlight nearest valid target within 30px
//   Drop (excludes self + descendants) -> confirm -> callbacks.onMerge(src, tgt)
//   Hover (suppressed during drag) -> tooltip: title, date, Q+R count

// Internal state
let _dragState = null; // { sourceNode, sourceEl } while dragging
let _lastClickTime = 0; // for double-click detection (persists across re-renders)
let _lastClickId = null;
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
 * @param {{ onNavigate, onBranch, onDelete, onMerge }} callbacks
 *   onMerge(sourceId, targetId) — move sourceId to become a child of targetId
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
  const mergeHighlight = "#f59e0b"; // amber for merge target

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
    resetTarget: svgEl,
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

  // ─── Drag-to-merge ───
  // Dragging a node onto another reparents it (merge/move).
  // Cannot drag root. Cannot drop onto self or descendants.
  const allNodes = root.descendants();

  function _isDescendantOf(potentialDescendant, potentialAncestor) {
    // Walk up from potentialDescendant to see if we hit potentialAncestor
    let cur = potentialDescendant;
    while (cur) {
      if (cur === potentialAncestor) return true;
      cur = cur.parent;
    }
    return false;
  }

  function _findNodeAt(px, py, excludeNode) {
    // Find the closest node to (px, py) within hit radius, excluding the dragged node + its subtree
    let best = null, bestDist = 30; // 30px hit radius
    for (const n of allNodes) {
      if (n === excludeNode) continue;
      if (_isDescendantOf(n, excludeNode)) continue;
      const dx = n.x - px, dy = n.y - py;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < bestDist) { best = n; bestDist = dist; }
    }
    return best;
  }

  let _dragTarget = null;
  let _dragMoved = false;

  const dragBehavior = d3.drag()
    .filter(function(event, d) {
      // Ctrl/meta-click should not start drag — let click handler show context menu
      if (event.ctrlKey || event.metaKey) return false;
      // Only allow drag on non-root nodes, left button only
      return d.data.id !== "root" && event.button === 0;
    })
    .on("start", function(event, d) {
      _hideContextMenu();
      _dragMoved = false;
      _dragState = { sourceNode: d, sourceEl: this };
    })
    .on("drag", function(event, d) {
      if (!_dragState) return;
      // Only start visual drag after significant movement
      const dx = event.x - d.x, dy = event.y - d.y;
      if (!_dragMoved && Math.abs(dx) < 5 && Math.abs(dy) < 5) return;
      _dragMoved = true;
      d3.select(this).raise().style("opacity", 0.7);
      // Move the dragged node visually
      d3.select(this).attr("transform", `translate(${event.x},${event.y})`);

      // Highlight potential drop target
      const target = _findNodeAt(event.x, event.y, d);
      if (target !== _dragTarget) {
        // Unhighlight previous
        if (_dragTarget) {
          g.selectAll(".conv-node").filter(n => n === _dragTarget)
            .select(".node-shape")
            .attr("stroke", n => n.data.selected ? accent : (n.data.id === "root" ? (n.data.selected ? accent : border) : border))
            .attr("stroke-width", n => n.data.selected || n.data.id === "root" ? 2 : 1);
        }
        _dragTarget = target;
        // Highlight new
        if (_dragTarget) {
          g.selectAll(".conv-node").filter(n => n === _dragTarget)
            .select(".node-shape")
            .attr("stroke", mergeHighlight)
            .attr("stroke-width", 3);
        }
      }
    })
    .on("end", function(event, d) {
      if (!_dragState) return;

      if (!_dragMoved) {
        // No movement — detect double-click vs single click (compare by ID
        // since navigate re-renders the tree, creating new node objects)
        const now = Date.now();
        const nodeId = d.data.id;
        if (_lastClickId === nodeId && (now - _lastClickTime) < 400) {
          // Double-click: open context menu
          _lastClickTime = 0;
          _lastClickId = null;
          _dragState = null;
          _dragTarget = null;
          _triggerContextMenu(event.sourceEvent, d);
          return;
        }
        _lastClickTime = now;
        _lastClickId = nodeId;
        _dragState = null;
        _dragTarget = null;
        if (callbacks.onNavigate) callbacks.onNavigate(d.data.id);
        return;
      }

      // Reset visual state
      d3.select(this).style("opacity", 1)
        .attr("transform", `translate(${d.x},${d.y})`);

      if (_dragTarget) {
        // Unhighlight
        g.selectAll(".conv-node").filter(n => n === _dragTarget)
          .select(".node-shape")
          .attr("stroke", n => n.data.selected ? accent : border)
          .attr("stroke-width", n => n.data.selected ? 2 : 1);

        const sourceId = d.data.id;
        const targetId = _dragTarget.data.id;

        // Confirm merge
        if (sourceId !== targetId) {
          if (targetId === "root") {
            // Can't merge into root
          } else {
            const srcCount = (d.data.messages || []).length;
            const tgtCount = (_dragTarget.data.messages || []).length;
            const targetLabel = _dragTarget.data.title;
            if ((typeof confirmAction === "function" ? confirmAction : confirm)(`Merge "${d.data.title}" (${srcCount} msgs) into "${targetLabel}" (${tgtCount} msgs)?\nMessages will be combined into one conversation.`)) {
              if (callbacks.onMerge) callbacks.onMerge(sourceId, targetId);
            }
          }
        }
      }

      _dragState = null;
      _dragTarget = null;
    });

  // Prevent text selection on tree nodes
  node.style("user-select", "none");

  node.call(dragBehavior);

  // ─── Click: navigate + ctrl-click/double-click → context menu ───
  // For non-root nodes, drag-end is the primary handler (fires before click).
  // This click handler is a fallback: d3.drag can suppress clicks after
  // micro-movement, so drag-end is authoritative for non-root. Both paths
  // may fire; navigateToNode deduplicates by selected-ID check.
  node.on("click", function(event, d) {
    event.preventDefault();
    event.stopPropagation();
    _hideContextMenu();

    // Ctrl-click / meta-click → context menu (any node)
    if (event.ctrlKey || event.metaKey) {
      _triggerContextMenu(event, d);
      return;
    }

    if (d.data.id !== "root") {
      // Non-root fallback: drag-end already navigated (navigateToNode deduplicates)
      if (callbacks.onNavigate) callbacks.onNavigate(d.data.id);
      return;
    }

    // Root double-click detection (root excluded from drag, so only this handler fires)
    var now = Date.now();
    var nodeId = d.data.id;
    if (_lastClickId === nodeId && (now - _lastClickTime) < 400) {
      _lastClickTime = 0;
      _lastClickId = null;
      _triggerContextMenu(event, d);
      return;
    }
    _lastClickTime = now;
    _lastClickId = nodeId;
    if (callbacks.onNavigate) callbacks.onNavigate(null);
  });

  // Double-click opens context menu (backup for root; non-root handled in drag end)
  node.on("dblclick", function(event, d) {
    event.preventDefault();
    event.stopPropagation();
    _triggerContextMenu(event, d);
  });

  // Touch double-tap detection (dblclick doesn't fire on most mobile browsers)
  let _lastTapTime = 0;
  let _lastTapTarget = null;
  node.on("touchend.doubletap", function(event, d) {
    const now = Date.now();
    const isSameNode = (_lastTapTarget === d);
    if (isSameNode && (now - _lastTapTime) < 350) {
      // Double-tap detected
      event.preventDefault();
      // Use touch position for menu placement
      const touch = event.changedTouches && event.changedTouches[0];
      const synth = touch ? { clientX: touch.clientX, clientY: touch.clientY,
                              pageX: touch.pageX, pageY: touch.pageY,
                              preventDefault: () => {}, stopPropagation: () => {} } : event;
      _triggerContextMenu(synth, d);
      _lastTapTime = 0;
      _lastTapTarget = null;
    } else {
      _lastTapTime = now;
      _lastTapTarget = d;
    }
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
      _hideContextMenu();
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

  const menu = document.createElement("div");
  menu.className = "tree-context-menu";
  menu.style.position = "fixed";
  menu.style.left = (event.clientX + 4) + "px";
  menu.style.top = (event.clientY + 4) + "px";

  menu._justOpened = true;
  setTimeout(() => { menu._justOpened = false; }, 300);

  const ctxItem = document.createElement("div");
  ctxItem.className = "ctx-item";
  ctxItem.textContent = "Context\u2026";
  ctxItem.addEventListener("click", function(e) {
    e.stopPropagation();
    _hideContextMenu();
    if (callbacks.onEditContext) callbacks.onEditContext();
  });
  menu.appendChild(ctxItem);

  const truthItem = document.createElement("div");
  truthItem.className = "ctx-item";
  truthItem.textContent = "Trust\u2026";
  truthItem.addEventListener("click", function(e) {
    e.stopPropagation();
    _hideContextMenu();
    if (callbacks.onEditTruth) callbacks.onEditTruth();
  });
  menu.appendChild(truthItem);

  const sep = document.createElement("div");
  sep.className = "ctx-sep";
  menu.appendChild(sep);

  const deleteAllItem = document.createElement("div");
  deleteAllItem.className = "ctx-item ctx-danger";
  deleteAllItem.textContent = "Delete All";
  deleteAllItem.addEventListener("click", function(e) {
    e.stopPropagation();
    _hideContextMenu();
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

  const menu = document.createElement("div");
  menu.className = "tree-context-menu";
  menu.style.position = "fixed";
  menu.style.left = (event.clientX + 4) + "px";
  menu.style.top = (event.clientY + 4) + "px";

  // Prevent the initial event from closing the menu
  menu._justOpened = true;
  setTimeout(() => { menu._justOpened = false; }, 300);

  // Copy all message content in this node to clipboard
  const copyItem = document.createElement("div");
  copyItem.className = "ctx-item";
  copyItem.textContent = "Copy";
  copyItem.addEventListener("click", function(e) {
    e.stopPropagation();
    _hideContextMenu();
    if (callbacks.onCopy) callbacks.onCopy(nodeData.id);
  });
  menu.appendChild(copyItem);

  const branchItem = document.createElement("div");
  branchItem.className = "ctx-item";
  branchItem.textContent = "Branch...";
  branchItem.addEventListener("click", function(e) {
    e.stopPropagation();
    _hideContextMenu();
    if (callbacks.onBranch) callbacks.onBranch(nodeData.id);
  });
  menu.appendChild(branchItem);

  const sep = document.createElement("div");
  sep.className = "ctx-sep";
  menu.appendChild(sep);

  const deleteItem = document.createElement("div");
  deleteItem.className = "ctx-item ctx-danger";
  deleteItem.textContent = "Delete";
  deleteItem.addEventListener("click", function(e) {
    e.stopPropagation();
    _hideContextMenu();
    if (callbacks.onDelete) callbacks.onDelete(nodeData.id);
  });
  menu.appendChild(deleteItem);

  document.body.appendChild(menu);
  _ctxMenu = menu;
}
