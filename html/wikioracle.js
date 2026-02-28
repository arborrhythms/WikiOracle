// wikioracle.js — Main WikiOracle front-end application.
// Loaded last; depends on config.js, state.js, util.js, query.js, tree.js.
//
// Sections:
//   XHTML validation       — validateXhtml, repairXhtml, ensureXhtml
//   Config/state persist   — _persistConfig, _persistState (call api(); deps live in config.js/state.js)
//   Layout + theme         — applyLayout, applyTheme
//   Provider metadata      — _refreshProviderMeta, _populateModelDropdown, _providerReady
//   Tree navigation        — navigateToNode, branchFromNode, _navigateChild/Sibling
//   Conversation actions   — deleteConversation, _deleteAllConversations, _splitAfterMessage
//   Clipboard              — _cutConversation, _pasteConversation, _copyConversationContent
//   Message rendering      — renderMessages, setStatus, _showProgress/_hideProgress
//   Chat                   — sendMessage (QueryBundle → ResponseBundle)
//   Events + init          — bindEvents, init, _initStateless, _initStateful
//   Draggable divider      — mouse/touch resize between tree and chat
//   Pinch zoom             — two-finger zoom on mobile
//   Swipe navigation       — horizontal/vertical swipe to navigate siblings

// ─── XHTML validation and repair ───
function validateXhtml(content) {
  // Quick check: try to parse as XML fragment in a wrapper
  try {
    const wrapped = `<div xmlns="http://www.w3.org/1999/xhtml">${content}</div>`;
    const parser = new DOMParser();
    const doc = parser.parseFromString(wrapped, "application/xhtml+xml");
    return !doc.querySelector("parsererror");
  } catch { return false; }
}

function repairXhtml(content) {
  // Deterministic sanitizer: use the browser's HTML parser to fix broken markup,
  // then re-serialize as well-formed HTML (close to XHTML).
  const template = document.createElement("template");
  template.innerHTML = content;
  const div = document.createElement("div");
  div.appendChild(template.content.cloneNode(true));
  // Self-close void elements for XHTML compat
  let repaired = div.innerHTML;
  repaired = repaired.replace(/<(br|hr|img|input|meta|link)(\s[^>]*)?\/?>/gi,
    (m, tag, attrs) => `<${tag}${attrs || ""} />`);
  return repaired;
}

function ensureXhtml(content) {
  if (!content) return "<div/>";
  if (validateXhtml(content)) return content;
  const repaired = repairXhtml(content);
  if (validateXhtml(repaired)) return repaired;
  // Last resort: escape and wrap
  return `<p>${escapeHtml(content)}</p>`;
}

// config, state — declared in config.js and state.js

// ─── Persistence bridges (call api() from query.js) ───

// Persist current config (stateless → sessionStorage, stateful → server).
function _persistConfig() {
  if (config.server.stateless) {
    _saveLocalConfig(config);
  } else {
    api("POST", "/config", { config: config }).catch(function() {});
  }
}

// Persist state: sessionStorage is authoritative in stateless mode;
// disk-backed POST /state is used in stateful mode.
function _persistState() {
  if (config.server.stateless) {
    _saveLocalState();
  } else {
    api("POST", "/state", state).catch(e => setStatus("Error: " + e.message));
  }
}


function applyLayout(layout) {
  const tree = document.getElementById("treeContainer");
  document.body.classList.remove("layout-flat", "layout-vertical");
  if (layout === "flat") {
    document.body.classList.add("layout-flat");
  } else if (layout === "vertical") {
    document.body.classList.add("layout-vertical");
    tree.style.height = "";
    if (!tree.style.width) tree.style.width = "280px";
  } else {
    // horizontal — CSS default (height: 40%) applies unless overridden by
    // saved splitter position; no need to set an explicit pixel fallback.
    tree.style.width = "";
  }
  if (typeof renderMessages === "function") renderMessages();
}

function applyTheme(theme) {
  // Set data-theme on <html> so CSS selectors activate the right variables
  var t = theme || "system";
  document.documentElement.setAttribute("data-theme", t);
}

// state — declared in util.js
var _navScrollHint = null;  // "top" | "bottom" | null — set by _treeNav for continuous scrolling

// Pending branch: when set, the next send creates a child of this conversation
let _pendingBranchParent = null;

// ─── Confirmation helper (skips dialog when confirm_actions is off) ───
function confirmAction(msg) {
  if (config.chat && config.chat.confirm_actions) return confirm(msg);
  return true;
}

// ─── Tree navigation ───

function navigateToNode(nodeId) {
  if (!state) return;
  if (state.selected_conversation === nodeId) return; // already on this node (dedup)
  _pendingBranchParent = null; // cancel any pending branch
  state.selected_conversation = nodeId;
  renderMessages();
  // Persist selected_conversation to server
  _persistState();
}

function branchFromNode(convId) {
  // Double-click a node → show empty chat, highlight the branch-from node
  if (!state || !convId) return;
  _pendingBranchParent = convId;
  state.selected_conversation = convId; // keep branch-from node highlighted in tree
  renderMessages();
  const conv = findConversation(state.conversations || [], convId);
  const label = conv ? conv.title.slice(0, 40) : convId.slice(0, 12);
  setStatus(`Branching from "${label}". Type your first message.`);
  document.getElementById("msgInput").focus();
}

function deleteConversation(convId) {
  if (!state || !state.conversations) return;
  const conv = findConversation(state.conversations, convId);
  if (!conv) return;

  const count = countTreeMessages(conv);
  if (!confirmAction(`Delete "${conv.title}" and all its branches? (${count} message${count !== 1 ? "s" : ""})`)) return;

  removeFromTree(state.conversations, convId);
  state.selected_conversation = null;
  renderMessages();
  _persistState();
  setStatus(`Deleted "${conv.title}"`);
}

// ─── Clipboard (shared by tree and message context menus) ───
// Supports cut/copy for both conversations (tree nodes) and messages (Q&R bubbles).
// Paste destination is determined by which popup menu the user invokes Paste from.
let _clipboard = null; // { type:"conv"|"msg", action:"cut"|"copy", id?, convId?, msgIdx?, title? }

function _cutConversation(convId) {
  if (!state) return;
  var conv = findConversation(state.conversations || [], convId);
  if (!conv) return;
  _clipboard = { type: "conv", action: "cut", id: convId, title: conv.title };
  setStatus('Cut "' + truncate(conv.title, 30) + '" \u2014 navigate to target and Paste');
}

function _pasteConversation(targetId) {
  if (!_clipboard || _clipboard.type !== "conv") return;
  var srcId = _clipboard.id;
  if (srcId === targetId) { setStatus("Cannot paste onto itself."); return; }

  var src = findConversation(state.conversations || [], srcId);
  if (!src) { _clipboard = null; setStatus("Source conversation no longer exists."); return; }

  // Prevent pasting a node onto its own descendant (would create a cycle)
  if (targetId !== "root" && findInTree(src.children || [], targetId)) {
    setStatus("Cannot paste a node onto its own descendant.");
    return;
  }

  if (_clipboard.action === "cut") {
    // Move: reparent srcId under targetId
    removeFromTree(state.conversations, srcId);
    if (targetId === "root") {
      state.conversations.push(src);
    } else {
      var tgt = findConversation(state.conversations, targetId);
      if (!tgt) return;
      if (!tgt.children) tgt.children = [];
      tgt.children.push(src);
    }
    var tgtLabel = targetId === "root" ? "Root" : truncate(tgt.title, 30);
    _clipboard = null;
    renderMessages();
    _persistState();
    setStatus('Moved "' + truncate(src.title, 30) + '" under "' + tgtLabel + '"');
  } else if (_clipboard.action === "copy") {
    // Duplicate: deep-clone src and add as child of target
    var clone = _deepCloneConversation(src);
    if (targetId === "root") {
      state.conversations.push(clone);
    } else {
      var tgt = findConversation(state.conversations, targetId);
      if (!tgt) return;
      if (!tgt.children) tgt.children = [];
      tgt.children.push(clone);
    }
    // Don't clear clipboard — copy allows repeated paste
    renderMessages();
    _persistState();
    setStatus('Duplicated "' + truncate(src.title, 30) + '"');
  }
}

