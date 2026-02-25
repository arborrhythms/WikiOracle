// wikioracle.js — WikiOracle client (conversation-based hierarchy)
// Preferences: served by config.yaml when writable; sessionStorage when stateless.
//
// Rendering pipeline:
//   llm.jsonl on disk
//     -> [jsonl_to_state] (bin/wikioracle_state.py)
//     -> GET /state -> client receives state JSON
//     -> [renderMessages] renders chat panel (selected conversation's messages)
//     -> [conversationsToHierarchy + renderTree] (d3tree.js) renders SVG tree
//
// State shape: { version, schema, time, context, conversations: [...tree...],
//                selected_conversation, truth: { trust: [...] } }
//
// Optimistic UI (sendMessage):
//   1. Client adds query entry with _pending:true (rendered at 0.6 opacity)
//   2. For new conversations, creates a temp conversation with tempId("c_")
//   3. Re-renders immediately via renderMessages()
//   4. Sends state to server; server adds only the response entry
//   5. On success: replaces state with server's authoritative response, re-renders
//   6. On error: reloads state from sessionStorage (stateless) or GET /state (stateful)
//
// State persistence:
//   Stateful:  POST /state after every mutation -> llm.jsonl on disk
//   Stateless: sessionStorage is authoritative; state sent with each /chat request

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

// ─── Server info (loaded on init) ───
let _serverInfo = { stateless: false, url_prefix: "" };

// ─── Preferences (derived in memory from config bundle) ───
let prefs = { provider: "wikioracle", layout: "flat", username: "User" };

const _STATE_KEY = "wikioracle_state";
const _CONFIG_KEY = "wikioracle_config";

// Config bundle in sessionStorage: { yaml: "<raw text>", parsed: {...}, prefs: {...} }
function _loadLocalConfig() {
  try {
    const raw = sessionStorage.getItem(_CONFIG_KEY);
    if (!raw) return null;
    const bundle = JSON.parse(raw);
    // Handle legacy format (raw YAML string, not a bundle)
    if (typeof bundle === "string") return null;
    return bundle;
  } catch { return null; }
}

function _saveLocalConfig(bundle) {
  try { sessionStorage.setItem(_CONFIG_KEY, JSON.stringify(bundle)); } catch {}
}

// Derive prefs from a parsed config dict — mirrors server's _derive_prefs()
function _derivePrefs(cfg) {
  const ui = (cfg && cfg.ui) || {};
  const chat = (cfg && cfg.chat) || {};
  const user = (cfg && cfg.user) || {};
  return {
    provider: ui.default_provider || "wikioracle",
    layout: ui.layout || "flat",
    username: user.name || "User",
    chat: {
      temperature: chat.temperature !== undefined ? chat.temperature : 0.7,
      message_window: chat.message_window !== undefined ? chat.message_window : 40,
      rag: chat.rag !== false,
      url_fetch: !!chat.url_fetch,
      confirm_actions: !!chat.confirm_actions,
    },
    theme: ui.theme || "system",
  };
}

// One-time migration: wikioracle_prefs → config bundle
async function _migratePrefsToConfig() {
  const _OLD_PREFS_KEY = "wikioracle_prefs";
  let oldPrefs;
  try {
    const raw = sessionStorage.getItem(_OLD_PREFS_KEY);
    if (!raw) return; // nothing to migrate
    oldPrefs = JSON.parse(raw);
  } catch { return; }

  const existing = _loadLocalConfig();
  if (existing && existing.prefs) {
    // Config bundle already exists — just clean up
    sessionStorage.removeItem(_OLD_PREFS_KEY);
    return;
  }

  // Build parsed config from old prefs
  const parsed = {
    user: { name: oldPrefs.username || "User" },
    ui: {
      default_provider: oldPrefs.provider || "wikioracle",
      layout: oldPrefs.layout || "flat",
    },
    chat: { ...(oldPrefs.chat || {}) },
  };
  if (oldPrefs.theme) parsed.ui.theme = oldPrefs.theme;

  // Fetch YAML text from server as seed (best-effort)
  let yamlText = "";
  // Check if legacy wikioracle_config had raw YAML text
  try {
    const raw = sessionStorage.getItem(_CONFIG_KEY);
    if (raw && typeof raw === "string") {
      const test = JSON.parse(raw);
      // If it parsed as a string (not object), it was raw YAML stored directly
      if (typeof test === "string") yamlText = test;
    }
  } catch {
    // Not JSON — might be raw YAML text stored directly
    try {
      const raw = sessionStorage.getItem(_CONFIG_KEY);
      if (raw) yamlText = raw;
    } catch {}
  }
  if (!yamlText) {
    try {
      const data = await api("GET", "/config");
      yamlText = data.yaml || "";
    } catch {}
  }

  _saveLocalConfig({ yaml: yamlText, parsed: parsed, prefs: _derivePrefs(parsed) });
  sessionStorage.removeItem(_OLD_PREFS_KEY);
}

