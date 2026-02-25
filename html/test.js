#!/usr/bin/env node

/**
 * WikiOracle Client-Side Test & Visualization Toolkit
 *
 * Consolidates four standalone scripts into one CLI:
 *   render    - Mock-render HTML output for the chat view
 *   convos    - Show conversation grouping (D3 tree nodes)
 *   simulate  - Full client-side rendering simulation
 *   structure - Message tree with branching visualization
 *
 * Usage:
 *   node test.js <command> [path/to/llm.jsonl]
 *   node test.js --help
 */

const fs = require('fs');
const path = require('path');

// ═══ Shared Utilities ═══════════════════════════════════════════════════════

function parseJsonl(filePath) {
  const content = fs.readFileSync(filePath, 'utf-8');
  const lines = content.trim().split('\n').filter(l => l.trim());
  if (lines.length === 0) throw new Error('Empty JSONL file');

  const header = JSON.parse(lines[0]);
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
  return { header, messages, trust };
}

function buildMessageGraph(messages) {
  const byId = {}, children = {}, rootIds = [];
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

function resolveCWD(messages, activePath) {
  if (!messages || !messages.length) return [];
  const graph = buildMessageGraph(messages);
  const allIds = new Set(Object.keys(graph.byId));
  if (activePath && activePath.length && activePath.every(id => allIds.has(id))) {
    return activePath;
  }
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

function groupConversations(graph, activePath) {
  const activeSet = new Set(activePath || []);

  function walkChain(startId) {
    const msgs = [];
    let cur = startId;
    while (cur) {
      const msg = graph.byId[cur];
      if (!msg) break;
      msgs.push(msg);
      const kids = graph.children[cur] || [];
      if (kids.length === 1) {
        cur = kids[0];
      } else {
        break;
      }
    }
    return msgs;
  }

  function buildConvNode(startId) {
    const msgs = walkChain(startId);
    if (!msgs.length) return null;

    const lastMsg = msgs[msgs.length - 1];
    const lastId = lastMsg.id;
    const kids = graph.children[lastId] || [];
    const isActive = msgs.some(m => activeSet.has(m.id));

    const firstUser = msgs.find(m => !isAssistant(m));
    const title = firstUser
      ? (firstUser.title || "").replace(/^User:\s*/, "").slice(0, 50)
      : (msgs[0].title || "").slice(0, 50);
    const qCount = msgs.filter(m => !isAssistant(m)).length;
    const childNodes = kids.map(buildConvNode).filter(Boolean);

    return {
      id: msgs[0].id,
      lastId: lastId,
      title: title || "(untitled)",
      messageCount: msgs.length,
      questionCount: qCount,
      messages: msgs,
      active: isActive,
      children: childNodes.length > 0 ? childNodes : undefined,
    };
  }

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

function isAssistant(msg) {
  return /llm|oracle|nanochat|claude|gpt|anthropic/i.test(msg.username || "");
}

function stripHtml(html) {
  return (html || "").replace(/<[^>]+>/g, "").trim();
}

// ═══ Command: render ═════════════════════════════════════════════════════════

function cmdRender(filePath) {
  const { header, messages } = parseJsonl(filePath);
  const graph = buildMessageGraph(messages);
  const cwd = resolveCWD(messages, header.active_path || []);
  const visible = cwd.map(id => graph.byId[id]).filter(Boolean);

  console.log('Mock Render: HTML Output for Chat View');
  console.log(''.padEnd(60, '=') + '\n');

  console.log(`<!-- active_path: ${header.active_path ? JSON.stringify(header.active_path) : '[] (default)'} -->`);
  console.log(`<!-- cwd.length: ${cwd.length} -->`);
  console.log(`<!-- visible messages: ${visible.length} -->\n`);

  console.log('<div id="chatWrapper" class="chat-wrapper">\n');

  for (let i = 0; i < visible.length; i++) {
    const msg = visible[i];
    const role = isAssistant(msg) ? 'assistant' : 'user';
    const ts = msg.timestamp ? new Date(msg.timestamp).toLocaleString() : 'N/A';

    console.log(`  <div class="message ${role}" data-id="${msg.id}">`);
    console.log(`    <div class="msg-meta">`);
    console.log(`      ${msg.username || 'Unknown'} \u00b7 ${ts}`);
    console.log(`    </div>`);
    console.log(`    <div class="msg-bubble">`);
    console.log(`      ${msg.content}`);
    console.log(`    </div>`);
    console.log(`  </div>`);
    if (i < visible.length - 1) console.log('');
  }

  console.log('\n</div> <!-- /chatWrapper -->\n');

  console.log(''.padEnd(60, '='));
  console.log('\nRENDERED TEXT (for readability):\n');

  for (const msg of visible) {
    const role = isAssistant(msg) ? '[ASSISTANT]' : '[USER]';
    const ts = msg.timestamp ? new Date(msg.timestamp).toLocaleString() : 'N/A';
    console.log(`${role} ${msg.username}`);
    console.log(`${ts}`);
    console.log(`${stripHtml(msg.content || "")}`);
    console.log('');
  }
}

// ═══ Command: convos ═════════════════════════════════════════════════════════

function cmdConvos(filePath) {
  const { header, messages } = parseJsonl(filePath);
  const graph = buildMessageGraph(messages);
  const cwd = resolveCWD(messages, header.active_path || []);
  const convTree = groupConversations(graph, cwd);

  console.log('Conversation Grouping (D3 Tree Nodes)');
  console.log(''.padEnd(60, '=') + '\n');

  let convIndex = 0;

  function printConv(node, depth) {
    if (node.id === 'root') {
      console.log('ROOT TREE');
      console.log('  Active: ' + (node.active ? 'YES (empty path)' : 'NO'));
      console.log('  Children: ' + (node.children ? node.children.length : 0) + ' conversation segment(s)\n');
      if (node.children) {
        for (const child of node.children) printConv(child, depth + 1);
      }
    } else {
      convIndex++;
      const indent = '  '.repeat(depth);
      console.log(`${indent}CONVERSATION ${convIndex}:`);
      console.log(`${indent}  Title: "${node.title}"`);
      console.log(`${indent}  ID: ${node.id}`);
      console.log(`${indent}  Active: ${node.active ? 'YES (on render path)' : 'NO'}`);
      console.log(`${indent}  Messages: ${node.messageCount}`);
      console.log(`${indent}  Questions/Answers: ${node.questionCount} Q/A pair(s)`);
      console.log(`${indent}  Message Chain:`);

      for (let i = 0; i < node.messages.length; i++) {
        const msg = node.messages[i];
        const role = isAssistant(msg) ? 'A' : 'U';
        const content = stripHtml(msg.content || "").slice(0, 55);
        console.log(`${indent}    [${i + 1}] ${role} ${msg.username || 'Unknown'}`);
        console.log(`${indent}        "${content}${content.length >= 55 ? '...' : ''}"`);
        console.log(`${indent}        (${msg.id.slice(0, 12)}...)`);
      }

      if (node.children && node.children.length > 0) {
        console.log(`${indent}  Child Conversations: ${node.children.length}\n`);
        for (const child of node.children) printConv(child, depth + 1);
      } else {
        console.log(`${indent}  Child Conversations: none (leaf)\n`);
      }
    }
  }

  printConv(convTree, 0);

  console.log('\n'.padEnd(60, '='));
  console.log('\nSUMMARY:');
  console.log(`  Input: ${messages.length} messages in ${graph.rootIds.length} conversation(s)`);
  console.log(`  Default path: ${cwd.length} messages`);
  console.log(`  Tree: ${convTree.children ? convTree.children.length : 0} top-level conversation segment(s)`);
}

// ═══ Command: simulate ═══════════════════════════════════════════════════════

function cmdSimulate(filePath) {
  console.log('Client-Side Rendering Simulator');
  console.log(''.padEnd(60, '=') + '\n');

  // 1) Parse
  console.log('1. PARSING llm.jsonl...\n');
  const data = parseJsonl(filePath);

  console.log(`   Header version:  ${data.header.version}`);
  console.log(`   Schema:          ${data.header.schema}`);
  console.log(`   Date:            ${data.header.date}`);
  console.log(`   Messages:        ${data.messages.length}`);
  console.log(`   Trust entries:   ${data.trust.length}`);
  console.log(`   Active path:     ${data.header.active_path ? JSON.stringify(data.header.active_path) : '(not set, will use default)'}\n`);

  // 2) Build graph
  console.log('2. BUILDING MESSAGE GRAPH...\n');
  const graph = buildMessageGraph(data.messages);

  console.log(`   Total messages:  ${Object.keys(graph.byId).length}`);
  console.log(`   Root messages:   ${graph.rootIds.length}`);
  console.log(`   Root IDs:        [${graph.rootIds.slice(0, 3).join(', ')}${graph.rootIds.length > 3 ? ', ...' : ''}]`);

  let branchPoints = 0, leafNodes = 0;
  for (const childList of Object.values(graph.children)) {
    if (childList.length > 1) branchPoints++;
  }
  for (const id of Object.keys(graph.byId)) {
    if (!graph.children[id] || graph.children[id].length === 0) leafNodes++;
  }
  console.log(`   Branch points:   ${branchPoints}`);
  console.log(`   Leaf nodes:      ${leafNodes}\n`);

  // 3) Resolve CWD
  console.log('3. RESOLVING DEFAULT PATH...\n');
  const activePath = data.header.active_path || [];
  const cwd = resolveCWD(data.messages, activePath);

  console.log(`   Resolved CWD length: ${cwd.length}`);
  console.log(`   CWD: [${cwd.slice(0, 5).map(id => id.slice(0, 12)).join(', ')}${cwd.length > 5 ? ', ...' : ''}]\n`);

  // 4) Visible messages
  console.log('4. VISIBLE MESSAGES (what would render)...\n');
  const visible = cwd.length > 0
    ? cwd.map(id => graph.byId[id]).filter(Boolean)
    : data.messages;

  console.log(`   Total visible:   ${visible.length}\n`);

  for (let i = 0; i < visible.length; i++) {
    const msg = visible[i];
    const role = isAssistant(msg) ? 'ASSISTANT' : 'USER';
    const ts = msg.timestamp ? new Date(msg.timestamp).toLocaleString() : 'N/A';
    const content = stripHtml(msg.content || "").slice(0, 70);

    console.log(`   [${i + 1}] ${role.padEnd(10)} | ${msg.username || 'Unknown'}`);
    console.log(`       ${ts}`);
    console.log(`       "${content}${content.length >= 70 ? '...' : ''}"`);
    if (msg.parent_id) console.log(`       parent: ${msg.parent_id.slice(0, 12)}...`);
    console.log('');
  }

  // 5) Conversation tree
  console.log('5. CONVERSATION TREE (groupConversations)...\n');
  const convTree = groupConversations(graph, cwd);

  function printTree(node, indent) {
    if (node.id === 'root') {
      console.log(`   ${indent}ROOT /`);
      console.log(`   ${indent}  active: ${node.active ? 'YES' : 'NO'}`);
      if (node.children) {
        for (let i = 0; i < node.children.length; i++) {
          printTree(node.children[i], indent + (i === node.children.length - 1 ? '  ' : '  \u2502 '));
        }
      }
    } else {
      console.log(`   ${indent}\u250c\u2500 [${node.questionCount} Q/A] "${node.title}"`);
      console.log(`   ${indent}\u2502  id: ${node.id.slice(0, 12)}...`);
      console.log(`   ${indent}\u2502  messages: ${node.messageCount}`);
      console.log(`   ${indent}\u2502  active: ${node.active ? 'YES' : 'NO'}`);
      if (node.children) {
        console.log(`   ${indent}\u2502  children:`);
        for (let i = 0; i < node.children.length; i++) {
          printTree(node.children[i], indent + (i === node.children.length - 1 ? '     ' : '  \u2502  '));
        }
      }
    }
  }

  printTree(convTree, '');

  // 6) Summary
  console.log('\n6. SUMMARY:\n');
  console.log(`   ${data.messages.length} messages in ${graph.rootIds.length} conversation(s)`);
  console.log(`   Default path: ${cwd.length} messages`);
  console.log(`   ${visible.length} messages would render`);
  console.log(`   ${convTree.children ? convTree.children.length : 0} top-level conversation segment(s)`);
}

// ═══ Command: structure ══════════════════════════════════════════════════════

function cmdStructure(filePath) {
  const { header, messages } = parseJsonl(filePath);
  const graph = buildMessageGraph(messages);
  const cwd = resolveCWD(messages, header.active_path || []);
  const cwdSet = new Set(cwd);

  console.log('Message Structure & Branching Visualization');
  console.log(''.padEnd(60, '=') + '\n');

  console.log('FULL CONVERSATION TREE (showing all branches):\n');

  function formatMsg(msg) {
    const role = isAssistant(msg) ? 'A' : 'U';
    return `${role} ${msg.username || 'Unknown'}: ${stripHtml(msg.content || "").slice(0, 35)}`;
  }

  function printNode(id, isLast, prefix) {
    const msg = graph.byId[id];
    if (!msg) return;

    const shortId = id.slice(0, 8);
    const marker = cwdSet.has(id) ? '\u25cf' : '\u25cb';
    const connector = isLast ? '\u2514\u2500' : '\u251c\u2500';

    console.log(`${prefix}${connector} ${marker} [${shortId}] ${formatMsg(msg)}`);

    const kids = graph.children[id] || [];
    const newPrefix = prefix + (isLast ? '   ' : '\u2502  ');
    for (let i = 0; i < kids.length; i++) {
      printNode(kids[i], i === kids.length - 1, newPrefix);
    }
  }

  for (const rootId of graph.rootIds) {
    printNode(rootId, true, '');
  }

  console.log('\nLEGEND:');
  console.log('  \u25cf = on default active path (will render)');
  console.log('  \u25cb = on alternate branch (hidden by default)');

  // Branch analysis
  console.log('\n\nBRANCH ANALYSIS:\n');

  let branchCount = 0;
  for (const [parentId, childList] of Object.entries(graph.children)) {
    if (childList.length > 1) {
      branchCount++;
      const parentMsg = graph.byId[parentId];
      console.log(`Branch #${branchCount}: After "${stripHtml(parentMsg.content || "").slice(0, 40)}..."`);
      console.log(`  Parent: [${parentId.slice(0, 8)}] ${parentMsg.username}`);
      console.log(`  ${childList.length} children:`);

      for (let i = 0; i < childList.length; i++) {
        const childMsg = graph.byId[childList[i]];
        const pathMark = cwdSet.has(childList[i]) ? ' [ON MAIN PATH]' : ' [ALTERNATE]';
        console.log(`    [${i + 1}] [${childList[i].slice(0, 8)}] ${childMsg.username}: "${stripHtml(childMsg.content || "").slice(0, 35)}..."${pathMark}`);
      }
      console.log('');
    }
  }

  if (branchCount === 0) console.log('No branches detected. This is a linear conversation.');

  // Path analysis
  console.log('\nPATH ANALYSIS:\n');
  console.log(`Active path from header: ${header.active_path ? JSON.stringify(header.active_path) : 'none (uses default)'}`);
  console.log(`Default path length: ${cwd.length} messages`);
  console.log(`Total messages: ${messages.length}`);
  console.log(`On alternate branches: ${messages.length - cwd.length}`);

  if (messages.length > cwd.length) {
    console.log('\nMessages NOT on default path:');
    for (const msg of messages.filter(m => !cwdSet.has(m.id))) {
      console.log(`  - [${msg.id.slice(0, 8)}] ${msg.username}: "${stripHtml(msg.content || "").slice(0, 35)}..."`);
    }
  }
}

// ═══ CLI ═════════════════════════════════════════════════════════════════════

const COMMANDS = {
  render:    { fn: cmdRender,    desc: 'Mock-render HTML output for the chat view' },
  convos:    { fn: cmdConvos,    desc: 'Show conversation grouping (D3 tree nodes)' },
  simulate:  { fn: cmdSimulate,  desc: 'Full client-side rendering simulation' },
  structure: { fn: cmdStructure, desc: 'Message tree with branching visualization' },
};

function usage() {
  console.log('Usage: node test.js <command> [path/to/llm.jsonl]\n');
  console.log('Commands:');
  for (const [name, { desc }] of Object.entries(COMMANDS)) {
    console.log(`  ${name.padEnd(12)} ${desc}`);
  }
  console.log('\nIf no file path is given, looks for ../llm.jsonl relative to this script.');
}

function main() {
  const args = process.argv.slice(2);

  if (args.length === 0 || args[0] === '--help' || args[0] === '-h') {
    usage();
    process.exit(0);
  }

  const cmd = args[0];
  if (!COMMANDS[cmd]) {
    console.error(`Unknown command: ${cmd}\n`);
    usage();
    process.exit(1);
  }

  const filePath = args[1] || path.resolve(__dirname, '..', 'llm.jsonl');

  if (!fs.existsSync(filePath)) {
    console.error(`File not found: ${filePath}`);
    process.exit(1);
  }

  COMMANDS[cmd].fn(filePath);
}

if (require.main === module) {
  try {
    main();
  } catch (err) {
    console.error('Error:', err.message);
    process.exit(1);
  }
}

module.exports = { parseJsonl, buildMessageGraph, resolveCWD, groupConversations, stripHtml, isAssistant };
