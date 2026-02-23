// wikioracle.js — WikiOracle v2 client (conversation-based hierarchy)

// ─── Cookie helpers (wo_prefs) ───
function b64urlEncode(str) {
  return btoa(unescape(encodeURIComponent(str))).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/g,"");
}
function b64urlDecode(str) {
  str = str.replace(/-/g,"+").replace(/_/g,"/");
  while (str.length % 4) str += "=";
  return decodeURIComponent(escape(atob(str)));
}
function setCookie(name, value, days=365) {
  const exp = new Date(Date.now() + days*864e5).toUTCString();
  document.cookie = `${name}=${value}; Expires=${exp}; Path=/; SameSite=Lax`;
}
function getCookie(name) {
  return document.cookie.split("; ").find(r => r.startsWith(name + "="))?.split("=").slice(1).join("=") || null;
}

// ─── Preferences ───
const DEFAULT_PREFS = {
  v: 1,
  provider: "wikioracle",
  model: "nanochat-default",
  temp: 0.7,
  username: "User",
  tools: { rag: true, url_fetch: false },
  truth: { max_entries: 8, min_certainty: 0.2 },
  message_window: 40,
  layout: "horizontal",
};

function loadPrefs() {
  const raw = getCookie("wo_prefs");
  if (!raw) return { ...DEFAULT_PREFS };
  try { return { ...DEFAULT_PREFS, ...JSON.parse(b64urlDecode(raw)) }; }
  catch { return { ...DEFAULT_PREFS }; }
}

function savePrefs(obj) {
  setCookie("wo_prefs", b64urlEncode(JSON.stringify(obj)));
}

let prefs = loadPrefs();

function applyLayout(layout) {
  const tree = document.getElementById("treeContainer");
  if (layout === "vertical") {
    document.body.classList.add("layout-vertical");
    // Reset height, use width for vertical
    tree.style.height = "";
    if (!tree.style.width) tree.style.width = "280px";
  } else {
    document.body.classList.remove("layout-vertical");
    // Reset width, use height for horizontal
    tree.style.width = "";
    if (!tree.style.height) tree.style.height = "220px";
  }
  if (typeof renderMessages === "function") renderMessages();
}

// ─── Token (stored in localStorage, not cookie) ───
function getToken() { return localStorage.getItem("wo_token") || ""; }
function setToken(t) { localStorage.setItem("wo_token", t); }

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

// ─── API helpers ───
async function api(method, path, body) {
  const token = getToken();
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = "Bearer " + token;
  const opts = { method, headers };
  if (body) opts.body = JSON.stringify(body);
  const resp = await fetch(path, opts);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`HTTP ${resp.status}: ${text.slice(0, 200)}`);
  }
  return resp.json();
}

// ─── Conversation tree helpers ───

function findConversation(conversations, convId) {
  for (const conv of conversations) {
    if (conv.id === convId) return conv;
    const found = findConversation(conv.children || [], convId);
    if (found) return found;
  }
  return null;
}

function tempId(prefix) {
  prefix = prefix || "m_";
  return prefix + Array.from(crypto.getRandomValues(new Uint8Array(8)))
    .map(b => b.toString(16).padStart(2, "0")).join("");
}

// ─── Tree navigation ───

function navigateToNode(nodeId) {
  if (!state) return;
  selectedConvId = nodeId;
  _pendingBranchParent = null; // cancel any pending branch
  state.selected_conversation = nodeId;
  renderMessages();
  // Persist selected_conversation to server
  api("POST", "/state", state).catch(e => setStatus("Error: " + e.message));
  // Save to cookie for session restore
  _saveSelectedToCookie();
}

