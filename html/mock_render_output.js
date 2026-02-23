#!/usr/bin/env node

/**
 * MockRender: Show exactly what HTML would be rendered
 * 
 * Simulates the actual DOM rendering that happens in renderMessages()
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
  const visible = cwd.map(id => graph.byId[id]).filter(Boolean);

  console.log('╔════════════════════════════════════════════════════════════════╗');
  console.log('║  Mock Render: HTML Output for Chat View                        ║');
  console.log('╚════════════════════════════════════════════════════════════════╝\n');

  console.log('<!-- State -->\n');
  console.log(`<!-- active_path: ${header.active_path ? JSON.stringify(header.active_path) : '[] (default)'} -->`);
  console.log(`<!-- cwd.length: ${cwd.length} -->`);
  console.log(`<!-- visible messages: ${visible.length} -->\n`);

  console.log('<div id="chatWrapper" class="chat-wrapper">\n');

  for (let i = 0; i < visible.length; i++) {
    const msg = visible[i];
    const isAssistant = /llm|oracle|nanochat|claude|gpt|anthropic/i.test(msg.username || "");
    const role = isAssistant ? 'assistant' : 'user';
    const ts = msg.timestamp ? new Date(msg.timestamp).toLocaleString() : 'N/A';
    
    console.log(`  <div class="message ${role}" data-id="${msg.id}">`);
    console.log(`    <div class="msg-meta">`);
    console.log(`      ${msg.username || 'Unknown'} · ${ts}`);
    console.log(`    </div>`);
    console.log(`    <div class="msg-bubble">`);
    console.log(`      ${msg.content}`);
    console.log(`    </div>`);
    console.log(`  </div>`);
    if (i < visible.length - 1) console.log('');
  }

  console.log('\n</div> <!-- /chatWrapper -->\n');

  // Show rendered text for readability
  console.log('════════════════════════════════════════════════════════════════\n');
  console.log('RENDERED TEXT (for readability):\n');

  for (let i = 0; i < visible.length; i++) {
    const msg = visible[i];
    const isAssistant = /llm|oracle|nanochat|claude|gpt|anthropic/i.test(msg.username || "");
    const role = isAssistant ? '[ASSISTANT]' : '[USER]';
    const ts = msg.timestamp ? new Date(msg.timestamp).toLocaleString() : 'N/A';
    const text = stripHtml(msg.content || "");
    
    console.log(`${role} ${msg.username}`);
    console.log(`${ts}`);
    console.log(`${text}`);
    console.log('');
  }

  console.log('════════════════════════════════════════════════════════════════\n');

  // Tree summary
  console.log('CSS CLASSES APPLIED:\n');
  console.log('User messages:');
  console.log('  <div class="message user"> - float right, lighter background\n');
  console.log('Assistant messages:');
  console.log('  <div class="message assistant"> - float left, darker background\n');
  console.log('Metadata:');
  console.log('  <div class="msg-meta"> - username and timestamp, muted color\n');
  console.log('Content bubble:');
  console.log('  <div class="msg-bubble"> - contains HTML content from llm.jsonl\n');
}

if (require.main === module) {
  try {
    main();
  } catch (err) {
    console.error('Error:', err.message);
    process.exit(1);
  }
}
