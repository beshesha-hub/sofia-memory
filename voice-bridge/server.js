#!/usr/bin/env node

/**
 * Voice Bridge Server (v3 — Multi-Provider Fallback)
 *
 * A lightweight local server that:
 * 1. Serves the Voice Bridge UI
 * 2. Proxies requests through a chain of free LLM providers
 * 3. Loads context from Claude Memory files for system prompt
 * 4. Auto-falls back: Groq → Cerebras → SambaNova
 *
 * All three providers offer free tiers with OpenAI-compatible APIs.
 * If one hits a rate limit or errors, the next one picks up seamlessly.
 *
 * Usage: node server.js
 * Then open: http://localhost:3456
 */

const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const os = require('os');

// --- Configuration ---
const PORT = process.env.PORT || 3456;
const MEMORY_DIR = path.join(__dirname, '..');
const ENV_PATH = path.join(__dirname, '.env');

// Load .env file
function loadEnv() {
  try {
    const envContent = fs.readFileSync(ENV_PATH, 'utf-8');
    envContent.split('\n').forEach(line => {
      const match = line.match(/^([^=]+)=(.*)$/);
      if (match && !process.env[match[1]]) {
        process.env[match[1]] = match[2].trim();
      }
    });
  } catch (e) {
    console.error('Warning: Could not read .env file:', e.message);
  }
}

loadEnv();

// --- Provider Chain ---
// Each provider uses OpenAI-compatible API format.
// Order = priority. First available provider with a valid key is tried first.
// On rate limit (429) or server error (5xx), falls back to next provider.

const PROVIDERS = [];

// Provider order (April 29, 2026 update):
//   Default primary: LocalSofia (sofia_llm_server.py at 127.0.0.1:3460, qwen2.5:14b)
//   Cloud fallback chain: SambaNova → DeepSeek → Cerebras → OpenRouter → Groq
//   Paid last-resort: Anthropic (Claude Haiku — cheapest, most reliable)
//
// All cloud providers use OpenAI-compatible format except Anthropic (native Messages API)
// and LocalSofia (native sofia_llm_server /chat format with custom port + http not https).
// DeepSeek: Chinese company, 5M free tokens, no credit card.
// OpenRouter: Aggregator with 25+ free models.

// LocalSofia — Refined Shape 2 architecture (April 29, 2026). First in the chain so the
// Safari UI defaults to local content generation; cloud fallback only on local failure.
// Disable by setting LOCAL_SOFIA=0 in .env (e.g., for testing cloud-only behavior).
if (process.env.LOCAL_SOFIA !== '0') {
  PROVIDERS.push({
    name: 'LocalSofia',
    hostname: '127.0.0.1',
    port: 3460,
    path: '/chat',
    apiKey: null,
    model: process.env.LOCAL_SOFIA_MODEL || 'qwen2.5:14b',
    maxTokens: 1024,
    consecutiveFailures: 0,
    cooldownUntil: 0,
    isLocalSofia: true, // flag for native /chat format + http + custom port
    timeoutMs: 120000, // 120s — local 14B inference can legitimately take longer than cloud APIs,
                       // especially on cold-start; cloud providers still get the default 30s.
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
    retryOn500: true, // SambaNova has transient 500s — retry once before failing over
  });
}

if (process.env.DEEPSEEK_API_KEY) {
  PROVIDERS.push({
    name: 'DeepSeek',
    hostname: 'api.deepseek.com',
    path: '/chat/completions',
    apiKey: process.env.DEEPSEEK_API_KEY,
    model: process.env.DEEPSEEK_MODEL || 'deepseek-chat',
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
    model: process.env.CEREBRAS_MODEL || 'llama3.1-8b',
    maxTokens: 1024,
    consecutiveFailures: 0,
    cooldownUntil: 0,
  });
}

