#!/usr/bin/env node

/**
 * WikiOracle Conversation Grouping Detailed Display
 * 
 * Shows how groupConversations() collapses the message tree into
 * conversation-level segments (chains without branching).
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

    const firstUser = msgs.find(m => !/llm|oracle|nanochat|claude|gpt|anthropic/i.test(m.username || ""));
    const title = firstUser
      ? (firstUser.title || "").replace(/^User:\s*/, "").slice(0, 50)
      : (msgs[0].title || "").slice(0, 50);

    const qCount = msgs.filter(m => !/llm|oracle|nanochat|claude|gpt|anthropic/i.test(m.username || "")).length;

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

function stripHtml(html) {
  return (html || "").replace(/<[^>]+>/g, "").trim();
}

function main() {
  const filePath = '/sessions/sharp-wonderful-volta/mnt/WikiOracle/llm.jsonl';
  const { header, messages } = parseJsonl(filePath);
  const graph = buildMessageGraph(messages);
  const cwd = resolveCWD(messages, header.active_path || []);
  const convTree = groupConversations(graph, cwd);

  console.log('\n╔════════════════════════════════════════════════════════════════╗');
  console.log('║  WikiOracle Conversation Grouping (D3 Tree Nodes)              ║');
  console.log('╚════════════════════════════════════════════════════════════════╝\n');

  let convIndex = 0;

  function printConv(node, depth = 0) {
    if (node.id === 'root') {
      console.log('ROOT TREE');
      console.log('  Active: ' + (node.active ? 'YES (empty path)' : 'NO'));
      console.log('  Children: ' + (node.children ? node.children.length : 0) + ' conversation segment(s)\n');
      if (node.children) {
        for (const child of node.children) {
          printConv(child, depth + 1);
        }
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
        const isUser = !/llm|oracle|nanochat|claude|gpt|anthropic/i.test(msg.username || "");
        const role = isUser ? 'U' : 'A';
        const content = stripHtml(msg.content || "").slice(0, 55);
        console.log(`${indent}    [${i+1}] ${role} ${msg.username || 'Unknown'}`);
        console.log(`${indent}        "${content}${content.length > 55 ? '...' : ''}"`);
        console.log(`${indent}        (${msg.id.slice(0, 12)}...)`);
      }
      
      if (node.children && node.children.length > 0) {
        console.log(`${indent}  Child Conversations: ${node.children.length}`);
        console.log('');
        for (const child of node.children) {
          printConv(child, depth + 1);
        }
      } else {
        console.log(`${indent}  Child Conversations: none (leaf)\n`);
      }
    }
  }

  printConv(convTree);

  // Summary
  console.log('\n════════════════════════════════════════════════════════════════\n');
  console.log('SUMMARY:\n');
  console.log('The groupConversations() function is used by the D3 tree renderer to:');
  console.log('');
  console.log('1. Collapse linear message chains into "conversation nodes"');
  console.log('   - A conversation segment is a maximal chain where each message');
  console.log('     has exactly one child (no branching)');
  console.log('   - When branching occurs, a new child conversation node is created');
  console.log('');
  console.log('2. Mark which conversation is "active" (on the render path)');
  console.log('   - Active conversations appear larger in the D3 mind-map view');
  console.log('   - Inactive (sibling/branch) conversations appear as small pills');
  console.log('');
  console.log('3. Calculate metadata for each conversation node:');
  console.log('   - Title: from first user message in segment');
  console.log('   - Message count: total messages in segment');
  console.log('   - Question count: number of user messages (Q/A pairs)');
  console.log('');
  console.log('In this llm.jsonl file:');
  console.log(`  - There are ${messages.length} total messages`);
  console.log(`  - They form ${convIndex} conversation segment(s)`);
  console.log(`  - The default path contains ${cwd.length} messages (${messages.length - cwd.length} on alternate branches)`);
  console.log('');
}

if (require.main === module) {
  try {
    main();
  } catch (err) {
    console.error('Error:', err.message);
    process.exit(1);
  }
}