function _loadLocalState() {
  try {
    const raw = sessionStorage.getItem(_STATE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function _saveLocalState() {
  try { sessionStorage.setItem(_STATE_KEY, JSON.stringify(state)); } catch {}
}

// Client-side merge: fold importState data into the live `state` object.
// Merges trust entries (by id, import wins), conversations (appended),
// and context (kept from current state — import context is not overwritten).
function _clientMerge(importState) {
  // Trust entries: merge by id (import overwrites duplicates)
  if (!state.truth) state.truth = {};
  if (!Array.isArray(state.truth.trust)) state.truth.trust = [];
  const incoming = (importState.truth && importState.truth.trust) || [];
  const byId = {};
  for (const e of state.truth.trust) { if (e.id) byId[e.id] = e; }
  for (const e of incoming) {
    if (e.id && byId[e.id]) {
      // Replace existing entry
      const idx = state.truth.trust.indexOf(byId[e.id]);
      if (idx >= 0) state.truth.trust[idx] = e;
    } else {
      state.truth.trust.push(e);
    }
  }

  // Conversations: merge by ID at every level of the tree.
  // Import wins for message content; children are recursively merged.
  if (!Array.isArray(state.conversations)) state.conversations = [];
  const importConvs = importState.conversations || [];

  function mergeConvLists(base, incoming) {
    const baseById = {};
    for (const c of base) { if (c.id) baseById[c.id] = c; }
    for (const inc of incoming) {
      const existing = inc.id ? baseById[inc.id] : null;
      if (existing) {
        // Merge messages by id: import wins for duplicates, appends new
        const msgById = {};
        for (const m of (existing.messages || [])) { if (m.id) msgById[m.id] = m; }
        for (const m of (inc.messages || [])) {
          if (m.id && msgById[m.id]) {
            const idx = existing.messages.indexOf(msgById[m.id]);
            if (idx >= 0) existing.messages[idx] = m;
          } else {
            existing.messages.push(m);
          }
        }
        // Update title if import has one
        if (inc.title) existing.title = inc.title;
        // Recursively merge children
        if (!existing.children) existing.children = [];
        mergeConvLists(existing.children, inc.children || []);
      } else {
        base.push(inc);
        if (inc.id) baseById[inc.id] = inc;
      }
    }
  }
  mergeConvLists(state.conversations, importConvs);

  // Context: keep current state context (don't overwrite)
}

// Persist state: sessionStorage is authoritative in stateless mode;
// disk-backed POST /state is used in stateful mode.
function _persistState() {
  if (_serverInfo.stateless) {
    _saveLocalState();
  } else {
    api("POST", "/state", state).catch(e => setStatus("Error: " + e.message));
  }
}

// Build the runtime_config dict from the current config bundle (stateless).
// This is the parsed config.yaml content that the server needs for
// provider resolution, chat settings, and user display name.
function _buildRuntimeConfig() {
  const bundle = _loadLocalConfig();
  return (bundle && bundle.parsed) ? bundle.parsed : {};
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
    // horizontal
    tree.style.width = "";
    if (!tree.style.height) tree.style.height = "220px";
  }
  if (typeof renderMessages === "function") renderMessages();
}

function applyTheme(theme) {
  // Set data-theme on <html> so CSS selectors activate the right variables
  var t = theme || "system";
  document.documentElement.setAttribute("data-theme", t);
}

// ─── Provider metadata (populated from /providers on init) ───
let _providerMeta = {};  // { "openai": { model: "gpt-4o", ... }, ... }

// ─── State (in-memory, synced from server) ───
// Shape: { version, schema, date, context, conversations: [...tree...],
//             selected_conversation, truth: { trust, retrieval_prefs } }
let state = null;

// ─── Selected conversation ───
// null = root selected (empty chat, typing creates new root conversation)
// string = conversation ID in the tree
let selectedConvId = null;

// Pending branch: when set, the next send creates a child of this conversation
let _pendingBranchParent = null;

// ─── Confirmation helper (skips dialog when confirm_actions is off) ───
function confirmAction(msg) {
  if (prefs.chat && prefs.chat.confirm_actions) return confirm(msg);
  return true;
}

// ─── API helpers ───
function _apiPath(path) {
  return (_serverInfo.url_prefix || "") + path;
}

async function api(method, path, body) {
  const headers = { "Content-Type": "application/json" };
  const opts = { method, headers };
  if (body) opts.body = JSON.stringify(body);
  const resp = await fetch(_apiPath(path), opts);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`HTTP ${resp.status}: ${text.slice(0, 200)}`);
  }
  return resp.json();
}

// ─── Conversation tree helpers (findInTree, removeFromTree, countTreeMessages, tempId in util.js) ───

function findConversation(conversations, convId) {
  return findInTree(conversations, convId);
}

// ─── Tree navigation ───

function navigateToNode(nodeId) {
  if (!state) return;
  selectedConvId = nodeId;
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
  selectedConvId = convId; // keep branch-from node highlighted in tree
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
  selectedConvId = null;
  state.selected_conversation = null;
  renderMessages();
  _persistState();
  setStatus(`Deleted "${conv.title}"`);
}

function mergeConversation(sourceId, targetId) {
  // Merge: combine all messages from source into target conversation.
  // Source's messages are appended after target's existing messages (preserving order).
  // Source is then removed from the tree. Source's children are re-parented under target.
  if (!state || !state.conversations) return;
  if (sourceId === targetId) return;
  if (targetId === "root") {
    setStatus("Cannot merge into root. Drag onto a conversation node.");
    return;
  }

  const source = findConversation(state.conversations, sourceId);
  const target = findConversation(state.conversations, targetId);
  if (!source || !target) return;

  // Append source messages after target's existing messages (no re-sorting)
  target.messages = [...(target.messages || []), ...(source.messages || [])];

  // Re-parent source's children under target
  if (source.children && source.children.length > 0) {
    if (!target.children) target.children = [];
    target.children.push(...source.children);
  }

  // Remove source from tree
  removeFromTree(state.conversations, sourceId);

  // If we were viewing the source, switch to target
  if (selectedConvId === sourceId) {
    selectedConvId = targetId;
    state.selected_conversation = targetId;
  }

  renderMessages();
  _persistState();
  setStatus(`Merged "${source.title}" into "${target.title}" (${target.messages.length} messages)`);
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
  selectedConvId = null;
  state.selected_conversation = null;
  renderMessages();
  _persistState();
  setStatus("All conversations deleted.");
}

