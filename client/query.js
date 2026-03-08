// query.js — Server communication layer for WikiOracle front-end.
// Loaded after util.js and graph.js; depends on config global (config.js) for url_prefix.
//
// Exports: api, _apiPath, _mergeResponseConversation,
//          _buildRuntimeConfig, _clientMerge

// ─── API helpers ───
function _apiPath(path) {
  return (config.server.url_prefix || "") + path;
}

async function api(method, path, body) {
  const headers = { "Content-Type": "application/json", "X-Requested-With": "WikiOracle" };
  var token = sessionStorage.getItem("wo_api_token") || localStorage.getItem("wo_api_token");
  if (token) headers["Authorization"] = "Bearer " + token;
  const opts = { method, headers };
  if (body) opts.body = JSON.stringify(body);
  var resp = await fetch(_apiPath(path), opts);
  if (resp.status === 401) {
    token = prompt("API token required:");
    if (token) {
      sessionStorage.setItem("wo_api_token", token);
      localStorage.setItem("wo_api_token", token);
      headers["Authorization"] = "Bearer " + token;
      resp = await fetch(_apiPath(path), opts);
    }
  }
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`HTTP ${resp.status}: ${text.slice(0, 200)}`);
  }
  return resp.json();
}

// ─── Conversation tree helpers (moved to graph.js) ───

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
    if (respConv.parentId !== undefined) localConv.parentId = respConv.parentId;
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
    // New conversation — use parentId for correct placement
    var pid = respConv.parentId || null;
    // Fallback: walk the response tree for backward compat with old servers
    if (!pid) {
      pid = (function _findParent(convs, childId) {
        for (var j = 0; j < convs.length; j++) {
          var ch = convs[j].children || [];
          for (var k = 0; k < ch.length; k++) {
            if (ch[k].id === childId) return convs[j].id;
          }
          var deeper = _findParent(ch, childId);
          if (deeper) return deeper;
        }
        return null;
      })(responseBundle.conversations || [], selId);
    }
    if (Array.isArray(pid)) {
      var attached = false;
      for (var p = 0; p < pid.length; p++) {
        var localParentMulti = findInTree(localConvs, pid[p]);
        if (!localParentMulti) continue;
        if (!localParentMulti.children) localParentMulti.children = [];
        if (!findInTree(localParentMulti.children, respConv.id)) {
          localParentMulti.children.push(respConv);
        }
        attached = true;
      }
      if (!attached) {
        localConvs.push(respConv);
      }
    } else if (pid) {
      var localParent = findInTree(localConvs, pid);
      if (localParent) {
        if (!localParent.children) localParent.children = [];
        if (!findInTree(localParent.children, respConv.id)) {
          localParent.children.push(respConv);
        }
      } else {
        localConvs.push(respConv);
      }
    } else {
      localConvs.push(respConv);
    }
  }
}

// Build the runtime_config dict from the current config (stateless).
// This is the config that the server needs for
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

  mergeConversationTrees(state.conversations, importConvs);

  // Context: keep current state context (don't overwrite)

  // Title: import wins if current title is empty or default
  if (importState.title && (!state.title || state.title === "WikiOracle")) {
    state.title = importState.title;
  }
}
