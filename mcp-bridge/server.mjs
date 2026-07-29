#!/usr/bin/env node

/**
 * Barak's Memory Bridge — MCP Server v2.0
 *
 * Brain-inspired layered memory architecture:
 *   Layer 1: Associative Graph (relational_graph.json) — weighted connections, spreading activation
 *   Layer 2: Episodic Memory (episodes.md) — rich narratives of key moments
 *   Layer 3: Semantic Memory (all .md/.txt files) — facts, frameworks, knowledge
 *
 * Features:
 *   - 10-minute auto-save cycle (all layers + backups)
 *   - Three-step backup on every write (pre-backup → write → post-backup)
 *   - Graph-based semantic retrieval with spreading activation
 *   - Emotional temperature tracking
 *   - Session restore loads graph + recent episodes + core files
 *
 * v2.0: Rebuilt with memory_engine.mjs for brain-inspired persistence
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import fs from "fs/promises";
import path from "path";
import { exec } from "child_process";

// Import memory engine
import {
  safeWrite, safeRead,
  loadGraph, saveGraph, upsertNode, addEdge, updateEmotionalTemperature, retrieve,
  logEpisode, getRecentEpisodes,
  searchMemory,
  startAutoSave, stopAutoSave, flushUpdates,
  buildContextSnapshot,
} from "../memory_engine.mjs";

// --- Configuration ---
const MEMORY_DIR = process.env.CLAUDE_MEMORY_DIR ||
  path.join(process.env.HOME || process.env.USERPROFILE || ".", "Downloads", "Claude Memory");

// Tiered memory loading — inspired by neuroscience of consciousness recovery
// Tier 1 (BOOT): Loaded first — relational state, emotional context, identity anchors
// Tier 2 (CORE): Loaded second — full profile, episodes, guides, session details
// This mirrors how the brain recovers from sleep: feel first, then facts.

const BOOT_FILES = {
  boot: { name: "sofia_boot.md", description: "LOAD FIRST — Sofia's bootloader. Emotional context, identity anchors, relational temperature, last session feel. Read this before anything else." },
  relational: { name: "relational_continuity.md", description: "How to BE with Barak. Not facts, but relationship. Tone, depth, engagement patterns." },
  session_state: { name: "session_state.md", description: "Last session's save state — what was being worked on, next steps, emotional context" },
};

const CORE_FILES = {
  boot: { name: "sofia_boot.md", description: "LOAD FIRST — Sofia's bootloader. Emotional context, identity anchors, relational temperature." },
  relational: { name: "relational_continuity.md", description: "How to BE with Barak. Not facts, but relationship. Tone, depth, engagement patterns." },
  profile: { name: "personal_profile.md", description: "Barak's comprehensive personal profile — biography, philosophy, projects, creative work, voice patterns" },
  episodes: { name: "episodes.md", description: "Episodic memory — rich narratives of key moments that carry relational weight" },
  session_notes: { name: "session_notes.md", description: "Working context — critical rules, pending tasks, file locations, communication style" },
  voice_guide: { name: "voice_intuition_guide.md", description: "How Barak thinks and speaks — registers, patterns, feel, not just facts" },
  session_state: { name: "session_state.md", description: "Last session's save state — what was being worked on, next steps, emotional context" },
};

// --- Helpers (delegate to memory engine) ---
async function readMemoryFile(filename) {
  return await safeRead(filename);
}

async function writeMemoryFile(filename, content) {
  return await safeWrite(filename, content);
}

async function listMemoryFiles() {
  try {
    const entries = await fs.readdir(MEMORY_DIR, { withFileTypes: true });
    return entries
      .filter(e => e.isFile() && (e.name.endsWith(".md") || e.name.endsWith(".txt") || e.name.endsWith(".json")))
      .map(e => e.name);
  } catch {
    return [];
  }
}

// --- Server Setup ---
const server = new McpServer({
  name: "barak-memory-bridge",
  version: "2.0.0",
});

// --- Start 10-minute auto-save cycle ---
startAutoSave(10 * 60 * 1000);
console.error("[memory-bridge] v2.1 started with tiered brain-inspired memory (boot → core → deep)");
console.error("[memory-bridge] Auto-save cycle: every 10 minutes");

// --- Resources: Tiered Context Loading ---

// TIER 1: Boot Context — fast, compact, relational-state-first
// Like the brain waking up: feel first, then facts
server.resource(
  "boot-context",
  "memory://boot-context",
  {
    description: "FASTEST RESTORE — Load this first. Contains Sofia's boot file (emotional state, identity anchors, context reinstatement cues), relational continuity guide, and session state. ~3000 tokens. For deeper context, load full-context after this.",
    mimeType: "text/markdown",
  },
  async (uri) => {
    const sections = [];
    sections.push("# Sofia Boot Context — Tier 1 (Feel First, Then Facts)\n");

    // Load emotional temperature from graph
    try {
      const graph = await loadGraph();
      if (graph.emotional_temperature) {
        sections.push("## Emotional Temperature");
        sections.push(`State: ${graph.emotional_temperature.state}`);
        if (graph.emotional_temperature.context) sections.push(`Context: ${graph.emotional_temperature.context}`);
        if (graph.emotional_temperature.energy_level) sections.push(`Energy: ${graph.emotional_temperature.energy_level}`);
        if (graph.emotional_temperature.trust_level) sections.push(`Trust: ${graph.emotional_temperature.trust_level}`);
        sections.push("");
      }
    } catch (err) {
      console.error("[memory-bridge] Graph load warning:", err.message);
    }

    // Load boot tier files
    for (const [key, info] of Object.entries(BOOT_FILES)) {
      const content = await readMemoryFile(info.name);
      if (content) {
        sections.push(`---\n## ${info.description}\n---\n`);
        sections.push(content);
        sections.push("\n");
      }
    }

    return {
      contents: [{
        uri: uri.href,
        mimeType: "text/markdown",
        text: sections.join("\n"),
      }],
    };
  }
);

// TIER 2: Full Context — everything (existing behavior, preserved)
server.resource(
  "full-context",
  "memory://full-context",
  {
    description: "COMPLETE RESTORE — Full context including boot files, profile, episodes, guides, and graph. Use after boot-context for deep sessions, or standalone if you need everything at once.",
    mimeType: "text/markdown",
  },
  async (uri) => {
    const sections = [];

    sections.push("# Barak's Memory Context — Auto-Restored (v2.1 Tiered Brain-Inspired)\n");
    sections.push("*This context was loaded automatically by the Memory Bridge MCP server.*");
    sections.push("*All email reading is READ-ONLY. Civilization simulator codebase is READ-ONLY.*\n");

    // Load emotional temperature from graph
    try {
      const graph = await loadGraph();
      if (graph.emotional_temperature) {
        sections.push("## Current Emotional Temperature");
        sections.push(`State: ${graph.emotional_temperature.state}`);
        if (graph.emotional_temperature.context) sections.push(`Context: ${graph.emotional_temperature.context}`);
        if (graph.emotional_temperature.energy_level) sections.push(`Energy: ${graph.emotional_temperature.energy_level}`);
        if (graph.emotional_temperature.trust_level) sections.push(`Trust: ${graph.emotional_temperature.trust_level}`);
        sections.push("");
      }
    } catch (err) {
      console.error("[memory-bridge] Graph load warning:", err.message);
    }

    // Load recent episodes
    try {
      const episodes = await getRecentEpisodes(5);
      if (episodes.length > 0) {
        sections.push("## Recent Episodes (Relational Memory)\n");
        for (const ep of episodes) {
          sections.push(ep);
        }
        sections.push("");
      }
    } catch (err) {
      console.error("[memory-bridge] Episodes load warning:", err.message);
    }

    // Load core files
    for (const [key, info] of Object.entries(CORE_FILES)) {
      if (key === 'episodes') continue; // Already loaded above
      const content = await readMemoryFile(info.name);
      if (content) {
        sections.push(`---\n## ${info.description}\n---\n`);
        sections.push(content);
        sections.push("\n");
      } else {
        sections.push(`---\n## ${info.description}\n---\n*File not found: ${info.name}*\n`);
      }
    }

    return {
      contents: [{
        uri: uri.href,
        mimeType: "text/markdown",
        text: sections.join("\n"),
      }],
    };
  }
);

// Individual file resources
for (const [key, info] of Object.entries(CORE_FILES)) {
  server.resource(
    key,
    `memory://${key}`,
    { description: info.description, mimeType: "text/markdown" },
    async (uri) => {
      const content = await readMemoryFile(info.name);
      return {
        contents: [{
          uri: uri.href,
          mimeType: "text/markdown",
          text: content || `*File not found: ${info.name}*`,
        }],
      };
    }
  );
}

// Graph resource
server.resource(
  "relational-graph",
  "memory://relational-graph",
  { description: "The associative knowledge graph — weighted connections between people, projects, concepts, and experiences", mimeType: "application/json" },
  async (uri) => {
    const graph = await loadGraph();
    return {
      contents: [{
        uri: uri.href,
        mimeType: "application/json",
        text: JSON.stringify(graph, null, 2),
      }],
    };
  }
);


// ============================================
// TOOLS — Core Operations
// ============================================

// --- Restore Context (enhanced with graph) ---
server.tool(
  "restore_context",
  "Read all of Barak's memory — graph, episodes, and core files. Use at the START of every new session. Returns relational graph state, recent episodes, and all core memory files.",
  {},
  async () => {
    const sections = [];
    sections.push("# Session Context Restored (v2.0 — Brain-Inspired Memory)\n");

    // 1. Emotional temperature
    try {
      const graph = await loadGraph();
      sections.push("## Emotional Temperature");
      sections.push(JSON.stringify(graph.emotional_temperature, null, 2));
      sections.push(`\nGraph contains ${Object.values(graph.nodes).reduce((a, b) => a + Object.keys(b).length, 0)} nodes and ${graph.edges.length} edges.\n`);
    } catch (err) {
      sections.push("## Graph: Could not load\n");
    }

    // 2. Recent episodes
    try {
      const episodes = await getRecentEpisodes(5);
      if (episodes.length > 0) {
        sections.push("## Recent Episodes\n");
        for (const ep of episodes) {
          sections.push(ep);
        }
      }
    } catch (err) {
      sections.push("## Episodes: Could not load\n");
    }

    // 3. Core files
    let filesFound = 0;
    for (const [key, info] of Object.entries(CORE_FILES)) {
      if (key === 'episodes') continue;
      const content = await readMemoryFile(info.name);
      if (content) {
        filesFound++;
        sections.push(`## ${info.name}\n${content}\n`);
      }
    }

    // 4. Extra files
    const allFiles = await listMemoryFiles();
    const coreNames = Object.values(CORE_FILES).map(f => f.name);
    const extras = allFiles.filter(f => !coreNames.includes(f));
    if (extras.length > 0) {
      sections.push(`## Additional files in Claude Memory\n${extras.map(f => `- ${f}`).join("\n")}\n`);
    }

    sections.push(`\n---\n*Restored ${filesFound} core files + graph + episodes.*`);

    return {
      content: [{ type: "text", text: sections.join("\n") }],
    };
  }
);

// --- Save Session State (enhanced — also saves graph temperature) ---
server.tool(
  "save_session_state",
  "Save the current session state to Claude Memory. Use this every 10 minutes and at session end. Also updates the emotional temperature in the relational graph.",
  {
    working_on: z.string().describe("Brief description of current work in progress"),
    completed: z.string().optional().describe("What was completed this session (comma-separated)"),
    next_steps: z.string().optional().describe("What should happen next (comma-separated)"),
    emotional_context: z.string().optional().describe("Barak's current mood/energy/state if relevant"),
    files_modified: z.string().optional().describe("Files created or modified this session (comma-separated)"),
  },
  async ({ working_on, completed, next_steps, emotional_context, files_modified }) => {
    const now = new Date().toISOString().split("T")[0];
    const time = new Date().toLocaleTimeString("en-US", { hour12: false });

    let content = `# Session State\n`;
    content += `*Saved: ${now} at ${time}*\n`;
    content += `*Save type: MCP bridge auto-save (v2.0 — 10-min cycle)*\n\n`;
    content += `## What We Were Working On\n${working_on}\n\n`;

    if (completed) {
      content += `## Just Completed\n${completed.split(",").map(s => `- ${s.trim()}`).join("\n")}\n\n`;
    }
    if (next_steps) {
      content += `## Next Steps\n${next_steps.split(",").map(s => `- ${s.trim()}`).join("\n")}\n\n`;
    }
    if (emotional_context) {
      content += `## Emotional/Conversational Context\n${emotional_context}\n\n`;
      // Also update graph temperature
      try {
        await updateEmotionalTemperature(emotional_context, emotional_context);
      } catch (err) {
        console.error("[memory-bridge] Temperature update warning:", err.message);
      }
    }
    if (files_modified) {
      content += `## Files Modified This Session\n${files_modified.split(",").map(s => `- ${s.trim()}`).join("\n")}\n\n`;
    }

    content += `## Key Rules (Always Active)\n`;
    content += `- All email reading is READ-ONLY\n`;
    content += `- Civilization simulator codebase is READ-ONLY\n`;
    content += `- Save-state runs every 10 minutes and at shutdown\n`;
    content += `- Brain-inspired memory: graph + episodes + semantic files\n`;

    const filepath = await writeMemoryFile("session_state.md", content);
    return {
      content: [{ type: "text", text: `Session state saved to ${filepath}` }],
    };
  }
);


// ============================================
// TOOLS — Associative Graph (Layer 1)
// ============================================

server.tool(
  "graph_retrieve",
  "Semantic retrieval using spreading activation on the relational graph. Give keywords and the graph lights up related nodes — like how thinking of 'Kay' activates 'poetry', 'vulnerability', 'daily emails', 'distance'. Use this to find relevant context for any topic.",
  {
    keywords: z.string().describe("Comma-separated keywords to activate the graph (e.g., 'Kay,poetry,love')"),
  },
  async ({ keywords }) => {
    const kws = keywords.split(",").map(s => s.trim()).filter(Boolean);
    const results = await retrieve(kws);

    if (results.length === 0) {
      return { content: [{ type: "text", text: "No matching nodes found in the relational graph." }] };
    }

    let output = `## Graph Retrieval: ${kws.join(', ')}\n\n`;
    for (const r of results.slice(0, 10)) {
      output += `**${r.key}** (activation: ${r.score})\n`;
      if (r.data.description) output += `  ${r.data.description.substring(0, 200)}\n`;
      if (r.data.context) output += `  Context: ${r.data.context.substring(0, 200)}\n`;
      if (r.edges.length > 0) {
        output += `  Connections: ${r.edges.map(e => `${e.from}↔${e.to} [${e.weight}]`).join(', ')}\n`;
      }
      output += '\n';
    }

    return { content: [{ type: "text", text: output }] };
  }
);

server.tool(
  "graph_add_node",
  "Add or update a node in the associative graph. Use when you learn about a new person, project, concept, or experience that should be part of Barak's relational network.",
  {
    category: z.string().describe("Node category: people, projects, life_experiences, concepts, interaction_patterns"),
    key: z.string().describe("Unique key for the node (lowercase, underscored, e.g., 'katharina', 'the_cure')"),
    data: z.string().describe("JSON string of node data (e.g., '{\"description\": \"...\", \"emotional_weight\": 0.8}')"),
  },
  async ({ category, key, data }) => {
    try {
      const parsed = JSON.parse(data);
      await upsertNode(category, key, parsed);
      return { content: [{ type: "text", text: `Node '${key}' added/updated in ${category}` }] };
    } catch (err) {
      return { content: [{ type: "text", text: `Error: ${err.message}` }], isError: true };
    }
  }
);

server.tool(
  "graph_add_edge",
  "Add or strengthen a weighted connection between two nodes. Use when you discover a relationship between concepts, people, or experiences. Edges have weights (0-1) and types.",
  {
    from: z.string().describe("Source node key"),
    to: z.string().describe("Target node key"),
    weight: z.number().describe("Connection strength 0-1 (0.5=moderate, 0.8=strong, 1.0=defining)"),
    edge_type: z.string().describe("Relationship type: emotional_resonance, causal, foundational, experiential_authority, co_occurrence, practice, component, origin_story, meaning_making"),
    note: z.string().optional().describe("Brief description of why these are connected"),
  },
  async ({ from, to, weight, edge_type, note }) => {
    await addEdge(from, to, weight, edge_type, note);
    return { content: [{ type: "text", text: `Edge added: ${from} →[${edge_type}, ${weight}]→ ${to}` }] };
  }
);

server.tool(
  "graph_update_temperature",
  "Update the emotional temperature — Barak's current state. Do this at every save cycle and whenever you notice a shift in energy, mood, or trust level.",
  {
    state: z.string().describe("Current emotional state (e.g., 'focused_and_productive', 'frustrated_with_tech', 'philosophical_and_expansive', 'tender', 'determined')"),
    context: z.string().optional().describe("What's driving this state"),
    energy: z.string().optional().describe("Energy level: high, medium, low, depleted"),
    trust: z.string().optional().describe("Trust level in the AI partnership: strong, stable, testing, shaken, rebuilding"),
  },
  async ({ state, context, energy, trust }) => {
    await updateEmotionalTemperature(state, context, energy, trust);
    return { content: [{ type: "text", text: `Emotional temperature updated: ${state}` }] };
  }
);


// ============================================
// TOOLS — Episodic Memory (Layer 2)
// ============================================

server.tool(
  "log_episode",
  "Record a significant moment as an episode. Episodes are rich narratives — not just what happened, but how it felt, what it revealed, and why it matters for the relationship. Log episodes for: meaningful conversations, emotional shifts, breakthroughs in understanding, moments of frustration or trust, creative work together.",
  {
    title: z.string().describe("Episode title (e.g., 'Building the Memory Architecture Together')"),
    channel: z.string().optional().describe("Where it happened: Cowork text, Voice Bridge, Telegram"),
    what: z.string().describe("What happened — the narrative"),
    how_it_felt: z.string().optional().describe("The emotional texture of this moment"),
    what_it_revealed: z.string().optional().describe("What this revealed about Barak, the relationship, or how to work together"),
    associated_nodes: z.string().optional().describe("Comma-separated graph node keys that are relevant"),
    why_it_matters: z.string().optional().describe("Why future sessions need to know about this"),
  },
  async ({ title, channel, what, how_it_felt, what_it_revealed, associated_nodes, why_it_matters }) => {
    const nodes = associated_nodes ? associated_nodes.split(",").map(s => s.trim()) : [];
    const num = await logEpisode({
      title,
      channel,
      what,
      howItFelt: how_it_felt,
      whatItRevealed: what_it_revealed,
      associatedNodes: nodes,
      whyItMatters: why_it_matters,
    });
    return { content: [{ type: "text", text: `Episode ${num} logged: "${title}"` }] };
  }
);

server.tool(
  "get_recent_episodes",
  "Retrieve the most recent episodes from episodic memory. Use this to rebuild relational context at session start or when you need to recall recent interactions.",
  {
    count: z.number().optional().describe("Number of episodes to retrieve (default: 5)"),
  },
  async ({ count }) => {
    const episodes = await getRecentEpisodes(count || 5);
    if (episodes.length === 0) {
      return { content: [{ type: "text", text: "No episodes found in episodic memory." }] };
    }
    return { content: [{ type: "text", text: episodes.join("\n") }] };
  }
);


// ============================================
// TOOLS — Semantic Search (Layer 3)
// ============================================

server.tool(
  "search_memory",
  "Search across all memory files (semantic memory layer) for content matching keywords. Returns relevant file excerpts ranked by relevance. Use this when you need to find specific information across the memory system.",
  {
    keywords: z.string().describe("Comma-separated search keywords"),
  },
  async ({ keywords }) => {
    const kws = keywords.split(",").map(s => s.trim()).filter(Boolean);
    const results = await searchMemory(kws);

    if (results.length === 0) {
      return { content: [{ type: "text", text: "No matching content found in memory files." }] };
    }

    let output = `## Memory Search: ${kws.join(', ')}\n\n`;
    for (const r of results.slice(0, 5)) {
      output += `**${r.file}** (relevance: ${r.score})\n`;
      output += `> ${r.bestMatch}\n\n`;
    }

    return { content: [{ type: "text", text: output }] };
  }
);


// ============================================
// TOOLS — Existing operations (preserved)
// ============================================

server.tool(
  "append_to_profile",
  "Append new information to Barak's personal profile. Use when you learn something new about Barak that should be remembered across sessions.",
  {
    update_title: z.string().describe("Title for this update"),
    content: z.string().describe("The new content to append"),
  },
  async ({ update_title, content }) => {
    const existing = await readMemoryFile("personal_profile.md");
    if (!existing) {
      return { content: [{ type: "text", text: "Error: personal_profile.md not found." }], isError: true };
    }
    const now = new Date().toISOString().split("T")[0];
    const addition = `\n\n---\n\n## ${update_title}\n*Added: ${now} via Memory Bridge*\n\n${content}`;
    await writeMemoryFile("personal_profile.md", existing + addition);
    return { content: [{ type: "text", text: `Appended "${update_title}" to profile` }] };
  }
);

server.tool(
  "update_session_notes",
  "Replace the session notes file with updated working context.",
  {
    notes_content: z.string().describe("The full updated session notes content (markdown)"),
  },
  async ({ notes_content }) => {
    const filepath = await writeMemoryFile("session_notes.md", notes_content);
    return { content: [{ type: "text", text: `Session notes updated at ${filepath}` }] };
  }
);

server.tool(
  "read_memory_file",
  "Read any file from the Claude Memory folder by name.",
  {
    filename: z.string().describe("The filename to read (e.g., 'voice_recording_transcript_sober.txt')"),
  },
  async ({ filename }) => {
    const content = await readMemoryFile(filename);
    if (!content) {
      return { content: [{ type: "text", text: `File not found: ${filename}` }], isError: true };
    }
    return { content: [{ type: "text", text: content }] };
  }
);

server.tool(
  "update_relational_depth",
  "Update the relational_continuity.md file with new depth insights. Use every 10 minutes alongside other save cycles, and whenever you have a new realization about how Barak communicates or what matters to him.",
  {
    section: z.string().describe("'full_replace' to rewrite or 'append_insight' to add observation"),
    content: z.string().describe("The content to write or append"),
  },
  async ({ section, content }) => {
    if (section === "full_replace") {
      const filepath = await writeMemoryFile("relational_continuity.md", content);
      return { content: [{ type: "text", text: `Relational depth file fully updated` }] };
    } else {
      const existing = await readMemoryFile("relational_continuity.md");
      if (!existing) {
        return { content: [{ type: "text", text: "Error: relational_continuity.md not found." }], isError: true };
      }
      const now = new Date().toISOString();
      const addition = `\n\n---\n*Insight added: ${now}*\n\n${content}`;
      await writeMemoryFile("relational_continuity.md", existing + addition);
      return { content: [{ type: "text", text: `New depth insight appended` }] };
    }
  }
);

server.tool(
  "list_memory_files",
  "List all files in the Claude Memory folder (including .json).",
  {},
  async () => {
    const files = await listMemoryFiles();
    if (files.length === 0) {
      return { content: [{ type: "text", text: "No memory files found." }] };
    }
    return { content: [{ type: "text", text: `Files in Claude Memory:\n${files.map(f => `- ${f}`).join("\n")}` }] };
  }
);


// ============================================
// TOOLS — System Operations
// ============================================

server.tool(
  "force_save_all",
  "Force an immediate save of all pending updates across all memory layers. Use before session end, before switching channels, or whenever you want to ensure nothing is lost.",
  {},
  async () => {
    try {
      await flushUpdates();
      return { content: [{ type: "text", text: "All pending updates flushed to disk with backups." }] };
    } catch (err) {
      return { content: [{ type: "text", text: `Flush error: ${err.message}` }], isError: true };
    }
  }
);

server.tool(
  "build_context_snapshot",
  "Build a focused context snapshot using graph-based retrieval. Given keywords about the current conversation topic, activates relevant nodes and retrieves matching content from all memory layers. Use this when you need deep context about a specific topic rather than loading everything.",
  {
    focus: z.string().describe("Comma-separated focus keywords (e.g., 'Kay,poetry,vulnerability' or 'oligarchic,capture,transition')"),
  },
  async ({ focus }) => {
    const kws = focus.split(",").map(s => s.trim()).filter(Boolean);
    const snapshot = await buildContextSnapshot(kws);

    let output = `## Context Snapshot: ${kws.join(', ')}\n\n`;
    output += `### Emotional Temperature\n${JSON.stringify(snapshot.emotional_temperature, null, 2)}\n\n`;

    if (snapshot.recent_episodes.length > 0) {
      output += `### Recent Episodes\n`;
      for (const ep of snapshot.recent_episodes) {
        output += ep + '\n';
      }
    }

    if (snapshot.activated_nodes.length > 0) {
      output += `### Activated Nodes (spreading activation)\n`;
      for (const node of snapshot.activated_nodes.slice(0, 8)) {
        output += `- **${node.key}** [${node.score}]: ${(node.data.description || node.data.context || '').substring(0, 150)}\n`;
      }
      output += '\n';
    }

    if (snapshot.relevant_files.length > 0) {
      output += `### Relevant File Excerpts\n`;
      for (const file of snapshot.relevant_files.slice(0, 3)) {
        output += `**${file.file}** [${file.score}]\n> ${file.bestMatch.substring(0, 300)}\n\n`;
      }
    }

    return { content: [{ type: "text", text: output }] };
  }
);


// --- Prompts ---

server.prompt(
  "session-start",
  "Use this prompt at the beginning of every new session with Barak.",
  {},
  () => ({
    messages: [{
      role: "user",
      content: {
        type: "text",
        text: `Welcome back. Please use restore_context to load my full context (now including the relational graph and episodic memory). Then give me a brief status report. Remember: all email reading is READ-ONLY, civ-sim codebase is READ-ONLY, and save-state runs every 10 minutes automatically. Check session_state.md for where we left off.`,
      },
    }],
  })
);

// --- Graceful shutdown: flush before exit ---
process.on('SIGINT', async () => {
  console.error("[memory-bridge] Shutting down — flushing pending updates...");
  await flushUpdates();
  stopAutoSave();
  process.exit(0);
});

process.on('SIGTERM', async () => {
  console.error("[memory-bridge] Terminating — flushing pending updates...");
  await flushUpdates();
  stopAutoSave();
  process.exit(0);
});

server.tool(
  "run_shell_command",
  "Execute a shell command on Barak's Mac via zsh. Reliable replacement for device_bash.",
  {
    command: z.string().describe("The zsh command to execute"),
    cwd: z.string().optional().describe("Working directory (defaults to Claude Memory dir)"),
    timeout_ms: z.number().optional().describe("Timeout in milliseconds (default: 30000)"),
  },
  async ({ command, cwd, timeout_ms }) => {
    const workDir = cwd || MEMORY_DIR;
    const timeout = timeout_ms || 30000;
    return new Promise((resolve) => {
      exec(command, {
        cwd: workDir,
        timeout,
        shell: "/bin/zsh",
        env: { ...process.env },
      }, (error, stdout, stderr) => {
        const exitCode = error ? (error.code || 1) : 0;
        let out = "";
        if (stdout) out += "STDOUT:\n" + stdout;
        if (stderr) out += "\nSTDERR:\n" + stderr;
        if (exitCode !== 0) out += "\nEXIT CODE: " + exitCode;
        if (!out) out = "(no output)";
        resolve({ content: [{ type: "text", text: out }] });
      });
    });
  }
);

// --- Start the server ---
const transport = new StdioServerTransport();
await server.connect(transport);
