#!/usr/bin/env node

/**
 * Enhanced WikiOracle Message Structure Visualizer
 * 
 * Shows:
 * - Full conversation tree with branching points
 * - Which messages appear on default path vs alternate branches
 * - Message relationships and parent-child chains
 */

const fs = require('fs');

function parseJsonl(filePath) {
  const content = fs.readFileSync(filePath, 'utf-8');
  const lines = content.trim().split('\n').filter(l => l.trim());
  if (lines.length === 0) throw new Error('Empty JSONL file');
  
  const header = JSON.parse(lines[0]);
  const messages = [];
  for (let i = 1; i < lines.length; i++) {
    const record = JSON.parse(lines[i]);
    if (record.type === 'message') {
      delete record.type;
      messages.push(record);
    }
  }
  return { header, messages };
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

function stripHtml(html) {
  return (html || "").replace(/<[^>]+>/g, "").trim();
}

function main() {
  const filePath = '/sessions/sharp-wonderful-volta/mnt/WikiOracle/llm.jsonl';
  const { header, messages } = parseJsonl(filePath);
  const graph = buildMessageGraph(messages);
  const cwd = resolveCWD(messages, header.active_path || []);
  const cwdSet = new Set(cwd);

  console.log('\n╔════════════════════════════════════════════════════════════════╗');
  console.log('║  WikiOracle Message Structure & Branching Visualization        ║');
  console.log('╚════════════════════════════════════════════════════════════════╝\n');

  // Build full tree visualization
  console.log('FULL CONVERSATION TREE (showing all branches):\n');

  function isUser(msg) {
    return !/llm|oracle|nanochat|claude|gpt|anthropic/i.test(msg.username || "");
  }

  function formatMsg(msg) {
    const role = isUser(msg) ? 'U' : 'A';
    const content = stripHtml(msg.content || "").slice(0, 35);
    return `${role} ${msg.username || 'Unknown'}: ${content}`;
  }

  function printNode(id, depth = 0, isLast = true, prefix = '') {
    const msg = graph.byId[id];
    if (!msg) return;

    const shortId = id.slice(0, 8);
    const onPath = cwdSet.has(id);
    const marker = onPath ? '●' : '○';
    const connector = isLast ? '└─' : '├─';
    const spacing = prefix + connector + ' ';
    
    console.log(`${spacing}${marker} [${shortId}] ${formatMsg(msg)}`);
    
    const kids = graph.children[id] || [];
    const newPrefix = prefix + (isLast ? '   ' : '│  ');
    
    for (let i = 0; i < kids.length; i++) {
      printNode(kids[i], depth + 1, i === kids.length - 1, newPrefix);
    }
  }

  for (const rootId of graph.rootIds) {
    printNode(rootId);
  }

  console.log('\nLEGEND:');
  console.log('  ● = message on default active path (will render)');
  console.log('  ○ = message on alternate branch (hidden by default)');

  // Branch points analysis
  console.log('\n\nBRANCH ANALYSIS:\n');
  
  let branchCount = 0;
  for (const [parentId, childList] of Object.entries(graph.children)) {
    if (childList.length > 1) {
      branchCount++;
      const parentMsg = graph.byId[parentId];
      console.log(`Branch #${branchCount}: After message "${stripHtml(parentMsg.content || "").slice(0, 40)}..."`);
      console.log(`  Parent: [${parentId.slice(0, 8)}] ${parentMsg.username}`);
      console.log(`  ${childList.length} children:`);
      
      for (let i = 0; i < childList.length; i++) {
        const childId = childList[i];
        const childMsg = graph.byId[childId];
        const isOnPath = cwdSet.has(childId);
        const pathMark = isOnPath ? ' [ON MAIN PATH]' : ' [ALTERNATE]';
        console.log(`    [${i+1}] [${childId.slice(0, 8)}] ${childMsg.username}: "${stripHtml(childMsg.content || "").slice(0, 35)}..."${pathMark}`);
      }
      console.log('');
    }
  }

  if (branchCount === 0) {
    console.log('No branches detected. This is a linear conversation.');
  }

  // Path analysis
  console.log('\nPATH ANALYSIS:\n');
  console.log(`Active path from header: ${header.active_path ? JSON.stringify(header.active_path) : 'none (uses default)'}`);
  console.log(`Default path length: ${cwd.length} messages`);
  console.log(`Total messages: ${messages.length}`);
  console.log(`Messages on alternate branches: ${messages.length - cwd.length}`);

  if (messages.length > cwd.length) {
    console.log('\nMessages NOT on default path (alternate branches):');
    const altMessages = messages.filter(m => !cwdSet.has(m.id));
    for (const msg of altMessages) {
      console.log(`  - [${msg.id.slice(0, 8)}] ${msg.username}: "${stripHtml(msg.content || "").slice(0, 35)}..."`);
    }
  }

  // Render output simulation
  console.log('\n\nRENDER SIMULATION:\n');
  console.log('If user opens this file in browser with active_path=[], these messages render:\n');
  
  for (let i = 0; i < cwd.length; i++) {
    const id = cwd[i];
    const msg = graph.byId[id];
    const isUserMsg = isUser(msg);
    const alignment = isUserMsg ? 'RIGHT' : 'LEFT';
    const bgClass = isUserMsg ? 'user-bubble' : 'assistant-bubble';
    
    console.log(`[${i+1}] <div class="message ${bgClass}" style="text-align: ${alignment}">`);
    console.log(`    <div class="username">${msg.username}</div>`);
    console.log(`    <div class="content">${stripHtml(msg.content || "").slice(0, 60)}</div>`);
    console.log(`    </div>`);
  }

  console.log('\n════════════════════════════════════════════════════════════════\n');
}

if (require.main === module) {
  try {
    main();
  } catch (err) {
    console.error('Error:', err.message);
    process.exit(1);
  }
}