function branchFromNode(convId) {
  // Double-click a node → show empty chat, pending branch parent set
  if (!state || !convId) return;
  _pendingBranchParent = convId;
  selectedConvId = null; // show empty chat
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

  // Count messages in this conversation and all descendants
  function countMsgs(c) {
    let n = (c.messages || []).length;
    for (const child of (c.children || [])) n += countMsgs(child);
    return n;
  }
  const count = countMsgs(conv);
  if (!confirm(`Delete "${conv.title}" and all its branches? (${count} message${count !== 1 ? "s" : ""})`)) return;

  // Remove from tree
  function removeFromList(list, id) {
    for (let i = 0; i < list.length; i++) {
      if (list[i].id === id) { list.splice(i, 1); return true; }
      if (removeFromList(list[i].children || [], id)) return true;
    }
    return false;
  }
  removeFromList(state.conversations, convId);
  selectedConvId = null;
  state.selected_conversation = null;
  renderMessages();
  api("POST", "/state", state).catch(e => setStatus("Error: " + e.message));
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
  function removeFromList(list, id) {
    for (let i = 0; i < list.length; i++) {
      if (list[i].id === id) { list.splice(i, 1); return true; }
      if (removeFromList(list[i].children || [], id)) return true;
    }
    return false;
  }
  removeFromList(state.conversations, sourceId);

  // If we were viewing the source, switch to target
  if (selectedConvId === sourceId) {
    selectedConvId = targetId;
    state.selected_conversation = targetId;
  }

  renderMessages();
  api("POST", "/state", state).catch(e => setStatus("Error: " + e.message));
  setStatus(`Merged "${source.title}" into "${target.title}" (${target.messages.length} messages)`);
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

  // Move up
  if (msgIdx > 0) {
    const item = document.createElement("div");
    item.className = "ctx-item";
    item.textContent = "Move up";
    item.addEventListener("click", (e) => { e.stopPropagation(); _hideMsgContextMenu(); _moveMessage(msgIdx, msgIdx - 1); });
    menu.appendChild(item);
  }

  // Move down
  if (msgIdx < totalMsgs - 1) {
    const item = document.createElement("div");
    item.className = "ctx-item";
    item.textContent = "Move down";
    item.addEventListener("click", (e) => { e.stopPropagation(); _hideMsgContextMenu(); _moveMessage(msgIdx, msgIdx + 1); });
    menu.appendChild(item);
  }

  // Separator
  if (msgIdx > 0 || msgIdx < totalMsgs - 1) {
    const sep = document.createElement("div");
    sep.className = "ctx-sep";
    menu.appendChild(sep);
  }

  // Delete
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
  api("POST", "/state", state).catch(e => setStatus("Error: " + e.message));
}

function _deleteMessage(msgIdx) {
  if (!state || !selectedConvId) return;
  const conv = findConversation(state.conversations, selectedConvId);
  if (!conv || !conv.messages) return;
  const msg = conv.messages[msgIdx];
  if (!msg) return;
  const preview = (msg.content || "").replace(/<[^>]+>/g, "").slice(0, 60);
  if (!confirm(`Delete this message?\n"${preview}"`)) return;
  conv.messages.splice(msgIdx, 1);
  // If conversation is now empty, remove it too
  if (conv.messages.length === 0 && (!conv.children || conv.children.length === 0)) {
    function removeFromList(list, id) {
      for (let i = 0; i < list.length; i++) {
        if (list[i].id === id) { list.splice(i, 1); return true; }
        if (removeFromList(list[i].children || [], id)) return true;
      }
      return false;
    }
    removeFromList(state.conversations, selectedConvId);
    selectedConvId = null;
    state.selected_conversation = null;
  }
  renderMessages();
  api("POST", "/state", state).catch(e => setStatus("Error: " + e.message));
}

// ─── Cookie for selected conversation ───
function _saveSelectedToCookie() {
  setCookie("wo_selected", selectedConvId || "");
}

function _loadSelectedFromCookie() {
  const val = getCookie("wo_selected");
  if (!val) return null;
  return val;
}