function _deepCloneConversation(conv) {
  var clone = JSON.parse(JSON.stringify(conv));
  function _reassignIds(c) {
    c.id = tempId("conv_");
    (c.messages || []).forEach(function(m) { m.id = tempId("msg_"); });
    (c.children || []).forEach(_reassignIds);
  }
  _reassignIds(clone);
  return clone;
}

function _copyConversationContent(convId) {
  if (!state) return;
  var conv = findConversation(state.conversations || [], convId);
  if (!conv || !conv.messages) return;
  // Set internal clipboard for paste-to-duplicate
  _clipboard = { type: "conv", action: "copy", id: convId, title: conv.title };
  // Also copy text to system clipboard
  var text = conv.messages.map(function(m) {
    var who = m.username || m.role || "unknown";
    var body = stripTags(m.content || "");
    return who + ": " + body;
  }).join("\n\n");
  navigator.clipboard.writeText(text).then(function() {
    setStatus("Copied " + conv.messages.length + " messages \u2014 Paste to duplicate");
  }).catch(function() {
    setStatus("Copy failed (clipboard permission denied)");
  });
}

function _deleteAllConversations() {
  if (!state || !state.conversations || state.conversations.length === 0) {
    setStatus("No conversations to delete.");
    return;
  }
  let total = 0;
  for (const c of state.conversations) total += countTreeMessages(c);
  if (!confirmAction(`Delete ALL conversations? (${state.conversations.length} root conversations, ${total} total messages)`)) return;
  state.conversations = [];
  state.selected_conversation = null;
  renderMessages();
  _persistState();
  setStatus("All conversations deleted.");
}

function _splitAfterMessage(msgIdx) {
  if (!state || !state.selected_conversation) return;
  const conv = findConversation(state.conversations, state.selected_conversation);
  if (!conv || !conv.messages) return;
  if (msgIdx < 0 || msgIdx >= conv.messages.length - 1) return; // nothing to split

  const tailMessages = conv.messages.splice(msgIdx + 1);
  const firstMsg = tailMessages[0] || {};
  const preview = truncate(stripTags(firstMsg.content), 40);
  const newTitle = preview || "Split";

  const newConv = {
    id: tempId("conv_"),
    title: newTitle,
    messages: tailMessages,
    children: conv.children || [],  // existing children follow the tail
  };
  conv.children = [newConv];

  state.selected_conversation = newConv.id;
  renderMessages();
  _persistState();
  setStatus(`Split after message ${msgIdx + 1} → "${newTitle}"`);
}

// ─── Message-level actions (within a conversation) ───

let _msgCtxMenu = null;

function _hideMsgContextMenu() {
  if (_msgCtxMenu) { _msgCtxMenu.remove(); _msgCtxMenu = null; }
}

// Dismiss all context menus across both panes
function _hideAllContextMenus() {
  _hideMsgContextMenu();
  if (typeof _hideContextMenu === "function") _hideContextMenu(); // tree pane menu
}

// Context menu for chat messages. Uses position:fixed to avoid clipping by
// the chat container's overflow. The _justOpened flag + 300ms grace period
// prevents the document-level click handler from immediately closing the menu.
function _showMsgContextMenu(event, msgIdx, totalMsgs) {
  _hideAllContextMenus();

  var menu = document.createElement("div");
  menu.className = "tree-context-menu"; // reuse tree context menu style
  menu.style.position = "fixed";
  menu.style.left = event.clientX + 4 + "px";
  menu.style.top = event.clientY + 4 + "px";
  menu._justOpened = true;
  setTimeout(function() { menu._justOpened = false; }, 300);

  // Cut
  var cutItem = document.createElement("div");
  cutItem.className = "ctx-item";
  cutItem.textContent = "Cut";
  cutItem.addEventListener("click", function(e) { e.stopPropagation(); _hideMsgContextMenu(); _cutMessage(msgIdx); });
  menu.appendChild(cutItem);

  // Copy
  var copyItem = document.createElement("div");
  copyItem.className = "ctx-item";
  copyItem.textContent = "Copy";
  copyItem.addEventListener("click", function(e) { e.stopPropagation(); _hideMsgContextMenu(); _copyMessageContent(msgIdx); });
  menu.appendChild(copyItem);

  // Paste (only if clipboard has a message)
  if (_clipboard && _clipboard.type === "msg") {
    var pasteItem = document.createElement("div");
    pasteItem.className = "ctx-item";
    pasteItem.textContent = "Paste";
    pasteItem.addEventListener("click", function(e) { e.stopPropagation(); _hideMsgContextMenu(); _pasteMessage(msgIdx); });
    menu.appendChild(pasteItem);
  }

  // Delete
  var delItem = document.createElement("div");
  delItem.className = "ctx-item ctx-danger";
  delItem.textContent = "Delete";
  delItem.addEventListener("click", function(e) { e.stopPropagation(); _hideMsgContextMenu(); _deleteMessage(msgIdx); });
  menu.appendChild(delItem);

  // Separator
  var sep = document.createElement("div");
  sep.className = "ctx-sep";
  menu.appendChild(sep);

  // Branch: split after this message, or branch from current conversation if last message
  var branchItem = document.createElement("div");
  branchItem.className = "ctx-item";
  branchItem.textContent = "Branch\u2026";
  branchItem.addEventListener("click", function(e) {
    e.stopPropagation(); _hideMsgContextMenu();
    if (msgIdx < totalMsgs - 1) {
      _splitAfterMessage(msgIdx);
    } else if (state.selected_conversation) {
      branchFromNode(state.selected_conversation);
    }
  });
  menu.appendChild(branchItem);

  document.body.appendChild(menu);
  _msgCtxMenu = menu;

  // Close when clicking outside
  function onDocClick(e) {
    if (_msgCtxMenu && !_msgCtxMenu.contains(e.target) && !_msgCtxMenu._justOpened) {
      _hideMsgContextMenu();
      document.removeEventListener("click", onDocClick);
    }
  }
  document.addEventListener("click", onDocClick);
}

function _moveMessage(fromIdx, toIdx) {
  if (!state || !state.selected_conversation) return;
  const conv = findConversation(state.conversations, state.selected_conversation);
  if (!conv || !conv.messages) return;
  if (fromIdx < 0 || fromIdx >= conv.messages.length) return;
  if (toIdx < 0 || toIdx >= conv.messages.length) return;
  const [msg] = conv.messages.splice(fromIdx, 1);
  conv.messages.splice(toIdx, 0, msg);
  renderMessages();
  _persistState();
}

function _deleteMessage(msgIdx) {
  if (!state || !state.selected_conversation) return;
  const conv = findConversation(state.conversations, state.selected_conversation);
  if (!conv || !conv.messages) return;
  const msg = conv.messages[msgIdx];
  if (!msg) return;
  const preview = truncate(stripTags(msg.content), 60);
  if (!confirmAction(`Delete this message?\n"${preview}"`)) return;
  conv.messages.splice(msgIdx, 1);
  // If conversation is now empty, remove it too
  if (conv.messages.length === 0 && (!conv.children || conv.children.length === 0)) {
    removeFromTree(state.conversations, state.selected_conversation);
    state.selected_conversation = null;
  }
  renderMessages();
  _persistState();
}

