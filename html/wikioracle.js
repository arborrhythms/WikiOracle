// wikioracle.js — WikiOracle v2 client (conversation-based hierarchy)
// Preferences: served by config.yaml when writable; localStorage when stateless.

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

// ─── Preferences (loaded from server on init, localStorage overlay in stateless) ───
let prefs = { provider: "wikioracle", layout: "flat", username: "User" };
const _PREFS_KEY = "wikioracle_prefs";

function _loadLocalPrefs() {
  try {
    const raw = localStorage.getItem(_PREFS_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function _saveLocalPrefs() {
  try { localStorage.setItem(_PREFS_KEY, JSON.stringify(prefs)); } catch {}
}

const _STATE_KEY = "wikioracle_state";
const _CONFIG_KEY = "wikioracle_config";

function _loadLocalState() {
  try {
    const raw = localStorage.getItem(_STATE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function _saveLocalState() {
  try { localStorage.setItem(_STATE_KEY, JSON.stringify(state)); } catch {}
}

// Persist state: always POST to server (keeps _MEMORY_STATE in sync);
// also save to localStorage in stateless mode as client-side backup.
function _persistState() {
  if (_serverInfo.stateless) _saveLocalState();
  api("POST", "/state", state).catch(e => setStatus("Error: " + e.message));
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

// ─── Provider metadata (populated from /providers on init) ───
let _providerMeta = {};  // { "openai": { model: "gpt-4o", ... }, ... }

// ─── State (in-memory, synced from server) ───
// v2 shape: { version, schema, date, context, conversations: [...tree...],
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
function renderMessages() {
  const wrapper = document.getElementById("chatWrapper");
  wrapper.innerHTML = "";

  if (!state) state = {};
  if (!Array.isArray(state.conversations)) state.conversations = [];

  const treeCallbacks = { onNavigate: navigateToNode, onBranch: branchFromNode, onDelete: deleteConversation, onMerge: mergeConversation, onEditContext: _toggleContextEditor, onDeleteAll: _deleteAllConversations };

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
    const data = await api("POST", "/chat", {
      message: text,
      conversation_id: conversationId || undefined,
      branch_from: branchFrom || undefined,
      prefs: {
        provider: prefs.provider,
        model: (_providerMeta[prefs.provider] || {}).model || "",
        username: prefs.username,
        chat: prefs.chat || {},
      },
    });
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
    // Rollback: reload state from server
    try {
      const data = await api("GET", "/state");
      state = data.state || state;
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
  prefs.provider = document.getElementById("setProvider").value;
  prefs.username = document.getElementById("setUsername").value.trim() || "User";
  prefs.layout = document.getElementById("setLayout").value;

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
  _updatePlaceholder();
  closeSettings();

  // Persist prefs: localStorage in stateless mode, server otherwise
  if (_serverInfo.stateless) {
    _saveLocalPrefs();
    setStatus("Settings saved (local)");
  } else {
    try {
      await api("POST", "/prefs", {
        provider: prefs.provider,
        username: prefs.username,
        layout: prefs.layout,
        chat: prefs.chat,
      });
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
      <div class="context-panel" style="max-width:560px;">
        <h2>config.yaml</h2>
        <textarea id="configEditorTextarea" style="width:100%; min-height:300px; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:0.82rem; line-height:1.5; tab-size:2; resize:vertical; padding:0.6rem; border:1px solid var(--border); border-radius:6px;"></textarea>
        <div id="configEditorError" style="display:none; color:#dc2626; font-size:0.8rem; margin-top:0.4rem;"></div>
        <div class="settings-actions" style="margin-top:0.8rem;">
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

      // Always persist to localStorage first (shared path)
      try { localStorage.setItem(_CONFIG_KEY, textarea.value); } catch {}

      // Then attempt disk write if server is writable
      if (!_serverInfo.stateless) {
        try {
          const resp = await api("POST", "/config", { yaml: textarea.value });
          if (resp.ok) {
            overlay.classList.remove("active");
            setStatus("config.yaml saved");
            return;
          }
          errEl.textContent = resp.error || "Unknown error";
          errEl.style.display = "block";
          return;
        } catch (e) {
          // Disk write failed — localStorage already has the data
          if (!e.message || !e.message.includes("403")) {
            errEl.textContent = "Disk write failed: " + e.message + " (saved to localStorage)";
            errEl.style.display = "block";
            return;
          }
          // 403 = stateless, fall through to success
        }
      }
      overlay.classList.remove("active");
      setStatus("config.yaml saved (localStorage)");
    });
  }

  // Load current config
  const textarea = document.getElementById("configEditorTextarea");
  const errEl = document.getElementById("configEditorError");
  errEl.style.display = "none";
  textarea.value = "Loading...";
  overlay.classList.add("active");

  if (_serverInfo.stateless) {
    const saved = localStorage.getItem(_CONFIG_KEY);
    if (saved !== null) {
      textarea.value = saved;
    } else {
      // First open: seed from server's spec defaults
      try {
        const data = await api("GET", "/config");
        textarea.value = data.yaml || "";
      } catch (e) {
        textarea.value = "# Error loading config: " + e.message;
      }
    }
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
  // Export (v2 JSONL)
  document.getElementById("btnExport").addEventListener("click", function() {
    if (!state) { setStatus("No state to export"); return; }
    const now = new Date();
    const pad2 = n => String(n).padStart(2, "0");
    const fn = `llm_${now.getFullYear()}.${pad2(now.getMonth()+1)}.${pad2(now.getDate())}.${pad2(now.getHours())}${pad2(now.getMinutes())}.jsonl`;

    // Build v2 JSONL
    const lines = [];
    const header = {
      type: "header", version: 2,
      schema: state.schema || "https://raw.githubusercontent.com/arborrhythms/WikiOracle/main/spec/llm_state_v2.json",
      date: new Date().toISOString(),
      context: state.context || "<div/>",
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
      // Parse: send to server which handles both v1 and v2
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
          date: first.date || "",
          context: first.context || "<div/>",
          conversations: [],
          messages: [],
          selected_conversation: first.selected_conversation || null,
          truth: { trust: [], retrieval_prefs: first.retrieval_prefs || {} },
        };
        if (first.active_path) importState.active_path = first.active_path;
        const convRecords = [];
        for (let i = 1; i < lines.length; i++) {
          const rec = JSON.parse(lines[i]);
          if (rec.type === "conversation") {
            const { type, ...rest } = rec;
            convRecords.push(rest);
          } else if (rec.type === "message") {
            const { type, ...rest } = rec;
            importState.messages.push(rest);
          } else if (rec.type === "trust") {
            const { type, ...rest } = rec;
            importState.truth.trust.push(rest);
          }
        }
        // If v2 conversations found, nest them
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
          delete importState.messages;
        }
      } else {
        importState = JSON.parse(text);
      }

      if (!importState.schema || !importState.schema.includes("llm_state")) throw new Error("Not a WikiOracle state file");

      // Merge into current state via server
      const result = await api("POST", "/merge", { state: importState });
      state = result.state || state;
      selectedConvId = null;
      renderMessages();
      const convCount = (state.conversations || []).length;
      setStatus(`Imported: ${file.name} (${convCount} conversations)`);
    } catch (err) {
      setStatus("Import error: " + err.message);
    }
    e.target.value = "";
  });

  // Settings
  document.getElementById("btnSettings").addEventListener("click", openSettings);
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

    // (stateless mode: config editor uses localStorage — button stays enabled)

    // 1) Load prefs: server defaults first, then localStorage overlay in stateless mode
    try {
      const prefData = await api("GET", "/prefs");
      prefs = prefData.prefs || prefs;
    } catch (e) {
      console.warn("[WikiOracle] Failed to load prefs:", e);
    }
    if (_serverInfo.stateless) {
      const local = _loadLocalPrefs();
      if (local) {
        // Merge: local overrides server defaults, preserving nested chat keys
        const serverChat = prefs.chat || {};
        Object.assign(prefs, local);
        prefs.chat = { ...serverChat, ...(local.chat || {}) };
      }
    }

    // 2) Load provider metadata and populate dropdown
    try {
      const provData = await api("GET", "/providers");
      _providerMeta = provData.providers || {};
      const sel = document.getElementById("setProvider");
      sel.innerHTML = "";
      for (const [key, info] of Object.entries(_providerMeta)) {
        const opt = document.createElement("option");
        opt.value = key;
        opt.textContent = info.name + (info.model ? ` (${info.model})` : "");
        sel.appendChild(opt);
      }
    } catch {}

    // 3) Apply layout, CSS overrides, and update placeholder from prefs
    applyLayout(prefs.layout);
    _updatePlaceholder();

    // Inject CSS overrides from config (ui.css section)
    if (prefs.css) {
      let styleEl = document.getElementById("wikioracle-css-override");
      if (!styleEl) {
        styleEl = document.createElement("style");
        styleEl.id = "wikioracle-css-override";
        document.head.appendChild(styleEl);
      }
      styleEl.textContent = prefs.css;
    }

    // 4) Load state: server provides seed defaults; localStorage is the full
    //    persistent copy in stateless mode (conversations, context, output, etc.)
    const data = await api("GET", "/state");
    state = data.state || {};
    if (!Array.isArray(state.conversations)) state.conversations = [];
    if (_serverInfo.stateless) {
      const localState = _loadLocalState();
      if (localState) {
        // Full override: localStorage IS the state in stateless mode.
        // Preserve server-provided schema/version, but take everything else from local.
        const serverVersion = state.version;
        const serverSchema = state.schema;
        Object.assign(state, localState);
        if (serverVersion) state.version = serverVersion;
        if (serverSchema) state.schema = serverSchema;
        if (!Array.isArray(state.conversations)) state.conversations = [];
      }
    }

    // Restore selected conversation from server state
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

// ─── Boot ───
bindEvents();
init();
