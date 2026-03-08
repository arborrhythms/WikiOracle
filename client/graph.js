// graph.js — Pure node/edge algorithms for conversation trees and DAGs.
//
// Nodes are plain objects with { id, children, messages, selected, parentId }.
// Edges are implicit: children arrays define parent→child, parentId stores
// the reverse link (a string or an array of strings for diamond merges).
//
// All functions are stateless — they take a conversation array (the forest)
// and any required context as arguments.  No globals are read or written.

"use strict";

// ─── Node lookup ───

function findInTree(nodes, id) {
  for (var i = 0; i < nodes.length; i++) {
    if (nodes[i].id === id) return nodes[i];
    var found = findInTree(nodes[i].children || [], id);
    if (found) return found;
  }
  return null;
}

function findConversation(conversations, convId) {
  return findInTree(conversations, convId);
}

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

// ─── Tree mutation ───

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

// ─── Path resolution ───

// Resolve a treePath (array of IDs) to the node it points to.
// Returns null if the path is empty (virtual root) or invalid.
function findNodeByPath(convs, path) {
  var nodes = convs;
  var node = null;
  for (var i = 0; i < path.length; i++) {
    var found = false;
    for (var j = 0; j < nodes.length; j++) {
      if (nodes[j].id === path[i]) {
        node = nodes[j];
        nodes = node.children || [];
        found = true;
        break;
      }
    }
    if (!found) return null;
  }
  return node;
}

// Build the path from root to targetId by DFS.  Returns [rootId, ..., targetId]
// or [] if targetId is null (root view).  For diamond nodes that appear under
// multiple parents, returns the first path found.
function buildTreePath(convs, targetId) {
  if (!targetId) return [];
  function _search(nodes, trail) {
    for (var i = 0; i < nodes.length; i++) {
      var cur = nodes[i];
      var next = trail.concat([cur.id]);
      if (cur.id === targetId) return next;
      var deeper = _search(cur.children || [], next);
      if (deeper) return deeper;
    }
    return null;
  }
  return _search(convs, []) || [];
}

// Build an ordered ancestor path (root → ... → target) for the given convId.
// Returns array of conversation *objects* (not IDs), or null if not found.
function getAncestorPath(conversations, convId) {
  if (!convId) return null;
  function _search(convs, target) {
    for (var i = 0; i < convs.length; i++) {
      if (convs[i].id === target) return [convs[i]];
      var deeper = _search(convs[i].children || [], target);
      if (deeper) { deeper.unshift(convs[i]); return deeper; }
    }
    return null;
  }
  return _search(conversations, convId);
}

// ─── Selection ───

// Walk the tree following `.selected` flags to find the deepest selected path.
function getSelectedConversationPath(conversations) {
  var best = null;
  function _walk(convs, path) {
    for (var i = 0; i < convs.length; i++) {
      var conv = convs[i];
      var next = path.concat([conv]);
      if (conv.selected) {
        best = next;
        _walk(conv.children || [], next);
      } else {
        _walk(conv.children || [], path);
      }
    }
  }
  _walk(conversations || [], []);
  return best || [];
}

// Return the terminal conversation ID from the deepest selected path, or null.
function selectedConversationIdFromFlags(conversations) {
  var path = getSelectedConversationPath(conversations);
  return path.length ? path[path.length - 1].id : null;
}

// Set `.selected = true` on every node in the path from root to selectedId.
// Clears all existing `.selected` flags first.
//
// When `explicitPath` (array of IDs) is provided and valid, walks those IDs
// instead of using DFS — this is essential for diamond/DAG nodes where the
// same node appears under multiple parents and DFS always finds the first.
function syncConversationSelection(conversations, selectedId, explicitPath) {
  function _clear(convs) {
    for (var i = 0; i < convs.length; i++) {
      delete convs[i].selected;
      _clear(convs[i].children || []);
    }
  }

  _clear(conversations || []);
  if (!selectedId) return [];

  // If an explicit path of IDs is provided, walk those IDs
  if (explicitPath && explicitPath.length > 0) {
    var result = [];
    var nodes = conversations || [];
    for (var i = 0; i < explicitPath.length; i++) {
      for (var j = 0; j < nodes.length; j++) {
        if (nodes[j].id === explicitPath[i]) {
          nodes[j].selected = true;
          result.push(nodes[j]);
          nodes = nodes[j].children || [];
          break;
        }
      }
    }
    if (result.length > 0 && result[result.length - 1].id === selectedId) {
      return result;
    }
    // explicitPath didn't resolve to selectedId — fall through to DFS
  }

  // Default: DFS to find first path
  var path = getAncestorPath(conversations || [], selectedId) || [];
  for (var i = 0; i < path.length; i++) {
    path[i].selected = true;
  }
  return path;
}

// ─── Tree projection ───

