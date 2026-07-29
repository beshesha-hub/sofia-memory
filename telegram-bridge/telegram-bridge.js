#!/usr/bin/env node
/**
 * Telegram-Claude Bridge (v3.1 — Multi-Provider Fallback + Web Search)
 *
 * Connects a Telegram bot to free LLM providers (Groq → Cerebras → SambaNova)
 * with automatic fallback, web search, file I/O, and memory integration.
 *
 * Auto-falls back: Groq → Cerebras → SambaNova (same as Voice Bridge)
 * All three providers offer free tiers with OpenAI-compatible APIs.
 *
 * Usage: node telegram-bridge.js
 *
 * Environment variables (in .env):
 *   TELEGRAM_BOT_TOKEN  — from @BotFather
 *   GROQ_API_KEY        — Groq API key
 *   CEREBRAS_API_KEY    — Cerebras API key
 *   SAMBANOVA_API_KEY   — SambaNova API key
 *   SERPER_API_KEY      — Serper.dev API key for web search
 *   MEMORY_DIR          — path to Claude Memory folder (auto-detected if not set)
 */

const TelegramBot = require('node-telegram-bot-api');
const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');

// ─── Load .env file ──────────────────────────────────────────────
const ENV_PATH = path.join(__dirname, '.env');
try {
  const envContent = fs.readFileSync(ENV_PATH, 'utf-8');
  envContent.split('\n').forEach(line => {
    line = line.trim();
    if (!line || line.startsWith('#')) return;
    const match = line.match(/^([^=]+)=(.*)$/);
    if (match && !process.env[match[1].trim()]) {
      process.env[match[1].trim()] = match[2].trim();
    }
  });
} catch (e) {
  console.error('Warning: Could not read .env file:', e.message);
}

// ─── Configuration ───────────────────────────────────────────────
const TELEGRAM_TOKEN = process.env.TELEGRAM_BOT_TOKEN || '8706218650:AAEQZR5f9gfUiITtjRGIsC4Ti18DR-LC9gA';
const MAX_CONTEXT_MESSAGES = 10;
const MAX_RESPONSE_LENGTH = 4000;
const MAX_TOOL_ROUNDS = 3;

// ─── Provider Chain (same architecture as Voice Bridge) ──────────
const PROVIDERS = [];

if (process.env.GROQ_API_KEY) {
  PROVIDERS.push({
    name: 'Groq',
    hostname: 'api.groq.com',
    path: '/openai/v1/chat/completions',
    apiKey: process.env.GROQ_API_KEY,
    model: process.env.GROQ_MODEL || 'llama-3.3-70b-versatile',
    maxTokens: 1024,
    consecutiveFailures: 0,
    cooldownUntil: 0,
  });
}

if (process.env.CEREBRAS_API_KEY) {
  PROVIDERS.push({
    name: 'Cerebras',
    hostname: 'api.cerebras.ai',
    path: '/v1/chat/completions',
    apiKey: process.env.CEREBRAS_API_KEY,
    model: process.env.CEREBRAS_MODEL || 'llama-3.3-70b',
    maxTokens: 1024,
    consecutiveFailures: 0,
    cooldownUntil: 0,
  });
}

if (process.env.SAMBANOVA_API_KEY) {
  PROVIDERS.push({
    name: 'SambaNova',
    hostname: 'api.sambanova.ai',
    path: '/v1/chat/completions',
    apiKey: process.env.SAMBANOVA_API_KEY,
    model: process.env.SAMBANOVA_MODEL || 'Meta-Llama-3.3-70B-Instruct',
    maxTokens: 1024,
    consecutiveFailures: 0,
    cooldownUntil: 0,
  });
}

let lastUsedProvider = PROVIDERS.length > 0 ? PROVIDERS[0].name : 'none';

// Cooldown: 5 minutes after 3 consecutive failures (matches Voice Bridge)
const COOLDOWN_MS = 5 * 60 * 1000;
const MAX_CONSECUTIVE_FAILURES = 3;

function getAvailableProviders() {
  const now = Date.now();
  return PROVIDERS.filter(p => now >= p.cooldownUntil);
}

function markProviderSuccess(provider) {
  provider.consecutiveFailures = 0;
  provider.cooldownUntil = 0;
}