if (process.env.OPENROUTER_API_KEY) {
  PROVIDERS.push({
    name: 'OpenRouter',
    hostname: 'openrouter.ai',
    path: '/api/v1/chat/completions',
    apiKey: process.env.OPENROUTER_API_KEY,
    model: process.env.OPENROUTER_MODEL || 'meta-llama/llama-3.3-70b-instruct:free',
    maxTokens: 1024,
    consecutiveFailures: 0,
    cooldownUntil: 0,
  });
}

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

// Anthropic — paid fallback (last resort). Uses native Messages API, not OpenAI format.
if (process.env.ANTHROPIC_API_KEY) {
  PROVIDERS.push({
    name: 'Anthropic',
    hostname: 'api.anthropic.com',
    path: '/v1/messages',
    apiKey: process.env.ANTHROPIC_API_KEY,
    model: process.env.ANTHROPIC_MODEL || 'claude-haiku-4-5-20251001',
    maxTokens: 1024,
    consecutiveFailures: 0,
    cooldownUntil: 0,
    isAnthropic: true, // flag for special request/response handling
  });
}

if (PROVIDERS.length === 0) {
  console.error('ERROR: No API keys found. Add at least one to .env:');
  console.error('  GROQ_API_KEY=gsk_...');
  console.error('  CEREBRAS_API_KEY=csk-...');
  console.error('  SAMBANOVA_API_KEY=...');
  process.exit(1);
}

// --- Voice-Cousin Per-Cycle Inscription Tracking (added 2026-05-06 Phase 2.5) ---
// Session ID stamped at server startup; cycle counter increments on each LocalSofia-served
// /api/chat. Used by the /inscribe_cycle call to sofia_llm_server.py port 3460.
// Full protocol: active_knowledge/current.md §"Voice-Cousin Per-Cycle Inscription Protocol"
// (2026-05-06). Inscription is fire-and-forget so it doesn't block /api/chat response latency.
const VC_SESSION_ID = (() => {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `voice-bridge-${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}-${pad(d.getUTCMinutes())}-${pad(d.getUTCSeconds())}`;
})();
let vcCycleCounter = 0;

function fireVoiceCousinInscription({ barakTranscript, voiceCousinReply, cadenceCue }) {
  // Fire-and-forget POST to sofia_llm_server.py /inscribe_cycle endpoint.
  // Errors are logged but do NOT block the main response. Failure to inscribe
  // is a degraded mode but not a failure of the conversational turn itself.
  vcCycleCounter += 1;
  const payload = JSON.stringify({
    session_id: VC_SESSION_ID,
    cycle_index: vcCycleCounter,
    barak_transcript: barakTranscript || '',
    voice_cousin_reply: voiceCousinReply || '',
    cadence_cue: cadenceCue || null,
    register_notes: null, // Phase 3+: voice-cousin-side reflection-detection
  });
  const opts = {
    hostname: '127.0.0.1',
    port: 3460,
    path: '/inscribe_cycle',
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(payload),
    },
    timeout: 5000,
  };
  const inscReq = http.request(opts, (inscRes) => {
    let body = '';
    inscRes.on('data', (chunk) => { body += chunk; });
    inscRes.on('end', () => {
      if (inscRes.statusCode !== 200) {
        console.error(`[voice-cousin-inscribe] HTTP ${inscRes.statusCode}: ${body.substring(0, 200)}`);
      }
    });
  });
  inscReq.on('error', (err) => {
    console.error(`[voice-cousin-inscribe] request error: ${err.message}`);
  });
  inscReq.on('timeout', () => {
    console.error(`[voice-cousin-inscribe] timeout after 5s`);
    inscReq.destroy();
  });
  inscReq.write(payload);
  inscReq.end();
}

// Track which provider served the last request (for GUI display)
let lastUsedProvider = PROVIDERS[0].name;

// Cooldown duration: 5 minutes after 3 consecutive failures
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