// Build a pruned conversation tree containing only the ancestor path to convId.
// Each node on the path keeps only the child that leads to the target;
// the target node itself retains all its children.
// Returns a new array (does not mutate the original).
function buildAncestorSubtree(conversations, convId) {
  if (!convId || !conversations) return [];
  function _copyMsg(m) {
    return {
      id: m.id,
      role: m.role,
      username: m.username,
      time: m.time,
      content: m.content,
      selected: !!m.selected,
      _pending: !!m._pending,
    };
  }
  function _search(convs, target) {
    for (var i = 0; i < convs.length; i++) {
      var c = convs[i];
      if (c.id === target) {
        return [{
          id: c.id, title: c.title,
          messages: (c.messages || []).map(_copyMsg),
          children: c.children || [],
          parentId: c.parentId, selected: !!c.selected,
        }];
      }
      var deeper = _search(c.children || [], target);
      if (deeper) {
        return [{
          id: c.id, title: c.title,
          messages: (c.messages || []).map(_copyMsg),
          children: deeper,
          parentId: c.parentId, selected: !!c.selected,
        }];
      }
    }
    return null;
  }
  return _search(conversations, convId) || [];
}

// ─── Tree aggregation ───

// Walk the conversation tree and return aggregate statistics.
// Returns { convCount, msgCount, qCount, rCount, earliest, latest }.
function computeTreeStats(conversations) {
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

// ─── Tree merge ───

// Recursively merge `incoming` conversation tree into `base` by ID.
// For duplicate IDs: incoming messages win (by message ID), title and parentId
// are updated from incoming, and children are merged recursively.
// New conversations (no matching ID in base) are appended.
// Mutates `base` in place.
function mergeConversationTrees(base, incoming) {
  var baseById = {};
  for (var i = 0; i < base.length; i++) {
    if (base[i].id) baseById[base[i].id] = base[i];
  }
  for (var k = 0; k < incoming.length; k++) {
    var inc = incoming[k];
    var existing = inc.id ? baseById[inc.id] : null;
    if (existing) {
      // Merge messages by id: incoming wins for duplicates, appends new
      var msgById = {};
      var eMsgs = existing.messages || [];
      for (var mi = 0; mi < eMsgs.length; mi++) {
        if (eMsgs[mi].id) msgById[eMsgs[mi].id] = eMsgs[mi];
      }
      var iMsgs = inc.messages || [];
      for (var mj = 0; mj < iMsgs.length; mj++) {
        if (iMsgs[mj].id && msgById[iMsgs[mj].id]) {
          var idx = eMsgs.indexOf(msgById[iMsgs[mj].id]);
          if (idx >= 0) eMsgs[idx] = iMsgs[mj];
        } else {
          eMsgs.push(iMsgs[mj]);
        }
      }
      // Update title and parentId if incoming has them
      if (inc.title) existing.title = inc.title;
      if (inc.parentId !== undefined) existing.parentId = inc.parentId;
      // Recursively merge children
      if (!existing.children) existing.children = [];
      mergeConversationTrees(existing.children, inc.children || []);
    } else {
      base.push(inc);
      if (inc.id) baseById[inc.id] = inc;
    }
  }
}

// ─── Preorder traversal (inorder reading traversal) ───
//
// Standard tree preorder: visit node, then recurse into children left-to-right.
// In a DAG (diamond), the same node appears under multiple parents and is
// visited once per parent — each parent's subtree is a complete reading path.

// Return the deepest last-descendant path from a given node+path.
function deepestLast(node, path) {
  while (node && node.children && node.children.length > 0) {
    var last = node.children[node.children.length - 1];
    path = path.concat([last.id]);
    node = last;
  }
  return path;
}

// Next node in preorder traversal from `treePath`.
// Returns the new path, or null if at the end.
function nextPreorder(convs, treePath) {
  if (treePath.length === 0) {
    if (convs.length > 0) return [convs[0].id];
    return null;
  }
  var cur = findNodeByPath(convs, treePath);
  if (cur && cur.children && cur.children.length > 0) {
    return treePath.concat([cur.children[0].id]);
  }
  for (var depth = treePath.length - 1; depth >= 0; depth--) {
    var parentPath = treePath.slice(0, depth);
    var parent = depth === 0
      ? { children: convs }
      : findNodeByPath(convs, parentPath);
    if (!parent || !parent.children) continue;
    var childId = treePath[depth];
    var siblings = parent.children;
    for (var si = 0; si < siblings.length; si++) {
      if (siblings[si].id === childId && si < siblings.length - 1) {
        return parentPath.concat([siblings[si + 1].id]);
      }
    }
  }
  return null;
}

// Previous node in preorder traversal from `treePath`.
// Returns the new path, or null if at the beginning.
function prevPreorder(convs, treePath) {
  if (treePath.length === 0) return null;
  var parentPath = treePath.slice(0, -1);
  var childId = treePath[treePath.length - 1];
  var parent = parentPath.length === 0
    ? { children: convs }
    : findNodeByPath(convs, parentPath);
  if (!parent || !parent.children) return parentPath.length > 0 ? parentPath : [];
  var siblings = parent.children;
  var idx = -1;
  for (var si = 0; si < siblings.length; si++) {
    if (siblings[si].id === childId) { idx = si; break; }
  }
  if (idx <= 0) {
    return parentPath; // [] = virtual root
  }
  var prevSib = siblings[idx - 1];
  return deepestLast(prevSib, parentPath.concat([prevSib.id]));
}