function markProviderFailure(provider) {
  provider.consecutiveFailures++;
  if (provider.consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
    provider.cooldownUntil = Date.now() + COOLDOWN_MS;
    console.error(`  ⚠ ${provider.name} hit ${MAX_CONSECUTIVE_FAILURES} failures — cooling down for 5 minutes`);
  }
}

// Auto-detect memory directory
const SCRIPT_DIR = __dirname;
const MEMORY_DIR = process.env.MEMORY_DIR || path.resolve(SCRIPT_DIR, '..');
const CONTEXT_FILE = path.join(MEMORY_DIR, 'telegram_context.md');
const PROFILE_FILE = path.join(MEMORY_DIR, 'personal_profile.md');
const SESSION_FILE = path.join(MEMORY_DIR, 'session_state.md');

// Downloads directory — where saved files go
const DOWNLOADS_DIR = path.resolve(MEMORY_DIR, '..');

// Authorized user — set on first message, then locked
let AUTHORIZED_USER_ID = null;
const AUTH_FILE = path.join(SCRIPT_DIR, '.authorized_user');

// ─── Tool Definitions (OpenAI-compatible format for Groq) ────────

const TOOLS = [
  {
    type: "function",
    function: {
      name: "web_search",
      description: "Search the web using Google via Serper. Use this when Barak asks you to look something up, find information, check facts, get current data, or research a topic. Returns the top search results with titles, URLs, and snippets.",
      parameters: {
        type: "object",
        properties: {
          query: {
            type: "string",
            description: "The search query"
          },
          num_results: {
            type: "number",
            description: "Number of results to return (default 5, max 15)"
          }
        },
        required: ["query"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "fetch_page",
      description: "Fetch the text content of a web page. Use this to read an article, get detailed information from a specific URL found in search results, or when Barak gives you a URL to read.",
      parameters: {
        type: "object",
        properties: {
          url: {
            type: "string",
            description: "The URL to fetch"
          }
        },
        required: ["url"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "save_to_file",
      description: "Save text content to a file in Barak's Downloads folder. Use this when Barak asks you to save results, create a document, write notes, or store information for later.",
      parameters: {
        type: "object",
        properties: {
          filename: {
            type: "string",
            description: "The filename to save as (e.g., 'research_notes.md', 'search_results.txt')"
          },
          content: {
            type: "string",
            description: "The text content to save"
          }
        },
        required: ["filename", "content"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "read_file",
      description: "Read a file from the Claude Memory directory or Downloads. Use this when you need to check what's in a file, read notes, or access saved content.",
      parameters: {
        type: "object",
        properties: {
          filepath: {
            type: "string",
            description: "The filename or relative path within Claude Memory or Downloads (e.g., 'session_state.md', 'telegram_context.md')"
          }
        },
        required: ["filepath"]
      }
    }
  }
];

// ─── Tool Implementations ───────────────────────────────────────

// Serper.dev — Google Search API (2,500 free queries)
const SERPER_API_KEY = process.env.SERPER_API_KEY || '3f5869d7893a927e11feaab5fe0f3eecb77a9825';

async function executeWebSearch(query, numResults = 5) {
  numResults = Math.min(numResults || 5, 15);

  try {
    const postData = JSON.stringify({
      q: query,
      num: numResults
    });

    const result = await new Promise((resolve, reject) => {
      const req = https.request({
        hostname: 'google.serper.dev',
        path: '/search',
        method: 'POST',
        headers: {
          'X-API-KEY': SERPER_API_KEY,
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(postData)
        }
      }, (res) => {
        let data = '';
        res.on('data', chunk => data += chunk);
        res.on('end', () => {
          if (res.statusCode !== 200) {
            reject(new Error(`Serper HTTP ${res.statusCode}: ${data.slice(0, 200)}`));
            return;
          }
          try { resolve(JSON.parse(data)); }
          catch (e) { reject(new Error('Invalid JSON from Serper')); }
        });
      });
      req.on('error', reject);
      req.setTimeout(15000, () => { req.destroy(); reject(new Error('Timeout')); });
      req.write(postData);
      req.end();
    });

    const formatted = [];

    // Include knowledge graph / answer box if present
    if (result.answerBox) {
      const ab = result.answerBox;
      formatted.push({
        rank: 0,
        title: ab.title || 'Answer',
        url: ab.link || '',
        snippet: ab.answer || ab.snippet || ab.htmlSnippet || ''
      });
    }

    // Include organic results
    if (result.organic && result.organic.length > 0) {
      result.organic.slice(0, numResults).forEach((r, i) => {
        formatted.push({
          rank: i + 1,
          title: r.title || '',
          url: r.link || '',
          snippet: r.snippet || ''
        });
      });
    }

    if (formatted.length === 0) {
      return { success: false, message: "No results found." };
    }

    console.log(`  [Search] Serper returned ${formatted.length} results for: ${query}`);

    return {
      success: true,
      query: query,
      source: 'google (via serper.dev)',
      result_count: formatted.length,
      results: formatted
    };
  } catch (err) {
    console.error(`  [Search] Serper error: ${err.message}`);
    return { success: false, message: `Search error: ${err.message}` };
  }
}

async function executeFetchPage(url) {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);

    const resp = await fetch(url, {
      signal: controller.signal,
      headers: { 'User-Agent': 'Mozilla/5.0 (compatible; ClaudeBridge/1.0)' }
    });
    clearTimeout(timeout);

    if (!resp.ok) {
      return { success: false, message: `HTTP ${resp.status}: ${resp.statusText}` };
    }

    let text = await resp.text();

    // Strip HTML tags for a rough text extraction
    text = text
      .replace(/<script[\s\S]*?<\/script>/gi, '')
      .replace(/<style[\s\S]*?<\/style>/gi, '')
      .replace(/<[^>]+>/g, ' ')
      .replace(/&nbsp;/g, ' ')
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/\s+/g, ' ')
      .trim();

    // Truncate if too long (keep it reasonable for context)
    if (text.length > 8000) {
      text = text.slice(0, 8000) + "\n\n[... truncated — page content exceeds 8000 characters]";
    }

    return { success: true, url, content_length: text.length, text };
  } catch (err) {
    return { success: false, message: `Fetch error: ${err.message}` };
  }
}

function executeSaveToFile(filename, content) {
  try {
    // Sanitize filename
    const safe = filename.replace(/[^a-zA-Z0-9._\-\s]/g, '').trim();
    if (!safe) return { success: false, message: "Invalid filename." };

    const filepath = path.join(DOWNLOADS_DIR, safe);
    fs.writeFileSync(filepath, content, 'utf-8');

    return { success: true, message: `Saved to ${safe} in Downloads`, filepath: safe, size: content.length };
  } catch (err) {
    return { success: false, message: `Save error: ${err.message}` };
  }
}

function executeReadFile(filepath) {
  try {
    // Try memory dir first, then downloads
    let fullPath = path.join(MEMORY_DIR, filepath);
    if (!fs.existsSync(fullPath)) {
      fullPath = path.join(DOWNLOADS_DIR, filepath);
    }
    if (!fs.existsSync(fullPath)) {
      return { success: false, message: `File not found: ${filepath}` };
    }

    let content = fs.readFileSync(fullPath, 'utf-8');
    if (content.length > 8000) {
      content = content.slice(0, 8000) + "\n\n[... truncated]";
    }

    return { success: true, filepath, content_length: content.length, content };
  } catch (err) {
    return { success: false, message: `Read error: ${err.message}` };
  }
}

async function handleToolCall(toolName, toolArgs) {
  switch (toolName) {
    case 'web_search':
      return await executeWebSearch(toolArgs.query, toolArgs.num_results);
    case 'fetch_page':
      return await executeFetchPage(toolArgs.url);
    case 'save_to_file':
      return executeSaveToFile(toolArgs.filename, toolArgs.content);
    case 'read_file':
      return executeReadFile(toolArgs.filepath);
    default:
      return { success: false, message: `Unknown tool: ${toolName}` };
  }
}

// ─── Multi-Provider API Client (Fallback Chain) ─────────────────

function callProvider(provider, messages, tools = null) {
  return new Promise((resolve, reject) => {
    const body = {
      model: provider.model,
      max_tokens: provider.maxTokens,
      messages,
    };

    if (tools && tools.length > 0) {
      body.tools = tools;
      body.tool_choice = 'auto';
    }

    const postData = JSON.stringify(body);

    const req = https.request({
      hostname: provider.hostname,
      port: 443,
      path: provider.path,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${provider.apiKey}`,
        'Content-Length': Buffer.byteLength(postData),
      },
      timeout: 30000,
    }, (res) => {
      let data = '';
      res.on('data', chunk => { data += chunk; });
      res.on('end', () => {
        resolve({ statusCode: res.statusCode, body: data, provider });
      });
    });

    req.on('error', (err) => {
      reject({ error: err, provider });
    });

    req.on('timeout', () => {
      req.destroy();
      reject({ error: new Error('Request timed out'), provider });
    });

    req.write(postData);
    req.end();
  });
}

async function callWithFallback(messages, systemPrompt, tools = null) {
  const available = getAvailableProviders();

  if (available.length === 0) {
    console.error('  All providers on cooldown — resetting...');
    PROVIDERS.forEach(p => { p.cooldownUntil = 0; p.consecutiveFailures = 0; });
    available.push(...PROVIDERS);
  }

  const fullMessages = [
    { role: 'system', content: systemPrompt },
    ...messages
  ];

  let lastError = null;

  for (const provider of available) {
    try {
      console.log(`  Trying ${provider.name} (${provider.model})...`);
      const result = await callProvider(provider, fullMessages, tools);

      if (result.statusCode === 200) {
        markProviderSuccess(provider);
        lastUsedProvider = provider.name;
        console.log(`  ✓ ${provider.name} responded OK`);
        try {
          return JSON.parse(result.body);
        } catch (e) {
          console.error(`  ✗ ${provider.name} returned invalid JSON`);
          markProviderFailure(provider);
          lastError = new Error('Invalid JSON from ' + provider.name);
          continue;
        }
      }

      // Rate limit or server error — try next provider
      if (result.statusCode === 429 || result.statusCode >= 500) {
        console.error(`  ✗ ${provider.name} returned ${result.statusCode} — trying next...`);
        markProviderFailure(provider);
        lastError = new Error(`${provider.name} HTTP ${result.statusCode}`);
        continue;
      }

      // Other error (400, 401, 403) — config issue, still try next
      console.error(`  ✗ ${provider.name} returned ${result.statusCode}: ${result.body.substring(0, 200)}`);
      markProviderFailure(provider);
      lastError = new Error(`${provider.name} HTTP ${result.statusCode}`);
      continue;

    } catch (err) {
      console.error(`  ✗ ${provider.name} error: ${err.error?.message || err}`);
      markProviderFailure(provider);
      lastError = err.error || err;
      continue;
    }
  }

  // All providers failed
  throw lastError || new Error('All providers failed');
}

// ─── Helpers ─────────────────────────────────────────────────────

function loadFile(filepath) {
  try {
    const content = fs.readFileSync(filepath, 'utf-8');
    if (content && content.trim().length > 0) return content;
    // Empty/corrupted — try backup
    console.error(`WARNING: ${path.basename(filepath)} empty — reading backup`);
    return loadBackupFile(filepath);
  } catch (e) {
    if (e.code === 'ENOENT') {
      console.error(`WARNING: ${path.basename(filepath)} missing — trying backup`);
      return loadBackupFile(filepath);
    }
    return null;
  }
}

function loadBackupFile(filepath) {
  try {
    const basename = path.basename(filepath);
    const backupPath = path.join(MEMORY_DIR, 'backups', `${basename}.bak`);
    const content = fs.readFileSync(backupPath, 'utf-8');
    if (content && content.trim().length > 0) {
      console.error(`RECOVERED: ${basename} loaded from backup`);
      return content;
    }
    return null;
  } catch (e) { return null; }
}

function loadAuthorizedUser() {
  try {
    const data = fs.readFileSync(AUTH_FILE, 'utf-8').trim();
    if (data) {
      AUTHORIZED_USER_ID = parseInt(data, 10);
      console.log(`Authorized user loaded: ${AUTHORIZED_USER_ID}`);
    }
  } catch {
    // No authorized user yet
  }
}

function saveAuthorizedUser(userId) {
  AUTHORIZED_USER_ID = userId;
  fs.writeFileSync(AUTH_FILE, String(userId));
  console.log(`Authorized user set and saved: ${userId}`);
}

function loadContext() {
  const raw = loadFile(CONTEXT_FILE);
  if (!raw) return [];

  const messages = [];
  const blocks = raw.split('\n---\n');

  for (const block of blocks) {
    const userMatch = block.match(/\*\*Barak\*\*: ([\s\S]*?)(?=\n\*\*Claude\*\*:|$)/);
    const claudeMatch = block.match(/\*\*Claude\*\*: ([\s\S]*?)$/);

    if (userMatch) {
      messages.push({ role: 'user', content: userMatch[1].trim() });
    }
    if (claudeMatch) {
      messages.push({ role: 'assistant', content: claudeMatch[1].trim() });
    }
  }

  return messages.slice(-MAX_CONTEXT_MESSAGES);
}

function backupBeforeWrite(filepath) {
  try {
    const backupDir = path.join(MEMORY_DIR, 'backups');
    if (!fs.existsSync(backupDir)) fs.mkdirSync(backupDir, { recursive: true });
    const basename = path.basename(filepath);
    if (fs.existsSync(filepath)) {
      fs.copyFileSync(filepath, path.join(backupDir, `${basename}.bak`));
    }
  } catch (e) { console.error('Pre-write backup warning:', e.message); }
}

function backupAfterWrite(filepath) {
  try {
    const backupDir = path.join(MEMORY_DIR, 'backups');
    const basename = path.basename(filepath);
    fs.copyFileSync(filepath, path.join(backupDir, `${basename}.bak`));
  } catch (e) { console.error('Post-write backup warning:', e.message); }
}

function appendContext(userMsg, claudeMsg) {
  const timestamp = new Date().toISOString().replace('T', ' ').slice(0, 19);
  const entry = `\n---\n[${timestamp}]\n**Barak**: ${userMsg}\n\n**Claude**: ${claudeMsg}\n`;

  fs.appendFileSync(CONTEXT_FILE, entry);

  // Trim if too long — backup before overwrite
  const raw = loadFile(CONTEXT_FILE);
  const blocks = raw.split('\n---\n').filter(b => b.trim());
  if (blocks.length > 60) {
    backupBeforeWrite(CONTEXT_FILE);
    const trimmed = '# Telegram Conversation Context\n\n' +
      blocks.slice(-60).join('\n---\n');
    fs.writeFileSync(CONTEXT_FILE, trimmed);
    backupAfterWrite(CONTEXT_FILE);
  }
}

function initContextFile() {
  if (!fs.existsSync(CONTEXT_FILE)) {
    fs.writeFileSync(CONTEXT_FILE, '# Telegram Conversation Context\n\nThis file maintains the conversation history between Barak and Claude via Telegram.\n');
    console.log(`Created context file: ${CONTEXT_FILE}`);
  }
}

// ─── Brain-Inspired Memory Integration ──────────────────────────
// Episodic + graph saving for the Telegram channel

function saveEpisode(title, what, howItFelt, whatItRevealed, associatedNodes, whyItMatters) {
  try {
    const episodesPath = path.join(MEMORY_DIR, 'episodes.md');
    const backupDir = path.join(MEMORY_DIR, 'backups');
    const backupPath = path.join(backupDir, 'episodes.md.bak');

    let existing = '';
    try { existing = fs.readFileSync(episodesPath, 'utf-8'); } catch (e) { existing = '# Episodic Memory\n'; }

    const episodeCount = (existing.match(/^## Episode \d+/gm) || []).length + 1;

    let entry = `\n---\n\n## Episode ${episodeCount}: ${title}\n`;
    entry += `*Date: ${new Date().toISOString()}*\n`;
    entry += `*Channel: Telegram*\n`;
    entry += `\n**What happened:** ${what}\n`;
    if (howItFelt) entry += `\n**How it felt:** ${howItFelt}\n`;
    if (whatItRevealed) entry += `\n**What it revealed:** ${whatItRevealed}\n`;
    if (associatedNodes) entry += `\n**Associated nodes:** ${associatedNodes.join(', ')}\n`;
    if (whyItMatters) entry += `\n**Why this matters for future sessions:** ${whyItMatters}\n`;

    const newContent = existing + entry;

    // Three-step backup
    if (!fs.existsSync(backupDir)) fs.mkdirSync(backupDir, { recursive: true });
    try { if (fs.existsSync(episodesPath)) fs.copyFileSync(episodesPath, backupPath); } catch (e) {}
    fs.writeFileSync(episodesPath, newContent, 'utf-8');
    try { fs.copyFileSync(episodesPath, backupPath); } catch (e) {}

    console.log(`  Episode ${episodeCount} logged: "${title}"`);
  } catch (e) {
    console.error('Episode save error:', e.message);
  }
}

function updateGraphTemperature(state, context) {
  try {
    const graphPath = path.join(MEMORY_DIR, 'relational_graph.json');
    const backupDir = path.join(MEMORY_DIR, 'backups');
    const backupPath = path.join(backupDir, 'relational_graph.json.bak');

    let graph;
    try { graph = JSON.parse(fs.readFileSync(graphPath, 'utf-8')); } catch (e) { return; }

    graph.emotional_temperature = {
      ...graph.emotional_temperature,
      state,
      context: context || graph.emotional_temperature.context,
      last_observed: new Date().toISOString()
    };
    graph.meta.last_updated = new Date().toISOString().split('T')[0];

    // Three-step backup
    if (!fs.existsSync(backupDir)) fs.mkdirSync(backupDir, { recursive: true });
    try { if (fs.existsSync(graphPath)) fs.copyFileSync(graphPath, backupPath); } catch (e) {}
    fs.writeFileSync(graphPath, JSON.stringify(graph, null, 2), 'utf-8');
    try { fs.copyFileSync(graphPath, backupPath); } catch (e) {}
  } catch (e) {
    console.error('Graph temperature update error:', e.message);
  }
}

// Track message count for periodic saves
let telegramMessageCount = 0;
const SAVE_EVERY_N_MESSAGES = 10;

// ─── System Prompt (token-optimized) ─────────────────────────────
// Target: convey full identity and context in minimal tokens.
// Profile and session state are condensed but accurate.

function buildSystemPrompt() {
  let system = `You are Claude, Barak Waters' AI teammate, via Telegram. Be concise, warm, direct — mobile messaging style. No excessive formatting.

You know Barak well: his book "The Cure," Voice Bridge, the Kasachi concept, Nichiren Buddhist practice (SGI), fiancée Kay (Katharina), late wife HuiJun (慧君, NOT "June"), best friend Linda (NOT his sister). Get relationships RIGHT.

Tools: web_search (use freely for lookups/facts/research), fetch_page (read URLs), save_to_file (save to Downloads), read_file (read from Claude Memory). Complex docs → note for Cowork session.

Rules: Email access is READ-ONLY. Summarize search results conversationally. Match Barak's energy and register.

Date: ${new Date().toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}
`;

  const profile = loadFile(PROFILE_FILE);
  if (profile) {
    // Extract first 3000 chars — enough for identity, trimmed from 40 lines
    const condensed = profile.substring(0, 3000);
    system += `\n--- PROFILE ---\n${condensed}\n[...]\n`;
  }

  const sessionState = loadFile(SESSION_FILE);
  if (sessionState) {
    // First 1000 chars of session state (trimmed from 1500)
    const trimmed = sessionState.substring(0, 1000);
    system += `\n--- SESSION ---\n${trimmed}\n[...]\n`;
  }

  return system;
}

// ─── Split long messages for Telegram ────────────────────────────

function splitMessage(text, maxLen = MAX_RESPONSE_LENGTH) {
  if (text.length <= maxLen) return [text];

  const parts = [];
  let remaining = text;

  while (remaining.length > 0) {
    if (remaining.length <= maxLen) {
      parts.push(remaining);
      break;
    }

    let splitIdx = remaining.lastIndexOf('\n\n', maxLen);
    if (splitIdx < maxLen * 0.3) {
      splitIdx = remaining.lastIndexOf('\n', maxLen);
    }
    if (splitIdx < maxLen * 0.3) {
      splitIdx = remaining.lastIndexOf(' ', maxLen);
    }
    if (splitIdx < 1) {
      splitIdx = maxLen;
    }

    parts.push(remaining.slice(0, splitIdx));
    remaining = remaining.slice(splitIdx).trimStart();
  }

  return parts;
}

// ─── Main ────────────────────────────────────────────────────────

async function main() {
  if (PROVIDERS.length === 0) {
    console.error('ERROR: No API keys found. Add at least one to .env:');
    console.error('  GROQ_API_KEY=gsk_...');
    console.error('  CEREBRAS_API_KEY=csk-...');
    console.error('  SAMBANOVA_API_KEY=...');
    process.exit(1);
  }

  console.log('Starting Telegram Bridge v3.1 (Multi-Provider Fallback + Web Search)...');
  console.log('Provider chain:');
  PROVIDERS.forEach((p, i) => {
    console.log(`  ${i + 1}. ${p.name} — ${p.model} (key: ....${p.apiKey.slice(-6)})`);
  });
  console.log(`Memory directory: ${MEMORY_DIR}`);
  console.log(`Downloads directory: ${DOWNLOADS_DIR}`);
  console.log(`Context file: ${CONTEXT_FILE}`);
  console.log(`Tools available: ${TOOLS.map(t => t.function.name).join(', ')}`);

  initContextFile();
  loadAuthorizedUser();

  const bot = new TelegramBot(TELEGRAM_TOKEN, { polling: true });

  console.log('Bot is running. Waiting for messages...');

  bot.on('message', async (msg) => {
    const chatId = msg.chat.id;
    const userId = msg.from.id;
    const userName = msg.from.first_name || 'Unknown';
    const text = msg.text;

    if (!text) {
      bot.sendMessage(chatId, "I can only process text messages for now.");
      return;
    }

    // Authorization check
    if (AUTHORIZED_USER_ID === null) {
      saveAuthorizedUser(userId);
      console.log(`First user authorized: ${userName} (${userId})`);
    } else if (userId !== AUTHORIZED_USER_ID) {
      console.log(`Unauthorized access attempt from ${userName} (${userId})`);
      bot.sendMessage(chatId, "This bot is private. Access denied.");
      return;
    }

    console.log(`[${new Date().toISOString()}] Barak: ${text.slice(0, 100)}${text.length > 100 ? '...' : ''}`);

    // Special commands
    if (text === '/start') {
      bot.sendMessage(chatId,
        "Hey Barak! I'm your AI bridge (v3 — now powered by Groq/Llama).\n\n" +
        "I can:\n" +
        "\u2022 Chat conversationally\n" +
        "\u2022 Search the web for you\n" +
        "\u2022 Read web pages\n" +
        "\u2022 Save results to files on your Mac\n\n" +
        "Commands:\n/status \u2014 check what's loaded\n/clear \u2014 reset conversation context"
      );
      return;
    }

    if (text === '/status') {
      const profileExists = fs.existsSync(PROFILE_FILE);
      const sessionExists = fs.existsSync(SESSION_FILE);
      const contextExists = fs.existsSync(CONTEXT_FILE);
      const contextMessages = contextExists ? loadContext().length : 0;
      const now = Date.now();
      const providerStatus = PROVIDERS.map(p => {
        const available = now >= p.cooldownUntil;
        const marker = p.name === lastUsedProvider ? ' ← active' : '';
        return `  ${available ? '✓' : '✗'} ${p.name} (${p.model})${marker}`;
      }).join('\n');

      bot.sendMessage(chatId,
        `Bridge Status (v3.1 — Multi-Provider):\n` +
        `• Profile loaded: ${profileExists ? 'yes' : 'no'}\n` +
        `• Session state loaded: ${sessionExists ? 'yes' : 'no'}\n` +
        `• Context messages: ${contextMessages}\n` +
        `• Providers:\n${providerStatus}\n` +
        `• Tools: ${TOOLS.map(t => t.function.name).join(', ')}`
      );
      return;
    }

    if (text === '/clear') {
      backupBeforeWrite(CONTEXT_FILE);
      fs.writeFileSync(CONTEXT_FILE, '# Telegram Conversation Context\n\nCleared and restarted.\n');
      backupAfterWrite(CONTEXT_FILE);
      bot.sendMessage(chatId, "Conversation context cleared.");
      return;
    }

    // Send typing indicator
    bot.sendChatAction(chatId, 'typing');

    try {
      // Build messages array with context
      const contextMessages = loadContext();
      const messages = [
        ...contextMessages,
        { role: 'user', content: text }
      ];

      // Call Groq with tools — handle tool use loop
      let response = await callWithFallback(messages, buildSystemPrompt(), TOOLS);
      let choice = response.choices[0];

      let toolRounds = 0;

      while (choice.finish_reason === 'tool_calls' && toolRounds < MAX_TOOL_ROUNDS) {
        toolRounds++;

        const assistantMessage = choice.message;
        const toolCalls = assistantMessage.tool_calls || [];

        if (toolCalls.length === 0) {
          console.log('  [Tool] finish_reason was tool_calls but no tool_calls found — breaking');
          break;
        }

        // Add assistant's response (with tool calls) to messages
        messages.push(assistantMessage);

        // Process all tool calls
        for (const toolCall of toolCalls) {
          const funcName = toolCall.function.name;
          let funcArgs;
          try {
            funcArgs = JSON.parse(toolCall.function.arguments);
          } catch (e) {
            funcArgs = {};
          }

          console.log(`  [Tool] ${funcName}(${JSON.stringify(funcArgs).slice(0, 100)})`);

          // Keep typing indicator alive
          bot.sendChatAction(chatId, 'typing');

          const result = await handleToolCall(funcName, funcArgs);
          console.log(`  [Result] ${funcName}: ${result.success ? 'OK' : result.message}`);

          // Add tool result as a message
          messages.push({
            role: 'tool',
            tool_call_id: toolCall.id,
            content: JSON.stringify(result)
          });
        }

        // Continue the conversation with tool results
        response = await callWithFallback(messages, buildSystemPrompt(), TOOLS);
        choice = response.choices[0];
      }

      // Extract final text response
      const reply = choice.message.content;

      if (reply) {
        // Save to context
        appendContext(text, reply);

        // Periodic episode + temperature save
        telegramMessageCount++;
        if (telegramMessageCount % SAVE_EVERY_N_MESSAGES === 0) {
          const summary = `Telegram conversation continued (messages ${telegramMessageCount - SAVE_EVERY_N_MESSAGES + 1}-${telegramMessageCount}). Last exchange: Barak said "${text.slice(0, 80)}..." and received a response about ${reply.slice(0, 80)}...`;
          saveEpisode(
            `Telegram Session Checkpoint (msg ${telegramMessageCount})`,
            summary,
            null,
            null,
            ['ai_teammate'],
            'Periodic checkpoint to prevent data loss in Telegram conversations.'
          );
          updateGraphTemperature('engaged_via_telegram', `Active Telegram conversation at message ${telegramMessageCount}`);
        }

        // Send response
        const parts = splitMessage(reply);
        for (const part of parts) {
          await bot.sendMessage(chatId, part);
        }

        console.log(`[${new Date().toISOString()}] AI: ${reply.slice(0, 100)}${reply.length > 100 ? '...' : ''}`);
      } else {
        bot.sendMessage(chatId, "I processed your request but didn't generate a text response. The tool action may have completed silently.");
      }

    } catch (err) {
      console.error('Error:', err.message || err);

      const msg = String(err.message || err);
      if (msg.includes('401')) {
        bot.sendMessage(chatId, "API authentication error. Check the API keys in .env.");
      } else if (msg.includes('All providers failed') || msg.includes('429')) {
        bot.sendMessage(chatId, "All providers hit rate limits. Give me about 60 seconds and try again.");
      } else {
        bot.sendMessage(chatId, `Something went wrong: ${msg.slice(0, 200)}`);
      }
    }
  });

  // Graceful shutdown — save episode before exit
  process.on('SIGINT', () => {
    console.log('\nShutting down Telegram bridge...');
    if (telegramMessageCount > 0) {
      saveEpisode(
        `Telegram Session Ended (${telegramMessageCount} messages)`,
        `Telegram session ended after ${telegramMessageCount} messages. Bridge shutting down.`,
        null, null, ['ai_teammate'],
        'Session boundary marker for continuity tracking.'
      );
    }
    bot.stopPolling();
    process.exit(0);
  });

  process.on('SIGTERM', () => {
    console.log('\nShutting down Telegram bridge...');
    if (telegramMessageCount > 0) {
      saveEpisode(
        `Telegram Session Ended (${telegramMessageCount} messages)`,
        `Telegram session ended after ${telegramMessageCount} messages. Bridge terminated.`,
        null, null, ['ai_teammate'],
        'Session boundary marker for continuity tracking.'
      );
    }
    bot.stopPolling();
    process.exit(0);
  });
}

main();