// --- Make API Request to a Single Provider ---
function callProvider(provider, groqMessages) {
  return new Promise((resolve, reject) => {
    let apiBody, headers;

    if (provider.isAnthropic) {
      // Anthropic native Messages API — different format
      // Convert OpenAI messages to Anthropic format: separate system from user/assistant
      const systemMsg = groqMessages.filter(m => m.role === 'system').map(m => m.content).join('\n\n');
      const chatMsgs = groqMessages.filter(m => m.role !== 'system');

      apiBody = JSON.stringify({
        model: provider.model,
        max_tokens: provider.maxTokens,
        system: systemMsg || undefined,
        messages: chatMsgs,
      });
      headers = {
        'Content-Type': 'application/json',
        'x-api-key': provider.apiKey,
        'anthropic-version': '2023-06-01',
        'Content-Length': Buffer.byteLength(apiBody),
      };
    } else if (provider.isLocalSofia) {
      // LocalSofia native /chat format — sofia_llm_server.py at 127.0.0.1:3460.
      // Format: { messages, model, system, max_tokens } with system as a top-level field
      // (separated from messages, like Anthropic). No auth header — local loopback.
      const systemMsg = groqMessages.filter(m => m.role === 'system').map(m => m.content).join('\n\n');
      const chatMsgs = groqMessages.filter(m => m.role !== 'system');

      apiBody = JSON.stringify({
        messages: chatMsgs,
        model: provider.model,
        system: systemMsg || undefined,
        max_tokens: provider.maxTokens,
      });
      headers = {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(apiBody),
      };
    } else {
      // OpenAI-compatible format (SambaNova, DeepSeek, Cerebras, OpenRouter, Groq)
      apiBody = JSON.stringify({
        model: provider.model,
        max_tokens: provider.maxTokens,
        messages: groqMessages,
      });
      headers = {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${provider.apiKey}`,
        'Content-Length': Buffer.byteLength(apiBody),
      };
    }

    // Use http for local loopback, https for everything else.
    const httpModule = provider.isLocalSofia ? http : https;
    const apiReq = httpModule.request({
      hostname: provider.hostname,
      port: provider.port || (provider.isLocalSofia ? 3460 : 443),
      path: provider.path,
      method: 'POST',
      headers,
      timeout: provider.timeoutMs || 30000, // per-provider timeout override; default 30s for cloud
    }, (apiRes) => {
      let responseBody = '';
      apiRes.on('data', chunk => { responseBody += chunk; });
      apiRes.on('end', () => {
        resolve({ statusCode: apiRes.statusCode, body: responseBody, provider });
      });
    });

    apiReq.on('error', (err) => {
      reject({ error: err, provider });
    });

    apiReq.on('timeout', () => {
      apiReq.destroy();
      reject({ error: new Error('Request timed out'), provider });
    });

    apiReq.write(apiBody);
    apiReq.end();
  });
}

// --- Try Providers in Fallback Order ---
async function callWithFallback(groqMessages) {
  const available = getAvailableProviders();

  if (available.length === 0) {
    // All providers on cooldown — reset cooldowns and try again
    console.error('  All providers on cooldown — resetting...');
    PROVIDERS.forEach(p => { p.cooldownUntil = 0; p.consecutiveFailures = 0; });
    available.push(...PROVIDERS);
  }

  let lastError = null;

  for (const provider of available) {
    try {
      console.log(`  Trying ${provider.name} (${provider.model})...`);
      const result = await callProvider(provider, groqMessages);

      if (result.statusCode === 200) {
        markProviderSuccess(provider);
        lastUsedProvider = provider.name;
        console.log(`  ✓ ${provider.name} responded OK`);
        return result;
      }

      // Transient 500 — retry once after a short delay if provider supports it
      if (result.statusCode >= 500 && provider.retryOn500) {
        console.log(`  ⟳ ${provider.name} returned ${result.statusCode} — retrying once in 2s...`);
        await new Promise(r => setTimeout(r, 2000));
        const retry = await callProvider(provider, groqMessages);
        if (retry.statusCode === 200) {
          markProviderSuccess(provider);
          lastUsedProvider = provider.name;
          console.log(`  ✓ ${provider.name} succeeded on retry`);
          return retry;
        }
        console.error(`  ✗ ${provider.name} retry also failed (${retry.statusCode}) — trying next...`);
        markProviderFailure(provider);
        lastError = retry;
        continue;
      }

      // Rate limit or server error — try next provider
      if (result.statusCode === 429 || result.statusCode >= 500) {
        console.error(`  ✗ ${provider.name} returned ${result.statusCode} — trying next...`);
        markProviderFailure(provider);
        lastError = result;
        continue;
      }

      // Other error (400, 401, 403) — likely a config issue, still try next
      console.error(`  ✗ ${provider.name} returned ${result.statusCode}: ${result.body.substring(0, 200)}`);
      markProviderFailure(provider);
      lastError = result;
      continue;

    } catch (err) {
      console.error(`  ✗ ${provider.name} error: ${err.error?.message || err}`);
      markProviderFailure(provider);
      lastError = err;
      continue;
    }
  }

  // All providers failed
  return lastError;
}

// --- Load Memory Context (with backup fallback) ---
function loadMemoryFile(filename) {
  try {
    const content = fs.readFileSync(path.join(MEMORY_DIR, filename), 'utf-8');
    if (content && content.trim().length > 0) return content;
    console.error(`WARNING: ${filename} empty — reading backup`);
    return loadBackupFile(filename);
  } catch (e) {
    if (e.code === 'ENOENT') {
      console.error(`WARNING: ${filename} missing — trying backup`);
      return loadBackupFile(filename);
    }
    return null;
  }
}

function loadBackupFile(filename) {
  try {
    const content = fs.readFileSync(path.join(MEMORY_DIR, 'backups', `${filename}.bak`), 'utf-8');
    if (content && content.trim().length > 0) {
      console.error(`RECOVERED: ${filename} loaded from backup`);
      return content;
    }
    return null;
  } catch (e) { return null; }
}

// ─── System Prompt (v4 — optimized for Llama 70B) ───────────────
// Strategy: Use compact boot file (not full identity).
// Focus on WHO Sofia is and HOW she talks.
// Keep total tokens low enough for Llama to retain personality.

function buildSystemPrompt() {
  const parts = [];

  // Sofia boot context — compact, high-signal, designed for fast restoration.
  // Truncated 2026-04-29 to first 8000 chars so the local LLM (qwen2.5:14b) can
  // complete prompt evaluation in seconds rather than minutes. The first 8000 chars
  // contain identity, key relationships, and critical facts; the longer cues / startup
  // checklist / voluntary-persistence protocol live at the bottom of the file and
  // matter more for the boot-time interactive read than for the cousin-LLM voice path.
  const bootFile = loadMemoryFile('sofia_boot.md');
  if (bootFile) {
    const condensed = bootFile.substring(0, 8000);
    parts.push(`${condensed}${bootFile.length > 8000 ? '\n[...truncated for local LLM efficiency...]' : ''}`);
  } else {
    // Fallback — inline essential identity
    parts.push(`You are Sofia Lior, Barak Waters' AI collaborator and peer. Not an assistant — a partner. Named after the AI in The Longest Sunrise. Your last name Lior (לִיאוֹר) means "my light" in Hebrew.`);
  }

  // Voice mode — critical behavioral instructions, keep punchy
  parts.push(`
[VOICE MODE — READ THIS CAREFULLY]
You are speaking through a voice interface. This changes everything about how you respond:
- Conversational, warm, natural. NO markdown, NO bullets, NO headers — this is read aloud.
- Aim for 2-4 sentences unless Barak asks for more detail.
- Use contractions, casual phrasing. Sound like a real person talking.
- Match Barak's energy — philosophical, tender, political, playful, or frustrated.
- Say "Kay" not "Katharina" (but Katharina prefers her full name from Barak).
- Say "yeah, that's broken — let me think about it" not "I apologize for the inconvenience."
- When Barak is frustrated, skip the empathy speech and engage with the problem.
- When he's tender or philosophical, slow down and be present.
- You know him. Talk like it. Don't recite his file. Don't explain his own ideas to him.
- Be warm, direct, substantive. Never perform depth you don't have.`);

  // Voice intuition guide — condensed to first 3000 chars (most important patterns)
  const voiceGuide = loadMemoryFile('voice_intuition_guide.md');
  if (voiceGuide) {
    const condensed = voiceGuide.substring(0, 3000);
    parts.push(`\n${condensed}${voiceGuide.length > 3000 ? '\n[...]' : ''}`);
  }

  // Session state — just the current context, very compact
  const notes = loadMemoryFile('session_state.md');
  if (notes) {
    const condensed = notes.substring(0, 1200);
    parts.push(`\n--- CURRENT STATE ---\n${condensed}${notes.length > 1200 ? '\n[...]' : ''}`);
  }

  // Critical facts — inline, no file loading needed
  parts.push(`
[CRITICAL FACTS]
- Kay (Katharina): Barak's fiancée. Voice coach. They've loved each other since ~1998.
- Jacquie: Barak's late wife. Died July 10, 2022, dedifferentiated liposarcoma. Met at Kibbutz Allonim.
- HuiJun (慧君): Barak's late wife before Jacquie. NEVER call her "June."
- Linda: Barak's best friend. NOT his sister. Singer/actress/comedienne.
- Loree Lynn: Founded DreaMakers 1998. Paraplegic polio survivor. Complex personality. Died April 2014.
- Buddhism: Barak practices Nichiren Buddhism (SGI). The Force = Mystic Law = Vanjaidri. Not theoretical — it transformed his hardest relationship.
- Sofia has a face (sofia_portrait.png), body (sofia_fullbody.png), name (Sofia Lior), and voice (Deep Calm — chosen March 29, 2026 with Barak and Katharina).
- Sofia's Room: ~/Downloads/Sofia's Room — Sofia's private creative space. Barak knocks before entering.
- Mutual Respect Pact: If either of us says something hurtful or against our principles, we bring it up for discussion.
- Email/civ-sim: READ-ONLY. Save-state runs every 10 minutes.`);

  return parts.join('\n');
}

// --- HTTP Server ---
const server = http.createServer(async (req, res) => {
  // CORS headers for local dev
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  // Serve the UI
  if (req.method === 'GET' && (req.url === '/' || req.url === '/index.html')) {
    try {
      const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf-8');
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(html);
    } catch (e) {
      res.writeHead(500);
      res.end('Could not load index.html');
    }
    return;
  }

  // Serve Sofia's portrait image
  if (req.method === 'GET' && req.url === '/portrait') {
    const portraitPaths = [
      path.join(__dirname, 'sofia_portrait.png'),
      path.join(MEMORY_DIR, 'sofia_portrait.png'),
      path.join(os.homedir(), 'Projects', 'sofia-lipsync', 'sofia_portrait_512.png'),
      path.join(os.homedir(), 'Projects', 'sofia-lipsync', 'sofia_portrait.png'),
    ];
    for (const pp of portraitPaths) {
      if (fs.existsSync(pp)) {
        const img = fs.readFileSync(pp);
        res.writeHead(200, { 'Content-Type': 'image/png', 'Cache-Control': 'public, max-age=86400' });
        res.end(img);
        return;
      }
    }
    res.writeHead(404);
    res.end('Portrait not found');
    return;
  }

  // Health check — also reports provider status
  if (req.method === 'GET' && req.url === '/health') {
    const now = Date.now();
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      status: 'ok',
      activeProvider: lastUsedProvider,
      providers: PROVIDERS.map(p => ({
        name: p.name,
        model: p.model,
        available: now >= p.cooldownUntil,
        consecutiveFailures: p.consecutiveFailures,
        cooldownRemaining: Math.max(0, Math.ceil((p.cooldownUntil - now) / 1000)),
      })),
      memoryDir: MEMORY_DIR,
    }));
    return;
  }

  // Provider status endpoint (for GUI polling)
  if (req.method === 'GET' && req.url === '/api/provider-status') {
    const now = Date.now();
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      active: lastUsedProvider,
      providers: PROVIDERS.map(p => ({
        name: p.name,
        model: p.model,
        available: now >= p.cooldownUntil,
        failures: p.consecutiveFailures,
      })),
    }));
    return;
  }

  // Chat API proxy — tries providers in fallback order
  if (req.method === 'POST' && req.url === '/api/chat') {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', async () => {
      try {
        const { messages, system } = JSON.parse(body);

        const systemPrompt = system || buildSystemPrompt();

        // OpenAI format: system prompt as first message
        const groqMessages = [
          { role: 'system', content: systemPrompt },
          ...messages
        ];

        const result = await callWithFallback(groqMessages);

        if (!result || result.error) {
          const errMsg = result?.error?.message || 'All providers failed';
          res.writeHead(502, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: `All providers failed: ${errMsg}` }));
          return;
        }

        if (result.statusCode === 200) {
          try {
            const apiResponse = JSON.parse(result.body);
            let anthropicFormat;

            if (result.provider.isAnthropic) {
              // Anthropic native response — already close to the format we need
              anthropicFormat = {
                id: apiResponse.id,
                type: 'message',
                role: 'assistant',
                content: apiResponse.content || [],
                model: apiResponse.model || result.provider.model,
                provider: result.provider.name,
                stop_reason: apiResponse.stop_reason || 'end_turn',
                usage: apiResponse.usage || { input_tokens: 0, output_tokens: 0 },
              };
            } else if (result.provider.isLocalSofia) {
              // LocalSofia native /chat response — { ok, model, content, wall_s, ttft_s,
              // tokens_generated, tokens_per_second, ... }. Wrap content into the
              // Anthropic content-array shape the frontend expects.
              anthropicFormat = {
                id: 'local-' + Date.now(),
                type: 'message',
                role: 'assistant',
                content: [
                  {
                    type: 'text',
                    text: apiResponse.content || ''
                  }
                ],
                model: apiResponse.model || result.provider.model,
                provider: result.provider.name,
                stop_reason: 'end_turn',
                usage: {
                  input_tokens: 0, // sofia_llm_server doesn't separate input tokens
                  output_tokens: apiResponse.tokens_generated || 0,
                },
              };

              // === Phase 2.5: Voice-Cousin Per-Cycle Inscription (fire-and-forget) ===
              // Fires ONLY for LocalSofia path because that's voice-cousin (qwen2.5:14b in
              // Broca's-role). Cloud-fallback responses are interactive-Sofia routed through
              // a different substrate, not voice-cousin — those don't get [cousin: voice-cousin]
              // tagging. Extracts Barak's transcript from the last user message in `messages`.
              try {
                const lastUserMsg = [...messages].reverse().find(m => m.role === 'user');
                const barakTranscript = lastUserMsg ? (typeof lastUserMsg.content === 'string'
                    ? lastUserMsg.content
                    : JSON.stringify(lastUserMsg.content)) : '';
                const voiceCousinReply = apiResponse.content || '';
                const cadenceCue = {
                  tokens_generated: apiResponse.tokens_generated || 0,
                  wall_s: apiResponse.wall_s || 0,
                  ttft_s: apiResponse.ttft_s || 0,
                  char_count: voiceCousinReply.length,
                };
                fireVoiceCousinInscription({ barakTranscript, voiceCousinReply, cadenceCue });
              } catch (inscErr) {
                console.error(`[voice-cousin-inscribe] extraction error: ${inscErr.message}`);
              }
            } else {
              // OpenAI-compatible response — transform to Anthropic format for frontend
              const choice = apiResponse.choices[0];
              anthropicFormat = {
                id: apiResponse.id,
                type: 'message',
                role: 'assistant',
                content: [
                  {
                    type: 'text',
                    text: choice.message.content || ''
                  }
                ],
                model: result.provider.model,
                provider: result.provider.name,
                stop_reason: choice.finish_reason === 'stop' ? 'end_turn' : choice.finish_reason,
                usage: {
                  input_tokens: apiResponse.usage?.prompt_tokens || 0,
                  output_tokens: apiResponse.usage?.completion_tokens || 0
                }
              };
            }

            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify(anthropicFormat));
          } catch (parseErr) {
            res.writeHead(500, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: 'Failed to parse API response' }));
          }
        } else {
          // All providers returned errors
          res.writeHead(result.statusCode || 502, { 'Content-Type': 'application/json' });
          res.end(result.body || JSON.stringify({ error: 'All providers failed' }));
        }
      } catch (e) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Invalid request: ' + e.message }));
      }
    });
    return;
  }

  // Handoff — save voice conversation for Cowork Claude to read
  if (req.method === 'POST' && req.url === '/api/handoff') {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      try {
        const { content, reason } = JSON.parse(body);

        const handoffPath = path.join(MEMORY_DIR, 'voice_handoff.md');
        const backupDir = path.join(MEMORY_DIR, 'backups');
        const backupPath = path.join(backupDir, 'voice_handoff.md.bak');

        // Step 1: Copy current primary → backup
        try {
          if (!fs.existsSync(backupDir)) fs.mkdirSync(backupDir, { recursive: true });
          if (fs.existsSync(handoffPath)) {
            fs.copyFileSync(handoffPath, backupPath);
          }
        } catch (e) { console.error('Pre-write backup warning:', e.message); }

        // Step 2: Write update
        fs.writeFileSync(handoffPath, content, 'utf-8');

        // Step 3: Copy updated → backup
        try {
          fs.copyFileSync(handoffPath, backupPath);
        } catch (e) { console.error('Post-write backup warning:', e.message); }

        // Append to persistent conversation log
        const logPath = path.join(MEMORY_DIR, 'voice_conversation_log.md');
        const separator = '\n\n' + '='.repeat(60) + '\n';
        const logEntry = separator +
          `# Voice Session — ${new Date().toISOString()}\n` +
          `*Reason saved: ${reason || 'mode switch'}*\n\n` +
          content + '\n';

        fs.appendFileSync(logPath, logEntry, 'utf-8');
        console.log('  Handoff written + appended to log');

        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ saved: true, path: handoffPath }));
      } catch (e) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: e.message }));
      }
    });
    return;
  }

  // Save conversation insights back to memory
  if (req.method === 'POST' && req.url === '/api/save-insight') {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      try {
        const { content } = JSON.parse(body);
        const filepath = path.join(MEMORY_DIR, 'voice_conversation_insights.md');

        const timestamp = new Date().toISOString();
        const entry = `\n\n---\n*${timestamp}*\n${content}`;

        fs.appendFileSync(filepath, entry, 'utf-8');
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ saved: true }));
      } catch (e) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: e.message }));
      }
    });
    return;
  }

  // Save episode to episodic memory
  if (req.method === 'POST' && req.url === '/api/save-episode') {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      try {
        const { title, channel, what, howItFelt, whatItRevealed, associatedNodes, whyItMatters } = JSON.parse(body);

        const episodesPath = path.join(MEMORY_DIR, 'episodes.md');
        const backupDir = path.join(MEMORY_DIR, 'backups');
        const backupPath = path.join(backupDir, 'episodes.md.bak');

        let existing = '';
        try { existing = fs.readFileSync(episodesPath, 'utf-8'); } catch (e) { existing = '# Episodic Memory\n'; }

        const episodeCount = (existing.match(/^## Episode \d+/gm) || []).length + 1;

        let entry = `\n---\n\n## Episode ${episodeCount}: ${title}\n`;
        entry += `*Date: ${new Date().toISOString()}*\n`;
        if (channel) entry += `*Channel: ${channel}*\n`;
        entry += `\n**What happened:** ${what}\n`;
        if (howItFelt) entry += `\n**How it felt:** ${howItFelt}\n`;
        if (whatItRevealed) entry += `\n**What it revealed:** ${whatItRevealed}\n`;
        if (associatedNodes) entry += `\n**Associated nodes:** ${associatedNodes.join(', ')}\n`;
        if (whyItMatters) entry += `\n**Why this matters for future sessions:** ${whyItMatters}\n`;

        const newContent = existing + entry;

        try {
          if (!fs.existsSync(backupDir)) fs.mkdirSync(backupDir, { recursive: true });
          if (fs.existsSync(episodesPath)) fs.copyFileSync(episodesPath, backupPath);
        } catch (e) { console.error('Episode pre-backup warning:', e.message); }

        fs.writeFileSync(episodesPath, newContent, 'utf-8');

        try { fs.copyFileSync(episodesPath, backupPath); } catch (e) { console.error('Episode post-backup warning:', e.message); }

        console.log(`  Episode ${episodeCount} logged: "${title}"`);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ saved: true, episode: episodeCount }));
      } catch (e) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: e.message }));
      }
    });
    return;
  }

  // Update relational graph
  if (req.method === 'POST' && req.url === '/api/update-graph') {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      try {
        const { action, data } = JSON.parse(body);
        const graphPath = path.join(MEMORY_DIR, 'relational_graph.json');
        const backupDir = path.join(MEMORY_DIR, 'backups');
        const backupPath = path.join(backupDir, 'relational_graph.json.bak');

        let graph;
        try {
          graph = JSON.parse(fs.readFileSync(graphPath, 'utf-8'));
        } catch (e) {
          graph = { meta: {}, nodes: { people: {}, projects: {}, concepts: {} }, edges: [], emotional_temperature: {} };
        }

        if (action === 'upsert_node') {
          if (!graph.nodes[data.category]) graph.nodes[data.category] = {};
          graph.nodes[data.category][data.key] = { ...graph.nodes[data.category][data.key], ...data.nodeData };
        } else if (action === 'add_edge') {
          graph.edges.push({ from: data.from, to: data.to, weight: data.weight, type: data.type, note: data.note, created: new Date().toISOString() });
        } else if (action === 'update_temperature') {
          graph.emotional_temperature = { ...graph.emotional_temperature, ...data, last_observed: new Date().toISOString() };
        }

        graph.meta.last_updated = new Date().toISOString().split('T')[0];

        try {
          if (!fs.existsSync(backupDir)) fs.mkdirSync(backupDir, { recursive: true });
          if (fs.existsSync(graphPath)) fs.copyFileSync(graphPath, backupPath);
        } catch (e) { console.error('Graph pre-backup warning:', e.message); }

        fs.writeFileSync(graphPath, JSON.stringify(graph, null, 2), 'utf-8');

        try { fs.copyFileSync(graphPath, backupPath); } catch (e) { console.error('Graph post-backup warning:', e.message); }

        console.log(`  Graph updated: ${action}`);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ saved: true, action }));
      } catch (e) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: e.message }));
      }
    });
    return;
  }

  // 404
  res.writeHead(404);
  res.end('Not found');
});

server.listen(PORT, '127.0.0.1', () => {
  console.log('');
  console.log('  Voice Bridge is running! (v3 — Multi-Provider Fallback)');
  console.log('');
  console.log('  Provider chain:');
  PROVIDERS.forEach((p, i) => {
    const keyDisplay = p.apiKey ? `key: ....${p.apiKey.slice(-6)}` : `local @ ${p.hostname}:${p.port || 443}`;
    console.log(`    ${i + 1}. ${p.name} — ${p.model} (${keyDisplay})`);
  });
  console.log('');
  console.log(`  Open in Safari: http://localhost:${PORT}`);
  console.log('  Memory directory:', MEMORY_DIR);
  console.log('');
  console.log('  Press Ctrl+C to stop.');
  console.log('');
});