function _splitAfterMessage(msgIdx) {
  if (!state || !selectedConvId) return;
  const conv = findConversation(state.conversations, selectedConvId);
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

  selectedConvId = newConv.id;
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

// Context menu for chat messages. Uses position:fixed to avoid clipping by
// the chat container's overflow. The _justOpened flag + 300ms grace period
// prevents the document-level click handler from immediately closing the menu.
function _showMsgContextMenu(event, msgIdx, totalMsgs) {
  _hideMsgContextMenu();

  const menu = document.createElement("div");
  menu.className = "tree-context-menu"; // reuse tree context menu style
  menu.style.position = "fixed";
  menu.style.left = event.clientX + 4 + "px";
  menu.style.top = event.clientY + 4 + "px";
  menu._justOpened = true;
  setTimeout(() => { menu._justOpened = false; }, 300);

  // Split (after) — mirrors "Branch..." on tree nodes
  if (msgIdx < totalMsgs - 1) {
    const splitItem = document.createElement("div");
    splitItem.className = "ctx-item";
    splitItem.textContent = "Split...";
    splitItem.addEventListener("click", (e) => { e.stopPropagation(); _hideMsgContextMenu(); _splitAfterMessage(msgIdx); });
    menu.appendChild(splitItem);
  }

  // Separator
  const sep = document.createElement("div");
  sep.className = "ctx-sep";
  menu.appendChild(sep);

  // Delete — mirrors tree node delete
  const delItem = document.createElement("div");
  delItem.className = "ctx-item ctx-danger";
  delItem.textContent = "Delete";
  delItem.addEventListener("click", (e) => { e.stopPropagation(); _hideMsgContextMenu(); _deleteMessage(msgIdx); });
  menu.appendChild(delItem);

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
  if (!state || !selectedConvId) return;
  const conv = findConversation(state.conversations, selectedConvId);
  if (!conv || !conv.messages) return;
  if (fromIdx < 0 || fromIdx >= conv.messages.length) return;
  if (toIdx < 0 || toIdx >= conv.messages.length) return;
  const [msg] = conv.messages.splice(fromIdx, 1);
  conv.messages.splice(toIdx, 0, msg);
  renderMessages();
  _persistState();
}

function _deleteMessage(msgIdx) {
  if (!state || !selectedConvId) return;
  const conv = findConversation(state.conversations, selectedConvId);
  if (!conv || !conv.messages) return;
  const msg = conv.messages[msgIdx];
  if (!msg) return;
  const preview = truncate(stripTags(msg.content), 60);
  if (!confirmAction(`Delete this message?\n"${preview}"`)) return;
  conv.messages.splice(msgIdx, 1);
  // If conversation is now empty, remove it too
  if (conv.messages.length === 0 && (!conv.children || conv.children.length === 0)) {
    removeFromTree(state.conversations, selectedConvId);
    selectedConvId = null;
    state.selected_conversation = null;
  }
  renderMessages();
  _persistState();
}

// ─── Spec defaults (cached after first fetch) ───
let _specDefaults = null;
async function _getSpecDefaults() {
  if (!_specDefaults) {
    try { _specDefaults = await api("GET", "/spec_defaults"); }
    catch (e) { _specDefaults = { context: "<div/>", output: "", config_yaml: "" }; }
  }
  return _specDefaults;
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
    overlay = document.createElement("div");
    overlay.id = "contextOverlay";
    overlay.className = "context-overlay";
    overlay.innerHTML = `
      <div class="context-panel">
        <h2>Context</h2>
        <p>Injected into every LLM call as background information.</p>
        <textarea id="contextTextarea" placeholder="Describe the project, key facts, instructions..."></textarea>
        <div class="settings-actions">
          <button class="btn" id="ctxReset">Reset</button>
          <button class="btn" id="ctxCancel">Cancel</button>
          <button class="btn btn-primary" id="ctxSave">Save</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);

    // Close on overlay background click
    overlay.addEventListener("click", function(e) {
      if (e.target === overlay) overlay.classList.remove("active");
    });
    document.getElementById("ctxReset").addEventListener("click", async function() {
      const defaults = await _getSpecDefaults();
      document.getElementById("contextTextarea").value = stripTags(defaults.context).trim();
    });
    document.getElementById("ctxCancel").addEventListener("click", function() {
      overlay.classList.remove("active");
    });
    document.getElementById("ctxSave").addEventListener("click", function() {
      const newText = document.getElementById("contextTextarea").value.trim();
      const currentPlain = stripTags(state?.context || "").trim();
      if (state && newText !== currentPlain) {
        state.context = newText;
        _persistState();
        setStatus("Context saved");
      }
      overlay.classList.remove("active");
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
    overlay = document.createElement("div");
    overlay.id = "outputOverlay";
    overlay.className = "context-overlay";
    overlay.innerHTML = `
      <div class="context-panel">
        <h2>Output</h2>
        <p>Instructions appended to every LLM call describing the desired response format.</p>
        <textarea id="outputTextarea" placeholder="Describe the desired output format..."></textarea>
        <div class="settings-actions">
          <button class="btn" id="outReset">Reset</button>
          <button class="btn" id="outCancel">Cancel</button>
          <button class="btn btn-primary" id="outSave">Save</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);

    overlay.addEventListener("click", function(e) {
      if (e.target === overlay) overlay.classList.remove("active");
    });
    document.getElementById("outCancel").addEventListener("click", function() {
      overlay.classList.remove("active");
    });
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
      overlay.classList.remove("active");
    });
  }

  // Populate from state (always present after server normalization)
  const current = state?.output ?? "";
  document.getElementById("outputTextarea").value = current;
  overlay.classList.add("active");
  document.getElementById("outputTextarea").focus();
}