function _cutMessage(msgIdx) {
  if (!state || !state.selected_conversation) return;
  var conv = findConversation(state.conversations, state.selected_conversation);
  if (!conv || !conv.messages || !conv.messages[msgIdx]) return;
  _clipboard = { type: "msg", action: "cut", convId: state.selected_conversation, msgIdx: msgIdx };
  setStatus("Cut message \u2014 select a position and Paste");
}

function _copyMessageContent(msgIdx) {
  if (!state || !state.selected_conversation) return;
  var conv = findConversation(state.conversations, state.selected_conversation);
  if (!conv || !conv.messages || !conv.messages[msgIdx]) return;
  var msg = conv.messages[msgIdx];
  // Set internal clipboard for paste-to-duplicate
  _clipboard = { type: "msg", action: "copy", convId: state.selected_conversation, msgIdx: msgIdx };
  // Also copy text to system clipboard
  var text = stripTags(msg.content || "");
  navigator.clipboard.writeText(text).then(function() {
    setStatus("Copied message text \u2014 Paste to duplicate");
  }).catch(function() {
    setStatus("Copy failed (clipboard permission denied)");
  });
}

function _pasteMessage(targetIdx) {
  if (!_clipboard || _clipboard.type !== "msg") return;
  if (!state || !state.selected_conversation) return;
  var conv = findConversation(state.conversations, state.selected_conversation);
  if (!conv || !conv.messages) return;

  if (_clipboard.action === "cut") {
    if (_clipboard.convId !== state.selected_conversation) {
      setStatus("Cannot paste message across conversations.");
      _clipboard = null;
      return;
    }
    _moveMessage(_clipboard.msgIdx, targetIdx);
    _clipboard = null;
  } else if (_clipboard.action === "copy") {
    var srcConv = findConversation(state.conversations, _clipboard.convId);
    if (!srcConv || !srcConv.messages) { _clipboard = null; return; }
    var srcMsg = srcConv.messages[_clipboard.msgIdx];
    if (!srcMsg) { _clipboard = null; return; }
    var clone = JSON.parse(JSON.stringify(srcMsg));
    clone.id = tempId("msg_");
    conv.messages.splice(targetIdx, 0, clone);
    // Don't clear clipboard — copy allows repeated paste
    renderMessages();
    _persistState();
    setStatus("Pasted message copy");
  }
}



// ─── Tree statistics (for root summary view) ───

function _computeTreeStats(conversations) {
  var stats = { convCount: 0, msgCount: 0, qCount: 0, rCount: 0,
                earliest: null, latest: null };
  function walk(nodes) {
    for (var i = 0; i < nodes.length; i++) {
      stats.convCount++;
      var msgs = nodes[i].messages || [];
      for (var j = 0; j < msgs.length; j++) {
        stats.msgCount++;
        if (msgs[j].role === "user") stats.qCount++;
        else stats.rCount++;
        var t = msgs[j].time;
        if (t) {
          if (!stats.earliest || t < stats.earliest) stats.earliest = t;
          if (!stats.latest   || t > stats.latest)   stats.latest = t;
        }
      }
      walk(nodes[i].children || []);
    }
  }
  walk(conversations);
  return stats;
}

function _friendlyDate(iso) {
  if (!iso) return "—";
  try {
    var d = new Date(iso);
    return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  } catch (e) { return iso; }
}

