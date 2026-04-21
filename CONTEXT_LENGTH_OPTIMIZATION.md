# JFYI Optimization Guide: Strategies for Context Efficiency

When scaling an agentic system with Model Context Protocol (MCP) servers, simply relying on massive context windows (e.g., 1M+ tokens) is an anti-pattern. Research shows that as context grows, models suffer from **Context Rot**, where accuracy can drop by over 30% when relevant information is buried in the middle of a prompt [1, 2]. The true ceiling is the **Maximum Effective Context Window (MECW)**, which is often far below the advertised limit [1, 3].

To ensure JFYI remains a "zero-cost" background profiler that enhances—rather than degrades—the primary agent's reasoning, implement the following context efficiency strategies.

## 1. Dynamic Tool & Instruction Exposure
MCP servers inherently expose all their tools and schemas upfront, which can consume 40-50% of the available context before the agent even begins a task [4-6]. 

*   **Instruction-Tool Retrieval (ITR):** Instead of injecting the entire JFYI profile and all optimization rules into the system prompt, use ITR. This acts as a semantic router that retrieves only the minimal system-prompt fragments and the smallest necessary subset of tools for the specific operational step [7, 8]. This dynamic composition can reduce per-step context tokens by up to 95% [9-11].
*   **Progressive Disclosure:** Expose only a single, lightweight "router" or "meta-tool" (e.g., `list_optimizations`) initially. Expand full schemas only when the agent explicitly decides it needs them [12-15].

## 2. Payload Minification (JSON & TOON)
When JFYI passes profile data or historical developer feedback to the agent, the data serialization format drastically impacts token consumption.

*   **Optimize JSON payloads:** 
    *   **Strip formatting:** Remove whitespace and indentation (`JSON.stringify(data, null, 0)`) [16].
    *   **Shorten identifiers:** Replace 36-character UUIDs with short, mapped IDs (e.g., `u-1`, `p-2`) [17].
    *   **Compact keys & drop nulls:** Use abbreviated key names (e.g., `desc` instead of `description`) and omit keys that contain null or empty values [18]. Flatten nested structures where the hierarchy carries no semantic meaning [19].
*   **Adopt TOON (Token-Optimized Object Notation):** Consider replacing JSON entirely with TOON for LLM interactions. TOON relies on whitespace and indentation rather than heavy syntax (like brackets and quotes), potentially reducing token syntax overhead by ~40-60% [20-22].

## 3. The "Compiled View" Memory Architecture
Do not treat the context window like a storage drive. Treat it as RAM (expensive, volatile, size-limited), while the local JFYI database acts as the hard drive (cheap, vast, requires retrieval) [23, 24].

*   **Externalize Large State (Artifacts):** Never inject massive raw files or raw logs (e.g., a 10,000-token crash log) directly into the history. Offload heavy data to the local disk and pass a lightweight "handle" or file path to the agent [25-27].
*   **Code-Based Execution:** If JFYI needs the agent to analyze a massive local log to update a profile, use a code execution pattern. Allow the agent to write a small script to filter or aggregate the log locally, returning only a 5-line summary to the context window rather than the entire 10,000-line file [28-31].

## 4. Context Compaction and Caching
For long-running coding sessions, the context window will inevitably fill up. 

*   **Recursive Compaction (Summary-Chaining):** Implement an asynchronous background process that summarizes older session events when the context hits a specific capacity threshold (e.g., 80% or 95%). Replace the raw events in the history with these compact summaries [32-35].
*   **Optimize for Prefix Caching:** Modern LLMs utilize Key-Value (KV) caching to reuse attention computations across turns [36]. Structure your dynamic system prompt so that stable instructions (core JFYI profile rules) remain strictly at the *beginning* of the prompt (the stable prefix), pushing highly dynamic content (recent tool outputs) toward the end [36, 37]. This prevents the cache from being invalidated and significantly lowers latency and token costs.
