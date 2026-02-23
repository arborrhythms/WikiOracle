#!/usr/bin/env node

/**
 * WikiOracle Client-Side Rendering Simulator
 * 
 * Reads llm.jsonl and simulates:
 * 1. JSONL parsing (header + message/trust records)
 * 2. buildMessageGraph() - construct tree structure
 * 3. resolveCWD() - resolve active_path to visible messages
 * 4. groupConversations() - collapse into conversation segments
 * 5. Show what messages would render
 */

const fs = require('fs');
const path = require('path');

// ─── JSONL Parsing ───
function parseJsonl(filePath) {
  const content = fs.readFileSync(filePath, 'utf-8');
  const lines = content.trim().split('\n').filter(l => l.trim());
  
  if (lines.length === 0) {
    throw new Error('Empty JSONL file');
  }

  const header = JSON.parse(lines[0]);
  if (header.type !== 'header') {
    throw new Error('First line must be a header record');
  }

  const messages = [];
  const trust = [];

  for (let i = 1; i < lines.length; i++) {
    const record = JSON.parse(lines[i]);
    if (record.type === 'message') {
      const msg = { ...record };
      delete msg.type;
      messages.push(msg);
    } else if (record.type === 'trust') {
      const t = { ...record };
      delete t.type;
      trust.push(t);
    }
  }

  return {
    header,
    messages,
    trust,
  };
}

// ─── buildMessageGraph (from wikioracle.js) ───
function buildMessageGraph(messages) {
  const byId = {}, children = {}, rootIds = [];
  
  // Sort by timestamp, then by ID for consistency
  const ordered = [...messages].sort((a, b) => {
    const ta = a.timestamp || "", tb = b.timestamp || "";
    return ta < tb ? -1 : ta > tb ? 1 : (a.id || "").localeCompare(b.id || "");
  });
  
  let prevId = null;
  for (const msg of ordered) {
    const mid = msg.id || "";
    byId[mid] = msg;
    
    let pid = msg.parent_id;
    if (pid === undefined) pid = prevId;
    
    if (pid === null || pid === undefined) {
      rootIds.push(mid);
    } else {
      if (!children[pid]) children[pid] = [];
      children[pid].push(mid);
    }
    prevId = mid;
  }
  
  return { byId, children, rootIds };
}

// ─── resolveCWD (from wikioracle.js) ───
function resolveCWD(messages, activePath) {
  if (!messages || !messages.length) return [];
  
  const graph = buildMessageGraph(messages);
  const allIds = new Set(Object.keys(graph.byId));
  
  // If activePath is provided and valid, use it
  if (activePath && activePath.length && activePath.every(id => allIds.has(id))) {
    return activePath;
  }
  
  // Otherwise, find the longest path (default path)
  function dfs(nid) {
    const kids = graph.children[nid] || [];
    if (!kids.length) return [nid];
    let best = [];
    for (const kid of kids) {
      const p = dfs(kid);
      if (p.length > best.length) best = p;
    }
    return [nid, ...best];
  }
  
  let longest = [];
  for (const rid of graph.rootIds) {
    const c = dfs(rid);
    if (c.length > longest.length) longest = c;
  }
  return longest;
}

// ─── groupConversations (from d3tree.js) ───
function groupConversations(graph, activePath) {
  const activeSet = new Set(activePath || []);

  // Walk a chain from startId, collecting messages until a branch or leaf
  function walkChain(startId) {
    const msgs = [];
    let cur = startId;
    while (cur) {
      const msg = graph.byId[cur];
      if (!msg) break;
      msgs.push(msg);
      const kids = graph.children[cur] || [];
      if (kids.length === 1) {
        cur = kids[0]; // continue chain
      } else {
        break; // branch point or leaf
      }
    }
    return msgs;
  }

  // Build a conversation node starting at startId
  function buildConvNode(startId) {
    const msgs = walkChain(startId);
    if (!msgs.length) return null;

    const lastMsg = msgs[msgs.length - 1];
    const lastId = lastMsg.id;
    const kids = graph.children[lastId] || [];
    const isActive = msgs.some(m => activeSet.has(m.id));

    // Build title: first user message content, truncated
    const firstUser = msgs.find(m => !/llm|oracle|nanochat|claude|gpt|anthropic/i.test(m.username || ""));
    const title = firstUser
      ? (firstUser.title || "").replace(/^User:\s*/, "").slice(0, 50)
      : (msgs[0].title || "").slice(0, 50);

    // Count Q/A pairs
    const qCount = msgs.filter(m => !/llm|oracle|nanochat|claude|gpt|anthropic/i.test(m.username || "")).length;

    const childNodes = kids.map(buildConvNode).filter(Boolean);

    return {
      id: msgs[0].id, // ID of first message in the segment
      lastId: lastId,
      title: title || "(untitled)",
      messageCount: msgs.length,
      questionCount: qCount,
      messages: msgs,
      active: isActive,
      children: childNodes.length > 0 ? childNodes : undefined,
    };
  }

  // Build root
  const rootChildren = graph.rootIds.map(buildConvNode).filter(Boolean);
  return {
    id: "root",
    title: "/",
    messageCount: 0,
    questionCount: 0,
    messages: [],
    active: activePath.length === 0,
    children: rootChildren.length > 0 ? rootChildren : undefined,
  };
}

// ─── Utility: Strip HTML tags ───
function stripHtml(html) {
  return (html || "").replace(/<[^>]+>/g, "").trim();
}