// ─── UI rendering ───
// renderMessages: finds the selected conversation via findConversation(),
// iterates conv.messages to build .message divs (role-based alignment),
// attaches context-menu listeners (right-click -> Cut/Copy/Paste/Branch/Delete), then
// calls conversationsToHierarchy() + renderTree() to sync the tree panel.
// Auto-scrolls chat container to bottom after render.
function renderMessages() {
  _hideAllContextMenus();
  const wrapper = document.getElementById("chatWrapper");
  wrapper.innerHTML = "";

  // Click on empty area clears bubble selection and dismisses menus
  wrapper.addEventListener("click", () => {
    _hideAllContextMenus();
    const sel = wrapper.querySelector(".msg-selected");
    if (sel) sel.classList.remove("msg-selected");
  });

  if (!state) state = {};
  if (!Array.isArray(state.conversations)) state.conversations = [];

  const treeCallbacks = {
    onNavigate: navigateToNode, onBranch: branchFromNode, onDelete: deleteConversation,
    onCut: _cutConversation, onCopy: _copyConversationContent, onPaste: _pasteConversation,
    hasClipboard: function() { return _clipboard && _clipboard.type === "conv"; },
    clipboardLabel: function() { return _clipboard ? _clipboard.title || "" : ""; },
    onEditContext: _toggleContextEditor, onEditTruth: _openTruthEditor, onDeleteAll: _deleteAllConversations
  };

  // Validate state.selected_conversation: if it points to a missing conversation, reset to root
  if (state.selected_conversation !== null && !findConversation(state.conversations, state.selected_conversation)) {
    state.selected_conversation = null;
  }

  // Determine which messages to show
  // When _pendingBranchParent is set, show empty chat (ready for new branch)
  let visible = [];
  if (_pendingBranchParent) {
    // Empty chat — user is about to type a new branch message
  } else if (state.selected_conversation !== null) {
    const conv = findConversation(state.conversations, state.selected_conversation);
    if (conv) {
      visible = conv.messages || [];
    }
  }
  // else: root selected → empty chat

  console.log("[WikiOracle] renderMessages: selectedConv=", state.selected_conversation,
              "visible=", visible.length, "conversations=", state.conversations.length);

  // Show parent navigation link at top of chat
  if (!_pendingBranchParent && state.selected_conversation !== null) {
    var parentConv = findParentConversation(state.conversations, state.selected_conversation);
    var parentNav = document.createElement("div");
    parentNav.className = "conv-parent-nav";
    var parentLink = document.createElement("button");
    parentLink.className = "conv-parent-link";
    if (parentConv) {
      parentLink.textContent = "\u2190 " + (parentConv.title || "(untitled)");
      parentLink.addEventListener("click", function() { navigateToNode(parentConv.id); });
    } else {
      // Current node is a root — link goes to root view
      parentLink.textContent = "\u2190 Root";
      parentLink.addEventListener("click", function() { navigateToNode(null); });
    }
    parentNav.appendChild(parentLink);
    wrapper.appendChild(parentNav);
  }

  for (let idx = 0; idx < visible.length; idx++) {
    const msg = visible[idx];
    const role = msg.role || "user";
    const div = document.createElement("div");
    div.className = `message ${role}`;
    div.dataset.msgIdx = idx;
    div.dataset.msgId = msg.id || "";
    if (msg._pending) div.style.opacity = "0.6";

    const meta = document.createElement("div");
    meta.className = "msg-meta";
    const ts = msg.time ? new Date(msg.time).toLocaleString() : "";
    meta.textContent = `${msg.username || ""} · ${ts}`;

    const bubble = document.createElement("div");
    bubble.className = "msg-bubble";
    bubble.innerHTML = ensureXhtml(msg.content || "");

    div.appendChild(meta);
    div.appendChild(bubble);

    // Click bubble to select (highlight outline, like tree-node selection)
    bubble.addEventListener("click", (e) => {
      e.stopPropagation();
      _hideAllContextMenus();
      const prev = wrapper.querySelector(".msg-selected");
      if (prev && prev !== bubble) prev.classList.remove("msg-selected");
      bubble.classList.toggle("msg-selected");
    });

    // Context menu (right-click / long-press) for message actions
    div.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      e.stopPropagation();
      _showMsgContextMenu(e, idx, visible.length);
    });

    // Double-click to open context menu (desktop) — on bubble only, not the
    // full message row, so double-clicking empty space doesn't trigger a menu.
    bubble.addEventListener("dblclick", (e) => {
      e.preventDefault();
      e.stopPropagation();
      _showMsgContextMenu(e, idx, visible.length);
    });

    // Double-tap detection (mobile — dblclick doesn't fire on most touch browsers)
    onDoubleTap(bubble, (synth) => { _showMsgContextMenu(synth, idx, visible.length); });

    wrapper.appendChild(div);
  }

  // ─── Root summary dashboard (when viewing the root node) ───
  if (state.selected_conversation === null && !_pendingBranchParent) {
    var stats = _computeTreeStats(state.conversations);
    var trustEntries = (state.truth && state.truth.trust) || [];
    var contextText = stripTags(state.context || "").trim();

    var summary = document.createElement("div");
    summary.className = "root-summary";

    // Title
    var h2 = document.createElement("h2");
    h2.className = "root-summary-title";
    h2.textContent = "WikiOracle";
    summary.appendChild(h2);

    var sub = document.createElement("p");
    sub.className = "root-summary-subtitle";
    sub.textContent = "Document overview";
    summary.appendChild(sub);

    // Stat grid
    var grid = document.createElement("div");
    grid.className = "root-summary-grid";
    var statItems = [
      [stats.convCount, "Conversations"],
      [stats.msgCount,  "Messages"],
      [stats.qCount,    "Questions"],
      [stats.rCount,    "Responses"]
    ];
    for (var si = 0; si < statItems.length; si++) {
      var cell = document.createElement("div");
      cell.className = "root-stat";
      var valSpan = document.createElement("span");
      valSpan.className = "root-stat-value";
      valSpan.textContent = String(statItems[si][0]);
      var lblSpan = document.createElement("span");
      lblSpan.className = "root-stat-label";
      lblSpan.textContent = statItems[si][1];
      cell.appendChild(valSpan);
      cell.appendChild(lblSpan);
      grid.appendChild(cell);
    }
    summary.appendChild(grid);

    // Date info
    if (stats.msgCount > 0) {
      var meta = document.createElement("div");
      meta.className = "root-summary-meta";
      if (state.time) {
        var modSpan = document.createElement("span");
        modSpan.textContent = "Last modified: " + _friendlyDate(state.time);
        meta.appendChild(modSpan);
      }
      if (stats.earliest && stats.latest) {
        var rangeSpan = document.createElement("span");
        rangeSpan.textContent = _friendlyDate(stats.earliest) + " \u2013 " + _friendlyDate(stats.latest);
        meta.appendChild(rangeSpan);
      }
      summary.appendChild(meta);
    }

    // Context preview (clickable — opens context editor)
    var ctxSection = document.createElement("div");
    ctxSection.className = "root-summary-section";
    ctxSection.style.cursor = "pointer";
    var ctxH3 = document.createElement("h3");
    ctxH3.textContent = "Context";
    ctxSection.appendChild(ctxH3);
    var ctxP = document.createElement("p");
    ctxP.className = "root-summary-context";
    ctxP.textContent = (contextText && contextText !== "<div/>")
      ? truncate(contextText, 200)
      : "(none — tap to edit)";
    ctxSection.appendChild(ctxP);
    ctxSection.addEventListener("click", function() {
      if (typeof _toggleContextEditor === "function") _toggleContextEditor();
    });
    summary.appendChild(ctxSection);

    // Trust entries (clickable — opens trust editor)
    var trustSection = document.createElement("div");
    trustSection.className = "root-summary-section";
    trustSection.style.cursor = "pointer";
    var trustH3 = document.createElement("h3");
    trustH3.textContent = "Trust";
    trustSection.appendChild(trustH3);
    var trustP = document.createElement("p");
    trustP.textContent = trustEntries.length > 0
      ? trustEntries.length + (trustEntries.length === 1 ? " entry" : " entries")
      : "(none — tap to edit)";
    trustSection.appendChild(trustP);
    trustSection.addEventListener("click", function() {
      if (typeof _openTruthEditor === "function") _openTruthEditor();
    });
    summary.appendChild(trustSection);

    // Hint
    var hint = document.createElement("p");
    hint.className = "root-summary-hint";
    hint.textContent = "Type a message to start a new conversation.";
    summary.appendChild(hint);

    wrapper.appendChild(summary);
  }

  // Show child conversations as clickable links (navigate deeper into tree)
  if (!_pendingBranchParent) {
    var currentConv = state.selected_conversation ? findConversation(state.conversations, state.selected_conversation) : null;
    var childConvs = currentConv ? (currentConv.children || []) : state.conversations;
    if (childConvs.length > 0) {
      const childNav = document.createElement("div");
      childNav.className = "conv-children-nav";
      for (const child of childConvs) {
        const link = document.createElement("button");
        link.className = "conv-child-link";
        const msgs = child.messages || [];
        const qCount = msgs.filter(function(m) { return m.role === "user"; }).length;
        link.textContent = (child.title || "(untitled)") + " (" + qCount + "Q " + (msgs.length - qCount) + "R)";
        link.addEventListener("click", (function(id) { return function() { navigateToNode(id); }; })(child.id));
        childNav.appendChild(link);
      }
      wrapper.appendChild(childNav);
    }
  }

  // Show placeholder for empty non-root conversations or pending branches
  var hasChildren = typeof childConvs !== "undefined" && childConvs && childConvs.length > 0;
  if (visible.length === 0 && !hasChildren && state.selected_conversation !== null) {
    const placeholder = document.createElement("div");
    placeholder.className = "chat-placeholder";
    if (_pendingBranchParent) {
      placeholder.textContent = "Type a message to create a new branch.";
    } else {
      placeholder.textContent = "No messages in this conversation.";
    }
    wrapper.appendChild(placeholder);
  }

  // Scroll chat — direction-aware for continuous scroll-through-tree navigation
  const container = document.getElementById("chatContainer");
  if (_navScrollHint === "top") {
    container.scrollTop = 0;
  } else {
    container.scrollTop = container.scrollHeight;
  }
  _navScrollHint = null;

  // Render D3 tree
  try {
    if (typeof conversationsToHierarchy === "function" && typeof renderTree === "function") {
      const treeData = conversationsToHierarchy(state.conversations, state.selected_conversation);
      renderTree(treeData, treeCallbacks);
    }
  } catch (e) {
    console.error("[WikiOracle] renderTree error:", e);
  }
}

function setStatus(text) {
  // Status bar removed — log to console for debugging
  console.log("[WikiOracle]", text);
}

// ─── Loading modal (blocks interaction until state loads) ───
// _showProgress(-1) = indeterminate; _showProgress(0..100) = determinate.
// _showProgress(pct, label) sets optional label text.
let _progressOverlay = null;

function _showProgress(pct, label) {
  if (!_progressOverlay) {
    _progressOverlay = document.createElement("div");
    _progressOverlay.className = "loading-overlay";
    _progressOverlay.innerHTML =
      '<div class="loading-box">' +
        '<div class="loading-label">Loading\u2026</div>' +
        '<div class="loading-track"><div class="loading-fill"></div></div>' +
      '</div>';
    document.body.appendChild(_progressOverlay);
  }
  var track = _progressOverlay.querySelector(".loading-track");
  var fill = _progressOverlay.querySelector(".loading-fill");
  var lbl = _progressOverlay.querySelector(".loading-label");
  if (label !== undefined) lbl.textContent = label;
  if (pct < 0) {
    track.classList.add("indeterminate");
    fill.style.width = "";
  } else {
    track.classList.remove("indeterminate");
    fill.style.width = Math.min(pct, 100) + "%";
  }
  _progressOverlay.style.display = "";
}