// ─── UI rendering ───
// renderMessages: finds the selected conversation via findConversation(),
// iterates conv.messages to build .message divs (role-based alignment),
// attaches context-menu listeners (right-click -> Split/Delete), then
// calls conversationsToHierarchy() + renderTree() to sync the tree panel.
// Auto-scrolls chat container to bottom after render.
function renderMessages() {
  const wrapper = document.getElementById("chatWrapper");
  wrapper.innerHTML = "";

  if (!state) state = {};
  if (!Array.isArray(state.conversations)) state.conversations = [];

  const treeCallbacks = { onNavigate: navigateToNode, onBranch: branchFromNode, onDelete: deleteConversation, onMerge: mergeConversation, onEditContext: _toggleContextEditor, onEditTruth: _openTruthEditor, onDeleteAll: _deleteAllConversations };

  // Validate selectedConvId: if it points to a missing conversation, reset to root
  if (selectedConvId !== null && !findConversation(state.conversations, selectedConvId)) {
    selectedConvId = null;
    state.selected_conversation = null;
  }

  // Determine which messages to show
  // When _pendingBranchParent is set, show empty chat (ready for new branch)
  let visible = [];
  if (_pendingBranchParent) {
    // Empty chat — user is about to type a new branch message
  } else if (selectedConvId !== null) {
    const conv = findConversation(state.conversations, selectedConvId);
    if (conv) {
      visible = conv.messages || [];
    }
  }
  // else: root selected → empty chat

  console.log("[WikiOracle] renderMessages: selectedConv=", selectedConvId,
              "visible=", visible.length, "conversations=", state.conversations.length);

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

    // Drag-to-reorder messages (desktop only — touch uses tap gestures)
    if (window.matchMedia("(pointer: fine)").matches) {
      div.draggable = true;
    }
    div.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/plain", String(idx));
      div.classList.add("msg-dragging");
    });
    div.addEventListener("dragend", () => { div.classList.remove("msg-dragging"); });
    div.addEventListener("dragover", (e) => {
      e.preventDefault();
      div.classList.add("msg-dragover");
    });
    div.addEventListener("dragleave", () => { div.classList.remove("msg-dragover"); });
    div.addEventListener("drop", (e) => {
      e.preventDefault();
      div.classList.remove("msg-dragover");
      const fromIdx = parseInt(e.dataTransfer.getData("text/plain"), 10);
      const toIdx = idx;
      if (!isNaN(fromIdx) && fromIdx !== toIdx) _moveMessage(fromIdx, toIdx);
    });

    // Context menu (right-click / long-press) for message actions
    div.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      e.stopPropagation();
      _showMsgContextMenu(e, idx, visible.length);
    });

    // Double-click to open context menu (desktop)
    div.addEventListener("dblclick", (e) => {
      e.preventDefault();
      e.stopPropagation();
      _showMsgContextMenu(e, idx, visible.length);
    });

    // Double-tap detection (mobile — dblclick doesn't fire on most touch browsers)
    onDoubleTap(div, (synth) => { _showMsgContextMenu(synth, idx, visible.length); });

    wrapper.appendChild(div);
  }

  // Show placeholder when at root or empty conversation
  if (visible.length === 0) {
    const placeholder = document.createElement("div");
    placeholder.className = "chat-placeholder";
    if (_pendingBranchParent) {
      placeholder.textContent = "Type a message to create a new branch.";
    } else if (selectedConvId === null) {
      placeholder.textContent = "Type a message to start a new conversation.";
    } else {
      placeholder.textContent = "No messages in this conversation.";
    }
    wrapper.appendChild(placeholder);
  }

  // Scroll chat
  const container = document.getElementById("chatContainer");
  container.scrollTop = container.scrollHeight;

  // Render D3 tree
  try {
    if (typeof conversationsToHierarchy === "function" && typeof renderTree === "function") {
      const treeData = conversationsToHierarchy(state.conversations, selectedConvId);
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

function _updatePlaceholder() {
  const input = document.getElementById("msgInput");
  const meta = _providerMeta[prefs.provider];
  const name = meta ? meta.name : prefs.provider;
  input.placeholder = `Message ${name}...`;
}

// ─── Send message ───
async function sendMessage() {
  const input = document.getElementById("msgInput");
  const text = input.value.trim();
  if (!text) return;

  // Check provider readiness before sending
  if (!_providerReady()) {
    const meta = _providerMeta[prefs.provider] || {};
    setStatus(`${meta.name || prefs.provider} requires an API key. Add it in Settings \u2192 config.yaml.`);
    return;
  }

  input.value = "";
  input.style.height = "auto";
  document.getElementById("btnSend").disabled = true;
  setStatus("Sending...");

  // Determine how to route this message:
  //   _pendingBranchParent set → create child of that conversation (branch_from)
  //   selectedConvId !== null → append to that conversation (conversation_id)
  //   selectedConvId === null → new root conversation (neither)
  let conversationId = null;
  let branchFrom = null;
  let isNewRoot = false;

  if (_pendingBranchParent) {
    branchFrom = _pendingBranchParent;
    _pendingBranchParent = null;
  } else if (selectedConvId !== null) {
    conversationId = selectedConvId;
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
    username: prefs.username || "User",
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
    selectedConvId = optConvId;
  }
  renderMessages();

  try {
    const chatBody = {
      message: text,
      conversation_id: conversationId || undefined,
      branch_from: branchFrom || undefined,
      prefs: {
        provider: prefs.provider,
        model: (_providerMeta[prefs.provider] || {}).model || "",
        username: prefs.username,
        chat: prefs.chat || {},
      },
    };
    // Stateless: include authoritative state + runtime_config
    if (_serverInfo.stateless) {
      chatBody.state = state;
      chatBody.runtime_config = _buildRuntimeConfig();
    }
    const data = await api("POST", "/chat", chatBody);
    state = data.state || state;
    if (!Array.isArray(state.conversations)) state.conversations = [];

    // Server sets selected_conversation; use it
    if (state.selected_conversation) {
      selectedConvId = state.selected_conversation;
    }

    _persistState();
    renderMessages();
    setStatus("Ready");
  } catch (e) {
    // Rollback: reload state from sessionStorage (stateless) or server (stateful)
    try {
      if (_serverInfo.stateless) {
        const localState = _loadLocalState();
        if (localState) state = localState;
      } else {
        const data = await api("GET", "/state");
        state = data.state || state;
      }
    } catch {}
    if (isNewRoot || branchFrom) selectedConvId = null;
    renderMessages();
    setStatus("Error: " + e.message);
  } finally {
    document.getElementById("btnSend").disabled = false;
    input.focus();
  }
}

// ─── Settings panel ───
function openSettings() {
  document.getElementById("setUsername").value = prefs.username || "User";
  document.getElementById("setProvider").value = prefs.provider || "wikioracle";
  document.getElementById("setLayout").value = prefs.layout || "flat";
  document.getElementById("setTheme").value = prefs.theme || "system";

  // Chat settings
  const chat = prefs.chat || {};
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
  const meta = _providerMeta[newProvider];
  if (meta && meta.needs_key && !meta.has_key) {
    setStatus(`${meta.name} requires an API key. Add it to config.yaml (Settings \u2192 Edit Config).`);
    // Still save — user might add the key later — but warn them
  }

  prefs.provider = newProvider;
  prefs.username = document.getElementById("setUsername").value.trim() || "User";
  prefs.layout = document.getElementById("setLayout").value;
  prefs.theme = document.getElementById("setTheme").value || "system";

  // Chat settings
  prefs.chat = {
    ...(prefs.chat || {}),
    temperature: parseFloat(document.getElementById("setTemp").value),
    message_window: parseInt(document.getElementById("setWindow").value, 10),
    rag: document.getElementById("setRag").checked,
    url_fetch: document.getElementById("setUrlFetch").checked,
    confirm_actions: document.getElementById("setConfirm").checked,
  };

  applyLayout(prefs.layout);
  applyTheme(prefs.theme);
  _updatePlaceholder();
  closeSettings();

  // Persist: patch config bundle in stateless mode, server otherwise
  if (_serverInfo.stateless) {
    const bundle = _loadLocalConfig() || { yaml: "", parsed: {}, prefs: {} };
    // Patch parsed config to reflect the settings changes
    bundle.parsed = bundle.parsed || {};
    bundle.parsed.user = bundle.parsed.user || {};
    bundle.parsed.user.name = prefs.username;
    bundle.parsed.ui = bundle.parsed.ui || {};
    bundle.parsed.ui.default_provider = prefs.provider;
    bundle.parsed.ui.layout = prefs.layout;
    bundle.parsed.ui.theme = prefs.theme;
    bundle.parsed.chat = bundle.parsed.chat || {};
    Object.assign(bundle.parsed.chat, {
      temperature: prefs.chat.temperature,
      message_window: prefs.chat.message_window,
      rag: prefs.chat.rag,
      url_fetch: prefs.chat.url_fetch,
      confirm_actions: prefs.chat.confirm_actions,
    });
    bundle.prefs = { ...prefs };
    _saveLocalConfig(bundle);
    setStatus("Settings saved (local)");
  } else {
    try {
      await api("POST", "/prefs", {
        provider: prefs.provider,
        username: prefs.username,
        layout: prefs.layout,
        theme: prefs.theme,
        chat: prefs.chat,
      });
      // Refresh provider metadata (has_key may have changed via config.yaml)
      await _refreshProviderMeta();
      setStatus("Settings saved");
    } catch (e) {
      setStatus("Error saving settings: " + e.message);
    }
  }
}

// ─── Config editor (edit config.yaml) ───
async function _openConfigEditor() {
  // Close the settings panel first
  closeSettings();

  let overlay = document.getElementById("configOverlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "configOverlay";
    overlay.className = "context-overlay"; // reuse context overlay style
    overlay.innerHTML = `
      <div class="context-panel config-panel">
        <h2>config.yaml</h2>
        <textarea id="configEditorTextarea" class="config-textarea"></textarea>
        <div id="configEditorError" class="config-error"></div>
        <div class="settings-actions settings-actions-md">
          <button class="btn" id="cfgReset">Reset</button>
          <button class="btn" id="cfgCancel">Cancel</button>
          <button class="btn btn-primary" id="cfgOk">OK</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);

    overlay.addEventListener("click", function(e) {
      if (e.target === overlay) overlay.classList.remove("active");
    });
    document.getElementById("cfgReset").addEventListener("click", async function() {
      const defaults = await _getSpecDefaults();
      if (defaults.config_yaml) {
        document.getElementById("configEditorTextarea").value = defaults.config_yaml;
      } else {
        setStatus("spec/config.yaml not found");
      }
    });
    document.getElementById("cfgCancel").addEventListener("click", function() {
      overlay.classList.remove("active");
    });
    document.getElementById("cfgOk").addEventListener("click", async function() {
      const textarea = document.getElementById("configEditorTextarea");
      const errEl = document.getElementById("configEditorError");
      errEl.style.display = "none";

      // Parse YAML via server → get parsed dict + derived prefs
      let parsed, derivedPrefs;
      try {
        const resp = await api("POST", "/parse_config", { yaml: textarea.value });
        if (!resp.ok) {
          errEl.textContent = resp.error || "Unknown error";
          errEl.style.display = "block";
          return;
        }
        parsed = resp.parsed;
        derivedPrefs = resp.prefs;
      } catch (e) {
        errEl.textContent = "Parse error: " + e.message;
        errEl.style.display = "block";
        return;
      }

      // Save config bundle to sessionStorage (single source of truth)
      _saveLocalConfig({ yaml: textarea.value, parsed: parsed, prefs: derivedPrefs });

      // Update in-memory prefs and apply UI changes
      prefs = derivedPrefs;
      applyLayout(prefs.layout);
      _updatePlaceholder();

      // Disk write in non-stateless mode
      if (!_serverInfo.stateless) {
        try {
          await api("POST", "/config", { yaml: textarea.value });
        } catch (e) {
          errEl.textContent = "Disk write failed: " + e.message + " (saved to sessionStorage)";
          errEl.style.display = "block";
          return;
        }
      }

      overlay.classList.remove("active");
      // Refresh prefs + provider metadata (keys may have changed)
      try {
        var prefsData = await api("GET", "/prefs");
        if (prefsData.prefs) Object.assign(prefs, prefsData.prefs);
        applyTheme(prefs.theme);
      } catch (e) { /* best effort */ }
      await _refreshProviderMeta();
      setStatus("config.yaml saved");
    });
  }

  // Load current config
  const textarea = document.getElementById("configEditorTextarea");
  const errEl = document.getElementById("configEditorError");
  errEl.style.display = "none";
  textarea.value = "Loading...";
  overlay.classList.add("active");

  // Load YAML text: config bundle (stateless) or server
  const bundle = _serverInfo.stateless ? _loadLocalConfig() : null;
  if (bundle && bundle.yaml) {
    textarea.value = bundle.yaml;
  } else {
    try {
      const data = await api("GET", "/config");
      textarea.value = data.yaml || "";
    } catch (e) {
      textarea.value = "# Error loading config: " + e.message;
    }
  }
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
    overlay = document.createElement("div");
    overlay.id = "truthOverlay";
    overlay.className = "context-overlay";
    overlay.innerHTML = `
      <div class="context-panel trust-panel">
        <h2>Trust</h2>
        <div id="truthListView">
          <div id="truthEntries" class="trust-entries-scroll"></div>
          <div class="settings-actions settings-actions-xs">
            <button class="btn" id="truthAdd">Add Entry</button>
            <button class="btn" id="truthAddImpl">Add Implication</button>
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
          <input id="implTitle" type="text" class="trust-input" placeholder="A \u2192 B (derived)">
          <label class="trust-label">Antecedent <span class="trust-label-hint">(if this entry is believed\u2026)</span></label>
          <select id="implAntecedent" class="trust-input"></select>
          <label class="trust-label">Consequent <span class="trust-label-hint">(\u2026then raise certainty of this entry)</span></label>
          <select id="implConsequent" class="trust-input"></select>
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
      </div>`;
    document.body.appendChild(overlay);

    overlay.addEventListener("click", function(e) {
      if (e.target === overlay) { overlay.classList.remove("active"); _truthEditing = null; }
    });

    document.getElementById("truthClose").addEventListener("click", function() {
      overlay.classList.remove("active");
      _truthEditing = null;
    });

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
      const implType = document.getElementById("implType").value;
      const now = new Date().toISOString().replace(/\.\d+Z$/, "Z");

      if (!ant || !con) return;

      const content = "<implication><antecedent>" + ant + "</antecedent><consequent>" + con + "</consequent><type>" + implType + "</type></implication>";

      if (_truthEditing === "new_impl") {
        const entry = { id: tempId("i_"), title: title, certainty: 0, content: content, time: now };
        state.truth.trust.push(entry);
      } else if (typeof _truthEditing === "number") {
        const entry = state.truth.trust[_truthEditing];
        if (entry) {
          entry.title = title;
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
}

function _truthShowEditView() {
  document.getElementById("truthListView").style.display = "none";
  document.getElementById("truthEditView").style.display = "";
  document.getElementById("truthImplView").style.display = "none";
  document.getElementById("truthTitle").focus();
}

function _truthShowImplView() {
  document.getElementById("truthListView").style.display = "none";
  document.getElementById("truthEditView").style.display = "none";
  document.getElementById("truthImplView").style.display = "";
  document.getElementById("implTitle").focus();
}

function _isImplication(entry) {
  return entry && typeof entry.content === "string" && entry.content.indexOf("<implication") !== -1;
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
  for (var i = 0; i < entries.length; i++) {
    var e = entries[i];
    if (_isImplication(e)) continue; // skip implication entries themselves
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
    const row = document.createElement("div");
    row.style.cssText = "display:flex; align-items:center; gap:0.5rem; padding:0.35rem 0; border-bottom:1px solid var(--border); font-size:0.82rem;";

    if (isImpl) {
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
    editBtn.addEventListener("click", (function(idx, isImplication) {
      return function() {
        _truthEditing = idx;
        const e = state.truth.trust[idx];
        if (isImplication) {
          const implData = _parseImplContent(e.content);
          document.getElementById("implTitle").value = e.title || "";
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
    })(i, isImpl));
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
const _READING_CSS_FALLBACK = `
body { font-family: Georgia, serif; line-height: 1.8; color: #1a1a1a; background: #fafaf8; max-width: 52rem; margin: 0 auto; padding: 2rem 1.5rem; }
h1 { font-size: 1.6rem; margin-bottom: 0.5rem; }
.meta { font-size: 0.85rem; color: #888; margin-bottom: 2rem; padding-bottom: 1rem; border-bottom: 1px solid #e0e0e0; }
.conversation { margin-bottom: 1.5rem; padding-left: 1.2rem; border-left: 2px solid #d0d0d0; }
.conv-title { font-size: 0.9rem; font-weight: 600; color: #555; margin-bottom: 0.6rem; }
p.message { margin-bottom: 0.6rem; font-size: 0.95rem; white-space: pre-wrap; }
p.message strong { font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.04em; }
p.message.user strong { color: #2563eb; }
p.message.assistant strong { color: #059669; }
`;

function _serializeConversations(conversations) {
  if (!conversations || !conversations.length) return "";
  let html = "";
  for (const conv of conversations) {
    const title = escapeHtml(conv.title || "Untitled");
    html += `<div class="conversation" data-id="${conv.id || ''}">\n`;
    html += `  <div class="conv-title">${title}</div>\n`;
    for (const msg of (conv.messages || [])) {
      const role = msg.role || "user";
      const username = escapeHtml(msg.username || role);
      const escaped = escapeHtml(stripTags(msg.content).trim());
      html += `  <p class="message ${role}" data-role="${role}"><strong>${username}:</strong> ${escaped}</p>\n`;
    }
    // Recurse into children
    if (conv.children && conv.children.length) {
      html += _serializeConversations(conv.children);
    }
    html += `</div>\n`;
  }
  return html;
}

async function _openReadView() {
  if (!state || !state.conversations || !state.conversations.length) {
    setStatus("No conversations to display.");
    return;
  }

  // Fetch reading.css and inline it
  let css = _READING_CSS_FALLBACK;
  try {
    const resp = await fetch(_apiPath("/reading.css"));
    if (resp.ok) {
      css = await resp.text();
    }
  } catch (e) {
    // fallback CSS already set
  }

  const body = _serializeConversations(state.conversations);
  const now = new Date().toLocaleString();
  const doc = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">
<title>WikiOracle — Read View</title>
<style>
${css}
/* d3 pinch-zoom support */
#reading-content { transform-origin: top center; }
</style>
</head>
<body>
<article id="reading-content">
<h1>WikiOracle</h1>
<div class="meta">Exported ${now} — ${state.conversations.length} root conversation${state.conversations.length !== 1 ? "s" : ""}</div>
${body}
</article>
<script src="https://d3js.org/d3.v7.min.js"><\/script>
<script>
// Optional d3 pinch-zoom on the reading content
(function() {
  if (typeof d3 === "undefined") return;
  var content = document.getElementById("reading-content");
  var zoom = d3.zoom()
    .scaleExtent([0.5, 4])
    .filter(function(event) {
      if (event.type === "wheel") return event.ctrlKey;
      if (event.type === "touchstart" || event.type === "touchmove") return event.touches.length >= 2;
      return false;
    })
    .on("zoom", function(event) {
      content.style.transform = "scale(" + event.transform.k + ")";
    });
  d3.select(document.body).call(zoom).on("dblclick.zoom", null);
})();
<\/script>
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
        for (let i = 1; i < lines.length; i++) {
          const rec = JSON.parse(lines[i]);
          if (rec.type === "conversation") {
            const { type, ...rest } = rec;
            convRecords.push(rest);
          } else if (rec.type === "trust") {
            const { type, ...rest } = rec;
            importState.truth.trust.push(rest);
          }
        }
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
      }

      if (!importState.schema || !importState.schema.includes("llm_state")) throw new Error("Not a WikiOracle state file");

      // Merge: client-side in stateless mode, server-side otherwise
      if (_serverInfo.stateless) {
        _clientMerge(importState);
      } else {
        const result = await api("POST", "/merge", { state: importState });
        state = result.state || state;
      }

      // Persist merged state and redraw all components
      _persistState();
      selectedConvId = null;
      renderMessages();

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
      setStatus("Import error: " + err.message);
      const input = document.getElementById("msgInput");
      const savedPH = input.placeholder;
      input.placeholder = "Import error: " + err.message;
      setTimeout(() => { input.placeholder = savedPH; }, 5000);
    }
    e.target.value = "";
  });

  // Settings
  document.getElementById("btnSettings").addEventListener("click", openSettings);
  document.getElementById("btnSettingsCancel").addEventListener("click", closeSettings);
  document.getElementById("btnSettingsSave").addEventListener("click", function() { saveSettings(); });
  document.getElementById("btnSend").addEventListener("click", sendMessage);
  document.getElementById("setTemp").addEventListener("input", function() {
    document.getElementById("setTempVal").textContent = this.value;
  });
  document.getElementById("setWindow").addEventListener("input", function() {
    document.getElementById("setWindowVal").textContent = this.value;
  });
  document.getElementById("settingsOverlay").addEventListener("click", function(e) {
    // Close settings when clicking the background overlay (not the panel itself)
    if (e.target === this) closeSettings();
  });

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
}

// ─── Init: load prefs + state from server ───
async function init() {
  try {
    setStatus("Loading...");

    // 0) Load server info (stateless flag, url_prefix)
    //    url_prefix is detected from the page URL: if we're at /chat/,
    //    API calls go to /chat/state etc.  Fallback: ask the server.
    const pagePath = window.location.pathname.replace(/\/+$/, "");
    if (pagePath && pagePath !== "/") {
      _serverInfo.url_prefix = pagePath;
    }
    try {
      const info = await api("GET", "/server_info");
      _serverInfo = info;
      // If server tells us a prefix and we didn't already detect one, use it
      if (info.url_prefix && !pagePath) _serverInfo.url_prefix = info.url_prefix;
    } catch (e) {
      console.warn("[WikiOracle] Failed to load server_info:", e);
    }

    if (_serverInfo.stateless) {
      await _initStateless();
    } else {
      await _initStateful();
    }

    // Apply layout, theme, and update placeholder from prefs
    applyLayout(prefs.layout);
    applyTheme(prefs.theme);
    _updatePlaceholder();

    // Restore selected conversation from state
    if (state.selected_conversation && findConversation(state.conversations, state.selected_conversation)) {
      selectedConvId = state.selected_conversation;
    } else {
      selectedConvId = null; // root
    }

    const convCount = state.conversations.length;
    console.log("[WikiOracle] init: loaded", convCount, "root conversations");
    renderMessages();
    setStatus(`Loaded ${convCount} conversation${convCount !== 1 ? "s" : ""}`);
  } catch (e) {
    console.error("[WikiOracle] init error:", e);
    setStatus("Connection error: " + e.message);
  }
}

// Stateless init: sessionStorage is authoritative.
// If sessionStorage has data, use it directly — no server calls needed for
// state or config.  If sessionStorage is empty, call /bootstrap once to seed.
async function _initStateless() {
  // Migrate legacy prefs → config bundle (one-time)
  await _migratePrefsToConfig();

  const localConfig = _loadLocalConfig();
  const localState = _loadLocalState();
  const needsBootstrap = !localConfig || !localState;

  if (needsBootstrap) {
    console.log("[WikiOracle] stateless: bootstrapping from server");
    try {
      const boot = await api("GET", "/bootstrap");

      // Seed config bundle
      if (!localConfig) {
        const seedPrefs = boot.prefs || _derivePrefs(boot.parsed || {});
        _saveLocalConfig({
          yaml: boot.config_yaml || "",
          parsed: boot.parsed || {},
          prefs: seedPrefs,
        });
        prefs = seedPrefs;
      } else {
        prefs = localConfig.prefs;
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

      // Provider metadata
      if (boot.providers) {
        _providerMeta = boot.providers;
        _populateProviderDropdown();
      }
    } catch (e) {
      console.warn("[WikiOracle] bootstrap failed:", e);
      // Fall back to defaults
      if (localConfig && localConfig.prefs) prefs = localConfig.prefs;
      state = localState || {};
      if (!Array.isArray(state.conversations)) state.conversations = [];
    }
  } else {
    // Both sessionStorage keys present — use them directly, no server calls
    console.log("[WikiOracle] stateless: using sessionStorage (no server calls)");
    prefs = localConfig.prefs;
    state = localState;
    if (!Array.isArray(state.conversations)) state.conversations = [];

    // Provider metadata: try server, but don't block
    try {
      const provData = await api("GET", "/providers");
      _providerMeta = provData.providers || {};
    } catch {}
    _populateProviderDropdown();
  }
}

// Stateful init: server disk is authoritative.
async function _initStateful() {
  // Load prefs from server
  try {
    const prefData = await api("GET", "/prefs");
    prefs = prefData.prefs || prefs;
  } catch (e) {
    console.warn("[WikiOracle] Failed to load prefs:", e);
  }

  // Load provider metadata
  try {
    const provData = await api("GET", "/providers");
    _providerMeta = provData.providers || {};
    _populateProviderDropdown();
  } catch {}

  // Load state from server (disk)
  const data = await api("GET", "/state");
  state = data.state || {};
  if (!Array.isArray(state.conversations)) state.conversations = [];
}

// Refresh provider metadata from server (updates has_key flags)
async function _refreshProviderMeta() {
  try {
    var provData = await api("GET", "/providers");
    _providerMeta = provData.providers || {};
    _populateProviderDropdown();
  } catch (e) {
    console.warn("[WikiOracle] Failed to refresh provider metadata:", e);
  }
}

// Populate the provider <select> dropdown from _providerMeta
function _populateProviderDropdown() {
  const sel = document.getElementById("setProvider");
  sel.innerHTML = "";
  for (const [key, info] of Object.entries(_providerMeta)) {
    const opt = document.createElement("option");
    opt.value = key;
    const keyWarning = (info.needs_key && !info.has_key) ? " \u26a0 no key" : "";
    opt.textContent = info.name + (info.model ? ` (${info.model})` : "") + keyWarning;
    sel.appendChild(opt);
  }
}

// Check if the currently selected provider can accept messages
function _providerReady() {
  var meta = _providerMeta[prefs.provider];
  if (!meta) return true;  // unknown provider — let server decide
  if (!meta.needs_key) return true;
  if (meta.has_key) return true;
  // In stateless mode, check local config for client-supplied key
  if (_serverInfo.stateless) {
    var bundle = _loadLocalConfig();
    var rc = (bundle && bundle.parsed) || {};
    var rcKey = ((rc.providers || {})[prefs.provider] || {}).api_key;
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
  setupZoom({
    container: d3.select(chatContainer),
    target: chatWrapper,
    mode: "css",
    scaleExtent: [0.5, 3],
    filter: "pinch",
    resetOnDblclick: true
  });
})();
