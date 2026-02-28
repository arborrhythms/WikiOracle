// query.js — Server communication layer for WikiOracle front-end.
// Loaded after util.js; depends on config global (config.js) for url_prefix.
//
// Exports: api, _apiPath, findConversation, findParentConversation,
//          _buildAncestorPath, _mergeResponseConversation,
//          _buildRuntimeConfig, _clientMerge

// ─── API helpers ───
function _apiPath(path) {
  return (config.server.url_prefix || "") + path;
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

// ─── Conversation tree helpers ───
function findConversation(conversations, convId) {
  return findInTree(conversations, convId);
}

// Return the parent conversation object of convId, or null if convId is a root.
function findParentConversation(conversations, convId) {
  if (!convId || !conversations) return null;
  for (var i = 0; i < conversations.length; i++) {
    var ch = conversations[i].children || [];
    for (var k = 0; k < ch.length; k++) {
      if (ch[k].id === convId) return conversations[i];
    }
    var deeper = findParentConversation(ch, convId);
    if (deeper) return deeper;
  }
  return null;
}

// Build a pruned conversation tree containing only the ancestor path to convId.
// Each node on the path keeps only the child that leads to the target.
// Returns a new array (does not mutate the original).
function _buildAncestorPath(conversations, convId) {
  if (!convId || !conversations) return [];
  function _search(convs, target) {
    for (var i = 0; i < convs.length; i++) {
      var c = convs[i];
      if (c.id === target) {
        // Found target — return it with its children intact (includes optimistic conv)
        return [{ id: c.id, title: c.title, messages: c.messages || [], children: c.children || [] }];
      }
      var deeper = _search(c.children || [], target);
      if (deeper) {
        // This node is on the path — keep only the child that leads to target
        return [{ id: c.id, title: c.title, messages: c.messages || [], children: deeper }];
      }
    }
    return null;
  }
  return _search(conversations, convId) || [];
}

// Merge a response-state's conversation tree back into the full local state.
// Finds the selected conversation in responseBundle and updates/inserts it in localConvs.
function _mergeResponseConversation(localConvs, responseBundle) {
  var selId = responseBundle.selected_conversation;
  if (!selId) return;
  // Find the conversation in the response
  var respConv = findInTree(responseBundle.conversations || [], selId);
  if (!respConv) return;
  // Try to find and update in the local tree
  var localConv = findInTree(localConvs, selId);
  if (localConv) {
    localConv.messages = respConv.messages || [];
    localConv.title = respConv.title || localConv.title;
    // Merge children (response may have added a new child)
    if (respConv.children) {
      if (!localConv.children) localConv.children = [];
      for (var i = 0; i < respConv.children.length; i++) {
        var rc = respConv.children[i];
        if (!findInTree(localConv.children, rc.id)) {
          localConv.children.push(rc);
        }
      }
    }
  } else {
    // New conversation — find its parent in the response path and insert there
    // Walk the response tree to find the parent
    function _findParent(convs, childId) {
      for (var j = 0; j < convs.length; j++) {
        var ch = convs[j].children || [];
        for (var k = 0; k < ch.length; k++) {
          if (ch[k].id === childId) return convs[j].id;
        }
        var deeper = _findParent(ch, childId);
        if (deeper) return deeper;
      }
      return null;
    }
    var parentId = _findParent(responseBundle.conversations || [], selId);
    if (parentId) {
      var localParent = findInTree(localConvs, parentId);
      if (localParent) {
        if (!localParent.children) localParent.children = [];
        localParent.children.push(respConv);
      } else {
        localConvs.push(respConv);
      }
    } else {
      localConvs.push(respConv);
    }
  }
}

// Build the runtime_config dict from the current config (stateless).
// This is the YAML-shaped config that the server needs for
// provider resolution, chat settings, and user display name.
function _buildRuntimeConfig() {
  return config || {};
}

// Client-side merge: fold importState data into the live `state` object.
// Merges truth entries (by id, import wins), conversations (appended),
// and context (kept from current state — import context is not overwritten).
function _clientMerge(importState) {
  // Truth entries: merge by id (import overwrites duplicates)
  if (!Array.isArray(state.truth)) state.truth = [];
  const incoming = Array.isArray(importState.truth) ? importState.truth : [];
  const byId = {};
  for (const e of state.truth) { if (e.id) byId[e.id] = e; }
  for (const e of incoming) {
    if (e.id && byId[e.id]) {
      // Replace existing entry
      const idx = state.truth.indexOf(byId[e.id]);
      if (idx >= 0) state.truth[idx] = e;
    } else {
      state.truth.push(e);
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

  // Title: import wins if current title is empty or default
  if (importState.title && (!state.title || state.title === "WikiOracle")) {
    state.title = importState.title;
  }
}