function _hideProgress() {
  if (!_progressOverlay) return;
  var fill = _progressOverlay.querySelector(".loading-fill");
  var track = _progressOverlay.querySelector(".loading-track");
  track.classList.remove("indeterminate");
  fill.style.width = "100%";
  setTimeout(function() {
    if (_progressOverlay) _progressOverlay.style.display = "none";
  }, 350);
}

function _updatePlaceholder() {
  const input = document.getElementById("msgInput");
  const meta = config.server.providers[config.ui.default_provider];
  const name = meta ? meta.name : config.ui.default_provider;
  const model = config.ui.model || (meta ? meta.model : "");
  input.placeholder = model ? `Message ${name} (${model})...` : `Message ${name}...`;
}

// ─── Send message ───
async function sendMessage() {
  const input = document.getElementById("msgInput");
  const text = input.value.trim();
  if (!text) return;

  // Check provider readiness before sending
  if (!_providerReady()) {
    const meta = config.server.providers[config.ui.default_provider] || {};
    setStatus(`${meta.name || config.ui.default_provider} requires an API key. Add it in Settings \u2192 config.yaml.`);
    return;
  }

  input.value = "";
  input.style.height = "auto";
  document.getElementById("btnSend").disabled = true;
  setStatus("Sending...");

  // Determine how to route this message:
  //   _pendingBranchParent set → create child of that conversation (branch_from)
  //   state.selected_conversation !== null → append to that conversation (conversation_id)
  //   state.selected_conversation === null → new root conversation (neither)
  let conversationId = null;
  let branchFrom = null;
  let isNewRoot = false;

  if (_pendingBranchParent) {
    branchFrom = _pendingBranchParent;
    _pendingBranchParent = null;
  } else if (state.selected_conversation !== null) {
    conversationId = state.selected_conversation;
  } else {
    isNewRoot = true;
  }

  console.log("[WikiOracle] sendMessage: convId=", conversationId,
              "branchFrom=", branchFrom, "newRoot=", isNewRoot);

  // Optimistic UI: show user message immediately
  const optimisticMsgId = tempId("m_");
  const now = new Date().toISOString().replace(/\.\d+Z$/, "Z");
  const userEntry = {
    id: optimisticMsgId,
    role: "user",
    username: config.user.name || "User",
    time: now,
    content: `<p>${escapeHtml(text)}</p>`,
    _pending: true,
  };

  if (conversationId) {
    // Append to existing conversation
    const conv = findConversation(state.conversations, conversationId);
    if (conv) conv.messages.push(userEntry);
  } else if (branchFrom || isNewRoot) {
    // Create temporary optimistic conversation
    const optConvId = tempId("c_");
    const optConv = {
      id: optConvId,
      title: text.slice(0, 50),
      messages: [userEntry],
      children: [],
    };
    if (branchFrom) {
      const parent = findConversation(state.conversations, branchFrom);
      if (parent) {
        if (!parent.children) parent.children = [];
        parent.children.push(optConv);
      } else {
        state.conversations.push(optConv);
      }
    } else {
      state.conversations.push(optConv);
    }
    state.selected_conversation = optConvId;
  }
  renderMessages();

  try {
    const queryBundle = {
    // QueryBundle: sent to POST /chat
      message: text,
      conversation_id: conversationId || undefined,
      branch_from: branchFrom || undefined,
      config: {
        provider: config.ui.default_provider,
        model: config.ui.model || (config.server.providers[config.ui.default_provider] || {}).model || "",
        username: config.user.name,
        chat: config.chat || {},
      },
    };
    // Include pruned state (ancestor path only) + runtime_config
    const targetConvId = conversationId || branchFrom || state.selected_conversation;
    const prunedState = {
      version: state.version, schema: state.schema, time: state.time,
      context: state.context, output: state.output, truth: state.truth,
      selected_conversation: state.selected_conversation,
      conversations: _buildAncestorPath(state.conversations, targetConvId),
      _path_only: true,
    };
    // If new root (no targetConvId), include the optimistic conversation
    if (!targetConvId && state.conversations.length > 0) {
      prunedState.conversations = [state.conversations[state.conversations.length - 1]];
    }
    if (config.server.stateless) {
      queryBundle.state = prunedState;
      queryBundle.runtime_config = _buildRuntimeConfig();
    } else {
      queryBundle.state = prunedState;
    }
    const data = await api("POST", "/chat", queryBundle);
    const responseBundle = data.state || {};
    // ResponseBundle: returned from POST /chat

    // Merge response into local full state (path_only means response has pruned tree)
    if (!Array.isArray(state.conversations)) state.conversations = [];
    _mergeResponseConversation(state.conversations, responseBundle);
    state.selected_conversation = responseBundle.selected_conversation || state.selected_conversation;
    // Update truth (derived certainty may have changed)
    if (responseBundle.truth) state.truth = responseBundle.truth;

    _persistState();
    renderMessages();
    setStatus("Ready");
  } catch (e) {
    // Rollback: reload state from sessionStorage (stateless) or server (stateful)
    try {
      if (config.server.stateless) {
        const localState = _loadLocalState();
        if (localState) state = localState;
      } else {
        const data = await api("GET", "/state");
        state = data.state || state;
      }
    } catch {}
    if (isNewRoot || branchFrom) state.selected_conversation = null;
    renderMessages();
    setStatus("Error: " + e.message);
  } finally {
    document.getElementById("btnSend").disabled = false;
    input.focus();
  }
}