// ─── Main ───
function main() {
  const filePath = '/sessions/sharp-wonderful-volta/mnt/WikiOracle/llm.jsonl';
  
  console.log('╔════════════════════════════════════════════════════════════════╗');
  console.log('║  WikiOracle Client-Side Rendering Simulator                    ║');
  console.log('╚════════════════════════════════════════════════════════════════╝\n');
  
  // Parse JSONL
  console.log('1. PARSING llm.jsonl...\n');
  const data = parseJsonl(filePath);
  
  console.log(`   Header version:  ${data.header.version}`);
  console.log(`   Schema:          ${data.header.schema}`);
  console.log(`   Date:            ${data.header.date}`);
  console.log(`   Messages:        ${data.messages.length}`);
  console.log(`   Trust entries:   ${data.trust.length}`);
  if (data.header.active_path) {
    console.log(`   Active path:     ${JSON.stringify(data.header.active_path)}`);
  } else {
    console.log(`   Active path:     (not set, will use default)`);
  }
  console.log('');

  // Build graph
  console.log('2. BUILDING MESSAGE GRAPH...\n');
  const graph = buildMessageGraph(data.messages);
  
  console.log(`   Total messages:  ${Object.keys(graph.byId).length}`);
  console.log(`   Root messages:   ${graph.rootIds.length}`);
  console.log(`   Root IDs:        [${graph.rootIds.slice(0, 3).join(', ')}${graph.rootIds.length > 3 ? ', ...' : ''}]`);
  
  // Count branches
  let branchPoints = 0;
  let leafNodes = 0;
  for (const [parentId, childList] of Object.entries(graph.children)) {
    if (childList.length > 1) branchPoints++;
  }
  for (const id of Object.keys(graph.byId)) {
    if (!graph.children[id] || graph.children[id].length === 0) leafNodes++;
  }
  console.log(`   Branch points:   ${branchPoints}`);
  console.log(`   Leaf nodes:      ${leafNodes}`);
  console.log('');

  // Resolve CWD with empty active_path (default behavior)
  console.log('3. RESOLVING DEFAULT PATH (active_path = [])...\n');
  const activePath = data.header.active_path || [];
  const cwd = resolveCWD(data.messages, activePath);
  
  console.log(`   Resolved CWD length: ${cwd.length}`);
  console.log(`   CWD: [${cwd.slice(0, 5).map(id => id.slice(0, 12)).join(', ')}${cwd.length > 5 ? ', ...' : ''}]`);
  console.log('');

  // Visible messages
  console.log('4. VISIBLE MESSAGES (what would render)...\n');
  const visible = cwd.length > 0
    ? cwd.map(id => graph.byId[id]).filter(Boolean)
    : data.messages;
  
  console.log(`   Total visible:   ${visible.length}`);
  console.log('');
  
  for (let i = 0; i < visible.length; i++) {
    const msg = visible[i];
    const isAssistant = /llm|oracle|nanochat|claude|gpt|anthropic/i.test(msg.username || "");
    const role = isAssistant ? 'ASSISTANT' : 'USER';
    const ts = msg.timestamp ? new Date(msg.timestamp).toLocaleString() : 'N/A';
    const content = stripHtml(msg.content || "").slice(0, 70);
    const contentDisplay = content.length > 70 ? content + '...' : content;
    
    console.log(`   [${i+1}] ${role.padEnd(10)} | ${msg.username || 'Unknown'}`);
    console.log(`       ${ts}`);
    console.log(`       "${contentDisplay}"`);
    if (msg.parent_id) {
      console.log(`       parent: ${msg.parent_id.slice(0, 12)}...`);
    }
    console.log('');
  }

  // Group conversations
  console.log('5. CONVERSATION TREE (groupConversations)...\n');
  const convTree = groupConversations(graph, cwd);
  
  function printTree(node, indent = '') {
    if (node.id === 'root') {
      console.log(`   ${indent}ROOT /`);
      console.log(`   ${indent}  active: ${node.active ? 'YES' : 'NO'}`);
      if (node.children && node.children.length > 0) {
        for (let i = 0; i < node.children.length; i++) {
          const isLast = i === node.children.length - 1;
          printTree(node.children[i], indent + (isLast ? '  ' : '  │ '));
        }
      }
    } else {
      console.log(`   ${indent}┌─ [${node.questionCount} Q/A] "${node.title}"`);
      console.log(`   ${indent}│  id: ${node.id.slice(0, 12)}...`);
      console.log(`   ${indent}│  messages: ${node.messageCount}`);
      console.log(`   ${indent}│  active: ${node.active ? 'YES' : 'NO'}`);
      if (node.children && node.children.length > 0) {
        console.log(`   ${indent}│  children:`);
        for (let i = 0; i < node.children.length; i++) {
          const isLast = i === node.children.length - 1;
          printTree(node.children[i], indent + (isLast ? '     ' : '  │  '));
        }
      }
    }
  }
  
  printTree(convTree);
  console.log('');

  // Summary
  console.log('6. SUMMARY...\n');
  console.log(`   Input state has ${data.messages.length} messages in ${graph.rootIds.length} conversation(s)`);
  console.log(`   Default path (when active_path=[]) contains ${cwd.length} messages`);
  console.log(`   These ${visible.length} messages would be rendered in the chat view`);
  console.log(`   Conversation tree shows ${convTree.children ? convTree.children.length : 0} top-level conversation segment(s)`);
  console.log('');

  console.log('════════════════════════════════════════════════════════════════');
}

if (require.main === module) {
  try {
    main();
  } catch (err) {
    console.error('Error:', err.message);
    process.exit(1);
  }
}

module.exports = { buildMessageGraph, resolveCWD, groupConversations };