// ─── UI rendering ───
function renderMessages() {
  const wrapper = document.getElementById("chatWrapper");
  wrapper.innerHTML = "";

  if (!state) state = {};
  if (!Array.isArray(state.conversations)) state.conversations = [];

  const treeCallbacks = { onNavigate: navigateToNode, onBranch: branchFromNode, onDelete: deleteConversation, onMerge: mergeConversation };

  // Determine which messages to show
  let visible = [];
  if (selectedConvId !== null) {
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
    const ts = msg.timestamp ? new Date(msg.timestamp).toLocaleString() : "";
    meta.textContent = `${msg.username || ""} · ${ts}`;

    const bubble = document.createElement("div");
    bubble.className = "msg-bubble";
    bubble.innerHTML = msg.content || "";

    div.appendChild(meta);
    div.appendChild(bubble);

    // Drag-to-reorder messages
    div.draggable = true;
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
    timestamp: now,
    content: `<p>${text.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}</p>`,
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
        ...prefs,
        temp: prefs.temp,
        provider: prefs.provider,
        model: prefs.model,
        username: prefs.username,
        tools: prefs.tools,
        message_window: prefs.message_window,
      },
    });
    state = data.state || state;
    if (!Array.isArray(state.conversations)) state.conversations = [];

    // Server sets selected_conversation; use it
    if (state.selected_conversation) {
      selectedConvId = state.selected_conversation;
    }

    renderMessages();
    _saveSelectedToCookie();
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
  document.getElementById("setToken").value = getToken();
  document.getElementById("setUsername").value = prefs.username || "User";
  document.getElementById("setProvider").value = prefs.provider || "wikioracle";
  document.getElementById("setModel").value = prefs.model || "nanochat-default";
  document.getElementById("setTemp").value = prefs.temp || 0.7;
  document.getElementById("tempVal").textContent = prefs.temp || 0.7;
  document.getElementById("setRag").checked = prefs.tools?.rag !== false;
  document.getElementById("setUrlFetch").checked = prefs.tools?.url_fetch === true;
  document.getElementById("setWindow").value = prefs.message_window || 40;
  document.getElementById("windowVal").textContent = prefs.message_window || 40;
  document.getElementById("setLayout").value = prefs.layout || "horizontal";
  document.getElementById("setContext").value = state?.context || "";
  document.getElementById("settingsOverlay").classList.add("active");
}
function closeSettings() {
  document.getElementById("settingsOverlay").classList.remove("active");
}
function saveSettings() {
  const token = document.getElementById("setToken").value.trim();
  if (token) setToken(token);
  prefs.username = document.getElementById("setUsername").value.trim() || "User";
  prefs.provider = document.getElementById("setProvider").value;
  prefs.model = document.getElementById("setModel").value.trim();
  prefs.temp = parseFloat(document.getElementById("setTemp").value);
  prefs.tools = {
    rag: document.getElementById("setRag").checked,
    url_fetch: document.getElementById("setUrlFetch").checked,
  };
  prefs.message_window = parseInt(document.getElementById("setWindow").value);
  prefs.layout = document.getElementById("setLayout").value;

  const newContext = document.getElementById("setContext").value.trim();
  if (state && newContext !== state.context) {
    state.context = newContext;
    api("POST", "/state", state).catch(e => setStatus("Error saving context: " + e.message));
  }

  savePrefs(prefs);
  applyLayout(prefs.layout);
  closeSettings();
  setStatus("Settings saved");
}

// ─── Bind UI events ───
function bindEvents() {
  document.getElementById("setTemp").addEventListener("input", function() {
    document.getElementById("tempVal").textContent = this.value;
  });
  document.getElementById("setWindow").addEventListener("input", function() {
    document.getElementById("windowVal").textContent = this.value;
  });

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
  document.getElementById("settingsOverlay").addEventListener("click", function(e) {
    // Close settings when clicking the background overlay (not the panel itself)
    if (e.target === this) closeSettings();
  });

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

// ─── Init: load state from server ───
async function init() {
  try {
    setStatus("Loading state...");
    try {
      const provData = await api("GET", "/providers");
      const sel = document.getElementById("setProvider");
      sel.innerHTML = "";
      for (const [key, info] of Object.entries(provData.providers)) {
        const opt = document.createElement("option");
        opt.value = key;
        opt.textContent = info.name + (info.model ? ` (${info.model})` : "");
        sel.appendChild(opt);
      }
    } catch {}

    const data = await api("GET", "/state");
    state = data.state || {};
    if (!Array.isArray(state.conversations)) state.conversations = [];

    // Restore selected conversation from cookie, then from server state
    const cookieSelected = _loadSelectedFromCookie();
    if (cookieSelected && findConversation(state.conversations, cookieSelected)) {
      selectedConvId = cookieSelected;
    } else if (state.selected_conversation && findConversation(state.conversations, state.selected_conversation)) {
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
applyLayout(prefs.layout);
init();