// ─── Bind UI events ───
function bindEvents() {
  // Export JSONL
  document.getElementById("btnExport").addEventListener("click", function() {
    if (!state) { setStatus("No state to export"); return; }
    const now = new Date();
    const pad2 = n => String(n).padStart(2, "0");
    const fn = `llm_${now.getFullYear()}.${pad2(now.getMonth()+1)}.${pad2(now.getDate())}.${pad2(now.getHours())}${pad2(now.getMinutes())}.jsonl`;

    const lines = [];
    const header = {
      type: "header", version: 2,
      schema: state.schema || "https://raw.githubusercontent.com/arborrhythms/WikiOracle/main/spec/llm_state.json",
      date: new Date().toISOString(),
      context: state.context || "<div/>",
      output: state.output || "<div/>",
      retrieval_prefs: (state.truth || {}).retrieval_prefs || {},
    };
    if (state.selected_conversation) header.selected_conversation = state.selected_conversation;
    lines.push(JSON.stringify(header));

    // Flatten conversations tree with parent references
    function flattenConvs(convs, parentId) {
      for (const conv of convs) {
        const rec = {
          type: "conversation",
          id: conv.id,
          title: conv.title || "",
          messages: (conv.messages || []).map(m => {
            const clean = { ...m };
            delete clean._pending;
            return clean;
          }),
        };
        if (parentId) rec.parent = parentId;
        lines.push(JSON.stringify(rec));
        flattenConvs(conv.children || [], conv.id);
      }
    }
    flattenConvs(state.conversations || [], null);

    // Trust
    for (const t of ((state.truth || {}).trust || [])) {
      lines.push(JSON.stringify({type: "trust", ...t}));
    }

    const blob = new Blob([lines.join("\n") + "\n"], { type: "application/x-jsonlines" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = fn;
    a.click();
    URL.revokeObjectURL(url);
    setStatus("Exported: " + fn);
  });

  // Import
  document.getElementById("btnImport").addEventListener("click", function() {
    document.getElementById("fileImport").click();
  });

  document.getElementById("fileImport").addEventListener("change", async function(e) {
    const file = e.target.files[0];
    if (!file) return;
    try {
      _showProgress(-1, "Reading file\u2026");
      const text = await file.text();
      const lines = text.trim().split("\n").filter(l => l.trim());
      if (lines.length === 0) throw new Error("Empty file");
      const first = JSON.parse(lines[0]);
      if (first.type !== "header" && !first.version) throw new Error("Not a WikiOracle state file");

      // Build state from JSONL
      let importState;
      if (first.type === "header") {
        importState = {
          version: first.version || 2,
          schema: first.schema || "",
          time: first.time || first.date || "",
          context: first.context || "<div/>",
          output: first.output || "",
          conversations: [],
          selected_conversation: first.selected_conversation || null,
          truth: { trust: [], retrieval_prefs: first.retrieval_prefs || {} },
        };
        const convRecords = [];
        const total = lines.length - 1;
        for (let i = 1; i < lines.length; i++) {
          const rec = JSON.parse(lines[i]);
          if (rec.type === "conversation") {
            const { type, ...rest } = rec;
            convRecords.push(rest);
          } else if (rec.type === "trust") {
            const { type, ...rest } = rec;
            importState.truth.trust.push(rest);
          }
          // Update progress bar during parse (yield every 200 lines for large files)
          if (total > 200 && i % 200 === 0) {
            _showProgress((i / total) * 80, "Parsing\u2026 " + i + " / " + total + " lines");
            await new Promise(r => setTimeout(r, 0));
          }
        }
        _showProgress(80);
        if (convRecords.length > 0) {
          const byId = {};
          const roots = [];
          for (const rec of convRecords) {
            byId[rec.id] = { ...rec, children: [] };
          }
          for (const rec of convRecords) {
            const node = byId[rec.id];
            if (rec.parent && byId[rec.parent]) {
              byId[rec.parent].children.push(node);
            } else {
              roots.push(node);
            }
            delete node.parent;
          }
          importState.conversations = roots;
        }
      } else {
        importState = JSON.parse(text);
        _showProgress(80);
      }

      if (!importState.schema || !importState.schema.includes("llm_state")) throw new Error("Not a WikiOracle state file");

      // Merge: client-side in stateless mode, server-side otherwise
      _showProgress(85, "Merging\u2026");
      if (config.server.stateless) {
        _clientMerge(importState);
      } else {
        const result = await api("POST", "/merge", { state: importState });
        state = result.state || state;
      }

      // Persist merged state and redraw all components
      _showProgress(95, "Saving\u2026");
      _persistState();
      state.selected_conversation = null;
      renderMessages();
      _hideProgress();

      // User-visible feedback
      const trustCount = (state.truth && state.truth.trust || []).length;
      const convCount = (state.conversations || []).length;
      const importTrust = (importState.truth && importState.truth.trust || []).length;
      const importConvs = (importState.conversations || []).length;
      const msg = `Imported ${file.name}: ${importTrust} trust entries, ${importConvs} conversations`;
      setStatus(msg);

      // Flash confirmation in message input placeholder
      const input = document.getElementById("msgInput");
      const savedPH = input.placeholder;
      input.placeholder = msg;
      setTimeout(() => { input.placeholder = savedPH; }, 4000);
    } catch (err) {
      _hideProgress();
      setStatus("Import error: " + err.message);
      const input = document.getElementById("msgInput");
      const savedPH = input.placeholder;
      input.placeholder = "Import error: " + err.message;
      setTimeout(() => { input.placeholder = savedPH; }, 5000);
    }
    e.target.value = "";
  });

  // Search
  document.getElementById("btnSearch").addEventListener("click", _openSearch);

  // Settings
  document.getElementById("btnSettings").addEventListener("click", openSettings);
  document.getElementById("btnSettingsCancel").addEventListener("click", closeSettings);
  document.getElementById("btnSettingsSave").addEventListener("click", function() { saveSettings(); });
  document.getElementById("btnSend").addEventListener("click", sendMessage);
  document.getElementById("setTemp").addEventListener("input", function() {
    document.getElementById("setTempVal").textContent = this.value;
  });
  document.getElementById("setProvider").addEventListener("change", function() {
    _populateModelDropdown(this.value);
  });
  document.getElementById("btnSettingsClose").addEventListener("click", closeSettings);

  // Edit config.yaml button
  document.getElementById("btnEditConfig").addEventListener("click", _openConfigEditor);

  // Read button
  document.getElementById("btnRead").addEventListener("click", _openReadView);

  // Textarea auto-resize + Enter to send
  const msgInput = document.getElementById("msgInput");
  msgInput.addEventListener("input", function() {
    this.style.height = "auto";
    this.style.height = Math.min(this.scrollHeight, 120) + "px";
  });
  msgInput.addEventListener("keydown", function(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // ─── Tree navigation helpers (shared by arrow keys and scroll-at-border) ───
  function _treeNav(direction) {
    if (!state) return false;
    var convs = state.conversations || [];

    function buildPreorder(nodes) {
      var result = [null];
      function walk(arr) {
        for (var i = 0; i < arr.length; i++) {
          result.push(arr[i]);
          if (arr[i].children && arr[i].children.length > 0) walk(arr[i].children);
        }
      }
      walk(nodes);
      return result;
    }

    var flat = buildPreorder(convs);
    var curIdx = flat.findIndex(function(c) {
      return c === null ? state.selected_conversation === null : c.id === state.selected_conversation;
    });

    switch (direction) {
      case "up": {
        if (state.selected_conversation === null) return false;
        var parent = findParentConversation(convs, state.selected_conversation);
        _navScrollHint = "bottom";
        treeRequestFocus();
        navigateToNode(parent ? parent.id : null);
        return true;
      }
      case "down": {
        var cur = state.selected_conversation === null ? null : findConversation(convs, state.selected_conversation);
        var hasChildren = state.selected_conversation === null
          ? convs.length > 0
          : (cur && cur.children && cur.children.length > 0);
        if (hasChildren && curIdx >= 0 && curIdx < flat.length - 1) {
          var next = flat[curIdx + 1];
          _navScrollHint = "top";
          treeRequestFocus();
          navigateToNode(next ? next.id : null);
          return true;
        }
        return false;
      }
      case "right": {
        if (curIdx >= 0 && curIdx < flat.length - 1) {
          var next = flat[curIdx + 1];
          _navScrollHint = "top";
          treeRequestFocus();
          navigateToNode(next ? next.id : null);
          return true;
        }
        return false;
      }
      case "left": {
        if (curIdx > 0) {
          var prev = flat[curIdx - 1];
          _navScrollHint = "top";
          treeRequestFocus();
          navigateToNode(prev ? prev.id : null);
          return true;
        }
        return false;
      }
    }
    return false;
  }

  // ─── Arrow-key navigation for conversation tree ───
  document.addEventListener("keydown", function(e) {
    var tag = document.activeElement && document.activeElement.tagName;
    if (tag === "TEXTAREA" || tag === "INPUT" || tag === "SELECT") return;
    if (document.querySelector(".context-overlay.active")) return;
    var dirMap = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right" };
    var dir = dirMap[e.key];
    if (!dir) return;
    e.preventDefault();
    _treeNav(dir);
  });

  // ─── Scroll-at-border: wheel past top/bottom/left/right navigates tree ───
  // Desktop only (trackpad/mouse wheel) — not gated by mobile check
  var _scrollNavCooldown = 0;
  document.getElementById("chatContainer").addEventListener("wheel", function(e) {
    var now = Date.now();
    if (now - _scrollNavCooldown < 600) return;
    var el = this;
    var atTop = el.scrollTop <= 0;
    var atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 1;

    if (atTop && e.deltaY < -30) {
      _scrollNavCooldown = now;
      _treeNav("up");
    } else if (atBottom && e.deltaY > 30) {
      _scrollNavCooldown = now;
      _treeNav("down");
    } else if (Math.abs(e.deltaX) > Math.abs(e.deltaY) && Math.abs(e.deltaX) > 50) {
      // Horizontal scroll (trackpad swipe)
      _scrollNavCooldown = now;
      _treeNav(e.deltaX > 0 ? "right" : "left");
    }
  }, { passive: true });

  // ─── Touch swipe: mobile-only tree navigation via swipe gestures ───
  // Governed by config.ui.swipe_nav_horizontal (default true) and
  // config.ui.swipe_nav_vertical (default false).  Vertical is off because
  // vertical scrolling is used to read content; horizontal swipes
  // navigate siblings.  Both are stored in config.yaml (ui section).
  if ("ontouchstart" in window || navigator.maxTouchPoints > 0) {
    (function() {
      var container = document.getElementById("chatContainer");
      var startY = null, startX = null;
      var SWIPE_THRESHOLD = 80;  // minimum px travel to count as directional swipe

      container.addEventListener("touchstart", function(e) {
        if (e.touches.length === 1) {
          startY = e.touches[0].clientY;
          startX = e.touches[0].clientX;
        }
      }, { passive: true });

      container.addEventListener("touchend", function(e) {
        if (startY === null) return;
        var endTouch = e.changedTouches[0];
        var dy = endTouch.clientY - startY;
        var dx = endTouch.clientX - startX;
        startY = null; startX = null;

        var now = Date.now();
        if (now - _scrollNavCooldown < 600) return;

        var atTop = container.scrollTop <= 0;
        var atBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 1;

        if (config.ui.swipe_nav_vertical) {
          // Finger drags DOWN when at top → navigate to parent
          if (atTop && dy > SWIPE_THRESHOLD && Math.abs(dy) > Math.abs(dx)) {
            _scrollNavCooldown = now; _treeNav("up");
            return;
          } else if (atBottom && dy < -SWIPE_THRESHOLD && Math.abs(dy) > Math.abs(dx)) {
            _scrollNavCooldown = now; _treeNav("down");
            return;
          }
        }

        if (config.ui.swipe_nav_horizontal !== false && Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > SWIPE_THRESHOLD) {
          // Horizontal swipe: finger left = next sibling, finger right = prev
          _scrollNavCooldown = now;
          _treeNav(dx < 0 ? "right" : "left");
        }
      }, { passive: true });
    })();
  }
}

// ─── Init: load config + state from server ───
async function init() {
  try {
    _showProgress(-1, "Connecting\u2026");
    setStatus("Loading...");

    // 0) Load server info (stateless flag, url_prefix)
    //    url_prefix is detected from the page URL: if we're at /chat/,
    //    API calls go to /chat/state etc.  Fallback: ask the server.
    const pagePath = window.location.pathname.replace(/\/+$/, "");
    if (pagePath && pagePath !== "/") {
      config.server.url_prefix = pagePath;
    }
    try {
      const info = await api("GET", "/server_info");
      config.server.stateless = !!info.stateless;
      // If server tells us a prefix and we didn't already detect one, use it
      if (info.url_prefix && !pagePath) config.server.url_prefix = info.url_prefix;
    } catch (e) {
      console.warn("[WikiOracle] Failed to load server_info:", e);
    }

    if (config.server.stateless) {
      await _initStateless();
    } else {
      await _initStateful();
    }

    // Apply layout, theme, and update placeholder from config
    applyLayout(config.ui.layout);
    applyTheme(config.ui.theme);
    _updatePlaceholder();

    // Restore splitter position from config (percentage of viewport)
    if (config.ui.splitter_pct != null) {
      const tree = document.getElementById("treeContainer");
      if (tree) {
        const pct = config.ui.splitter_pct;
        if (document.body.classList.contains("layout-vertical")) {
          tree.style.width = pct === 0 ? "0px" : (pct / 100 * window.innerWidth) + "px";
        } else {
          tree.style.height = pct === 0 ? "0px" : (pct / 100 * window.innerHeight) + "px";
        }
        tree.classList.toggle("tree-collapsed", pct === 0);
      }
    }

    // Restore selected conversation from state
    if (!state.selected_conversation || !findConversation(state.conversations, state.selected_conversation)) {
      state.selected_conversation = null; // root
    }

    const convCount = state.conversations.length;
    console.log("[WikiOracle] init: loaded", convCount, "root conversations");
    renderMessages();
    _hideProgress();
    setStatus(`Loaded ${convCount} conversation${convCount !== 1 ? "s" : ""}`);
  } catch (e) {
    _hideProgress();
    console.error("[WikiOracle] init error:", e);
    setStatus("Connection error: " + e.message);
  }
}

// Stateless init: sessionStorage is authoritative.
// If sessionStorage has data, use it directly — no server calls needed for
// state or config.  If sessionStorage is empty, call /bootstrap once to seed.
async function _initStateless() {
  // Migrate legacy config (one-time)
  await _migrateOldPrefs();

  const localConfig = _loadLocalConfig();
  const localState = _loadLocalState();
  const needsBootstrap = !localConfig || !localState;

  if (needsBootstrap) {
    console.log("[WikiOracle] stateless: bootstrapping from server");
    try {
      const boot = await api("GET", "/bootstrap");

      // Seed config
      if (!localConfig) {
        config = _normalizeConfig(boot.config || {});
        _saveLocalConfig(config);
      } else {
        config = _normalizeConfig(localConfig);
      }

      // Seed state
      if (!localState) {
        state = boot.state || {};
        if (!Array.isArray(state.conversations)) state.conversations = [];
        _saveLocalState();
      } else {
        state = localState;
        if (!Array.isArray(state.conversations)) state.conversations = [];
      }

      // Provider metadata is now part of config.server.providers
      _populateProviderDropdown();
    } catch (e) {
      console.warn("[WikiOracle] bootstrap failed:", e);
      if (localConfig) config = _normalizeConfig(localConfig);
      state = localState || {};
      if (!Array.isArray(state.conversations)) state.conversations = [];
    }
  } else {
    // Both sessionStorage keys present — use them directly, no server calls
    console.log("[WikiOracle] stateless: using sessionStorage (no server calls)");
    config = _normalizeConfig(localConfig);
    state = localState;
    if (!Array.isArray(state.conversations)) state.conversations = [];

    // Provider metadata is already in config.server.providers
    _populateProviderDropdown();
  }
}

// Stateful init: server disk is authoritative.
async function _initStateful() {
  // Load config from server (YAML-shaped with defaults, includes providers)
  try {
    const configData = await api("GET", "/config");
    config = _normalizeConfig(configData.config || {});
  } catch (e) {
    console.warn("[WikiOracle] Failed to load config:", e);
  }
  _populateProviderDropdown();

  // Get state file size for determinate progress bar
  var expectedSize = 0;
  try {
    const sizeData = await api("GET", "/state_size");
    expectedSize = sizeData.size || 0;
  } catch {}

  if (expectedSize > 0) {
    _showProgress(0, "Loading state\u2026");
  }

  // Load state with XHR for progress tracking
  const data = await _fetchStateWithProgress(expectedSize);
  state = data.state || {};
  if (!Array.isArray(state.conversations)) state.conversations = [];
}

// Fetch /state using XHR so we can track download progress via onprogress.
function _fetchStateWithProgress(expectedSize) {
  return new Promise(function(resolve, reject) {
    var prefix = config.server.url_prefix || "";
    var xhr = new XMLHttpRequest();
    xhr.open("GET", prefix + "/state");
    xhr.responseType = "text";

    if (expectedSize > 0) {
      xhr.onprogress = function(e) {
        // Use expectedSize from /state_size (more reliable than e.total
        // which depends on Content-Length header and compression).
        var total = expectedSize || e.total || 0;
        if (total > 0 && e.loaded > 0) {
          var pct = Math.min((e.loaded / total) * 100, 99);
          var loadedKB = (e.loaded / 1024).toFixed(0);
          var totalKB = (total / 1024).toFixed(0);
          _showProgress(pct, "Loading state\u2026 " + loadedKB + " / " + totalKB + " KB");
        }
      };
    }

    xhr.onload = function() {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch (err) {
          reject(new Error("Invalid JSON from /state"));
        }
      } else {
        reject(new Error("HTTP " + xhr.status));
      }
    };
    xhr.onerror = function() { reject(new Error("Network error loading /state")); };
    xhr.send();
  });
}

// Refresh provider metadata from server (updates has_key flags).
// Re-reads /config since provider meta is part of config.server.providers.
async function _refreshProviderMeta() {
  try {
    var cfgData = await api("GET", "/config");
    config = _normalizeConfig(cfgData.config || {});
    _populateProviderDropdown();
  } catch (e) {
    console.warn("[WikiOracle] Failed to refresh provider metadata:", e);
  }
}

// Populate the provider <select> dropdown from config.server.providers
function _populateProviderDropdown() {
  const sel = document.getElementById("setProvider");
  sel.innerHTML = "";
  for (const [key, info] of Object.entries(config.server.providers)) {
    const opt = document.createElement("option");
    opt.value = key;
    const keyWarning = (info.needs_key && !info.has_key) ? " \u26a0 no key" : "";
    opt.textContent = info.name + keyWarning;
    sel.appendChild(opt);
  }
}

// Populate the model <select> dropdown for the currently selected provider
function _populateModelDropdown(providerKey) {
  const sel = document.getElementById("setModel");
  sel.innerHTML = "";
  const meta = config.server.providers[providerKey || config.ui.default_provider];
  if (!meta) return;
  const models = meta.models || [];
  if (models.length === 0 && meta.model) {
    // Fallback: single model from default
    const opt = document.createElement("option");
    opt.value = meta.model;
    opt.textContent = meta.model;
    sel.appendChild(opt);
    return;
  }
  for (const m of models) {
    const opt = document.createElement("option");
    opt.value = m;
    opt.textContent = m;
    sel.appendChild(opt);
  }
}

// Check if the currently selected provider can accept messages
function _providerReady() {
  var meta = config.server.providers[config.ui.default_provider];
  if (!meta) return true;  // unknown provider — let server decide
  if (!meta.needs_key) return true;
  if (meta.has_key) return true;
  // In stateless mode, check local config for client-supplied key
  if (config.server.stateless) {
    var rcKey = ((config.providers || {})[config.ui.default_provider] || {}).api_key;
    if (rcKey) return true;
  }
  return false;
}

// ─── Boot ───
bindEvents();
init();

// ─── Draggable divider between tree and chat (mouse + touch, horizontal + vertical) ───
(function() {
  const divider = document.getElementById("resizeDivider");
  const tree = document.getElementById("treeContainer");
  let dragging = false, startPos = 0, startSize = 0;

  function isVertical() {
    return document.body.classList.contains("layout-vertical");
  }

  function startDrag(clientX, clientY) {
    dragging = true;
    if (isVertical()) { startPos = clientX; startSize = tree.offsetWidth; }
    else              { startPos = clientY; startSize = tree.offsetHeight; }
    divider.classList.add("active");
    document.body.style.cursor = isVertical() ? "col-resize" : "row-resize";
    document.body.style.userSelect = "none";
  }

  function moveDrag(clientX, clientY) {
    if (!dragging) return;
    if (isVertical()) {
      // Allow collapsing to 0 but keep divider on-screen (min 0, max 80% viewport)
      const newW = Math.max(0, Math.min(window.innerWidth * 0.8, startSize + (clientX - startPos)));
      tree.style.width = newW + "px";
    } else {
      // Allow collapsing to 0 but keep divider on-screen (min 0, max 80% viewport)
      const newH = Math.max(0, Math.min(window.innerHeight * 0.8, startSize + (clientY - startPos)));
      tree.style.height = newH + "px";
    }
  }

  function endDrag() {
    if (!dragging) return;
    dragging = false;
    divider.classList.remove("active");
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    // Persist splitter position as percentage into config
    // Use clientHeight/clientWidth (excludes borders) and snap small values to 0
    var size = isVertical() ? tree.clientWidth : tree.clientHeight;
    var viewport = isVertical() ? window.innerWidth : window.innerHeight;
    var pct = size < 4 ? 0 : Math.round(size / viewport * 1000) / 10;
    config.ui.splitter_pct = pct;
    // Toggle collapsed state for border hiding
    tree.classList.toggle("tree-collapsed", pct === 0);
    _persistConfig();
    if (typeof renderMessages === "function") renderMessages();
  }

  // Mouse events
  divider.addEventListener("mousedown", function(e) { e.preventDefault(); startDrag(e.clientX, e.clientY); });
  document.addEventListener("mousemove", function(e) { moveDrag(e.clientX, e.clientY); });
  document.addEventListener("mouseup", endDrag);

  // Touch events
  divider.addEventListener("touchstart", function(e) {
    if (e.touches.length !== 1) return;
    e.preventDefault();
    const t = e.touches[0];
    startDrag(t.clientX, t.clientY);
  }, { passive: false });
  document.addEventListener("touchmove", function(e) {
    if (!dragging) return;
    e.preventDefault();
    const t = e.touches[0];
    moveDrag(t.clientX, t.clientY);
  }, { passive: false });
  document.addEventListener("touchend", endDrag);
  document.addEventListener("touchcancel", endDrag);
})();

// ─── Pinch-zoom on chat panel (shared setupZoom from util.js) ───
(function() {
  const chatContainer = document.getElementById("chatContainer");
  const chatWrapper = document.getElementById("chatWrapper");
  if (!chatContainer || !chatWrapper || typeof setupZoom === "undefined") return;

  // setupZoom's built-in resetOnDblclick fails here for two reasons:
  //   1. Desktop: dblclick event.target is a child element, never chatContainer
  //   2. Mobile:  the "pinch" filter blocks single-finger touches, so d3's
  //      internal double-tap detection never fires.
  // We disable it and handle both paths manually below.
  var zoom = setupZoom({
    container: d3.select(chatContainer),
    target: chatWrapper,
    mode: "css",
    scaleExtent: [0.5, 3],
    filter: "pinch",
    resetOnDblclick: false
  });

  function _resetChatZoom() {
    d3.select(chatContainer).transition().duration(300)
      .call(zoom.transform, d3.zoomIdentity);
  }
  function _isBubble(target) {
    return target && target.closest && target.closest(".msg-bubble");
  }

  // Desktop: double-click on empty area resets zoom.
  // Clicks on msg-bubble are handled by their own dblclick handler (with
  // stopPropagation), so they never reach here.
  chatContainer.addEventListener("dblclick", function(e) {
    if (_isBubble(e.target)) return;
    _resetChatZoom();
  });

  // Mobile: touchend-based double-tap (dblclick may not fire on all browsers
  // with touch-action: manipulation).
  onDoubleTap(chatContainer, function(synth) {
    if (_isBubble(synth.target)) return;
    _resetChatZoom();
  });
})();
