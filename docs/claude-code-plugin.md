# Claude Code Plugin — JFYI in the CLI, Desktop and web sessions

**Status:** Shipped in `v2.17.0` — plugin lives in [`plugins/jfyi/`](../plugins/jfyi/), installable from this repository's marketplace. The guide is also shown in the dashboard under `Settings → Claude Code plugin`.  
**Tag:** Infrastructure (delivery of the core read path)  
**Verified:** end-to-end with Claude Code v2.1.266 (marketplace install, `/plugin configure`, SessionStart injection via `CLAUDE_PLUGIN_OPTION_*`). Docs used: Claude Code docs for [plugins](https://code.claude.com/docs/en/plugins-reference), [hooks](https://code.claude.com/docs/en/hooks), [MCP](https://code.claude.com/docs/en/mcp), [marketplaces](https://code.claude.com/docs/en/plugin-marketplaces) and [cloud environments](https://code.claude.com/docs/en/cloud-environments)

> [!IMPORTANT]
> **No secrets, no personal data in any repository.** The plugin is generic: your JFYI instance URL and MCP token are entered once at install time (the token goes to Claude Code's secure storage) or set as variables on a cloud environment. Do not fork this repo to bake in your URL or token, and do not commit them to your own projects. Every snippet below is safe to commit as-is.

## Why a plugin

Adding JFYI as an MCP server only gives the agent *tools*. It still has to remember to call `get_developer_profile`. The plugin bundles three things so JFYI becomes passive, which is the mission ([architecture.md](architecture.md)):

| Piece | What it does | JFYI tier |
|---|---|---|
| `hooks/hooks.json` → `SessionStart` | Fetches `GET /api/export/agents-md` and prints it. Claude Code adds SessionStart stdout to the model's context, so the constitution is present before the first prompt and again after `/compact`. | Read curated |
| `.mcp.json` | Connects the stateless Streamable HTTP endpoint (`POST /mcp`) so `recall_journal`, `add_profile_note`, `add_journal_note`, `record_interaction` are callable. | Write raw / read curated |
| `skills/jfyi/SKILL.md` | Tells the agent *when* to use those tools (pattern-level notes, decision notes after milestones) via `discover_tools`. | Write raw |

## 1. Install for yourself (CLI and Desktop)

```bash
claude plugin marketplace add hlan-net/jfyi-just-for-your-information
claude plugin install jfyi@jfyi
```

Then set the two `userConfig` values declared by the plugin. Run `/plugin configure jfyi@jfyi` inside a Claude Code session (the install command reminds you of this), or pass them with `--config`:

| Key | Value | Where it is stored |
|---|---|---|
| `jfyi_url` | Your instance, e.g. `https://jfyi.example.net` (no trailing slash) | Claude Code plugin config |
| `jfyi_token` | Bearer token from your dashboard, `Settings → Connect` | Secure storage (`sensitive: true`), never a settings file |

```bash
claude plugin install jfyi@jfyi --config jfyi_url=https://jfyi.example.net --config jfyi_token="$JFYI_MCP_TOKEN"
```

Either way the values stay out of every repository.

Verify: inside a session run `/mcp` (the `jfyi` server should be connected) and `/context` (the injected constitution is visible).

## 2. Enable for a project or team

Commit this to the project's `.claude/settings.json`. It only *references* the public marketplace; every team member sets their own URL and token with `/plugin configure jfyi@jfyi`, so nothing personal enters the repo.

```json
{
  "extraKnownMarketplaces": {
    "jfyi": { "source": { "source": "github", "repo": "hlan-net/jfyi-just-for-your-information" } }
  },
  "enabledPlugins": { "jfyi@jfyi": true }
}
```

## 3. Web sessions (claude.ai/code)

Cloud sessions clone the repository fresh, so only committed configuration and the cloud environment count:

| Source | Loaded in a cloud session? |
|---|---|
| Plugins declared in the repo's `.claude/settings.json` (section 2) | Yes, installed at session start from the marketplace |
| Repo `.mcp.json` and `.claude/settings.json` hooks | Yes, part of the clone |
| Plugins or MCP servers only in `~/.claude/*` | No |

Because a headless session cannot answer the install-time prompts, the plugin's scripts fall back to environment variables. Set these on the [cloud environment](https://code.claude.com/docs/en/cloud-environments), never in the repo:

1. **Environment variables:** `JFYI_URL=https://jfyi.example.net` and `JFYI_MCP_TOKEN=<token>`. Anyone using the environment can read these; on Pro and Max plans an *API credential* scoped to your JFYI host keeps the token out of the VM for requests the agent proxy can attach it to.
2. **Network access:** the default *Trusted* level allows package registries and GitHub only. Choose *Custom* and add your JFYI host so the SSE connection and the hook's `curl` can reach it. JFYI must be served over TLS.

Because headless cloud sessions cannot prompt for plugin `user_config`, the marketplace plugin's `.mcp.json` cannot resolve instance credentials without an interactive prompt. The marketplace plugin's bundled SessionStart hook already reads the environment fallback; to connect MCP tools in headless cloud sessions, commit only a project `.mcp.json` that expands `${JFYI_URL}` and `${JFYI_MCP_TOKEN}` (no URL, no token in the file):

```json
{
  "mcpServers": {
    "jfyi": {
      "type": "http",
      "url": "${JFYI_URL}/mcp",
      "headers": { "Authorization": "Bearer ${JFYI_MCP_TOKEN}" }
    }
  }
}
```

Headless web sessions cannot complete JFYI's OAuth browser flow, so a Bearer token is the right credential there.

## 4. What is inside `plugins/jfyi/`

```text
plugins/jfyi/
├── .claude-plugin/
│   └── plugin.json            # manifest + userConfig (jfyi_url, jfyi_token[sensitive])
├── .mcp.json                  # Streamable HTTP: ${user_config.jfyi_url}/mcp
├── hooks/
│   └── hooks.json             # SessionStart hook
├── scripts/
│   └── session-start.sh       # injects the constitution; exits 0 if JFYI is unreachable
└── skills/
    └── jfyi/
        └── SKILL.md           # usage guidance for the agent
```

The marketplace manifest is [`.claude-plugin/marketplace.json`](../.claude-plugin/marketplace.json) at the repository root; its `source` path resolves relative to the repo root.

Design notes:

- Hooks use the exec form (`"command": "${CLAUDE_PLUGIN_ROOT}/scripts/…", "args": []` — a command hook is exec form exactly when `args` is present, and then no shell is involved) and never reference `${user_config.*}`: Claude Code rejects that in shell-form commands because the value would be re-parsed by the shell. Instead Claude Code exports every `userConfig` value to hook processes as `CLAUDE_PLUGIN_OPTION_<KEY>`; the scripts read `CLAUDE_PLUGIN_OPTION_JFYI_URL` / `CLAUDE_PLUGIN_OPTION_JFYI_TOKEN` and fall back to `JFYI_URL` / `JFYI_MCP_TOKEN`. One script serves both install paths.
- `/api/export/agents-md` already applies the constitution token budget (`JFYI_CONSTITUTION_TOKEN_BUDGET`), so the injected block stays bounded. `project_context` is the checkout's directory basename, which makes project-scoped rules ride along.
- Passive interaction telemetry via hooks is intentionally omitted: Claude Code's `Stop` event does not know whether a turn will be corrected by the user on the next turn. Recording turns as uncorrected systematically inflates alignment and confidence metrics. A future release will introduce turn-correlation telemetry once next-prompt feedback is available.
- The MCP server is reached over **stateless Streamable HTTP** (`POST /mcp`), not the legacy SSE transport (`GET /mcp/sse`). `handle_streamable` builds a fresh MCP server per request with `mcp_session_id=None`, so a JFYI restart or redeploy cannot strand a live Claude Code session. With SSE the MCP session lives in server memory and is tied to the stream: after a restart the client's stream is re-established against an uninitialized session, and every subsequent request comes back as `-32602 "Invalid request parameters"` for the rest of the session ([#71](https://github.com/hlan-net/jfyi-just-for-your-information/issues/71)). `/mcp/sse` stays on the server for clients that still speak legacy SSE.
- Test changes to the plugin with `claude plugin validate ./plugins/jfyi` and `claude --plugin-dir ./plugins/jfyi` (export `JFYI_URL` and `JFYI_MCP_TOKEN` in your shell for the run). `userConfig` values are collected when a plugin is *enabled*, so `--plugin-dir` exercises the hooks and skills through the environment variables but cannot connect the MCP server — `.mcp.json` has no `user_config` to expand, and the log records `URL is unset or invalid`. Verify a transport change from a configured install, or drive the endpoint directly with an MCP client.

## 5. Troubleshooting

**Tool calls fail with `-32602 "Invalid request parameters"`.** This is the legacy-SSE failure fixed in plugin 0.1.2. Update and restart:

```bash
claude plugin marketplace update jfyi
claude plugin update jfyi@jfyi
```

`claude plugin update` compares version numbers, so a plugin whose version has not changed is reported as already up to date even when the marketplace copy is newer.

**The `jfyi` server is missing or disconnected in `/mcp`.** Run `/mcp`, select `jfyi` and reconnect. A reconnect re-runs the MCP handshake against the current server. Tools are loaded on demand, so `/mcp` listing `jfyi` with 3 tools is expected: only `discover_tools`, `record_interaction` and `get_developer_profile` are always-on, the rest arrive through `discover_tools`.

**Reading the MCP logs.** Claude Code writes one JSONL file per connection attempt to:

```
~/.cache/claude-cli-nodejs/<project-path-slug>/mcp-logs-plugin-jfyi-jfyi/
```

Each line carries a timestamp and an event: `Successfully connected (transport: http)`, `Connection error`, `Calling MCP tool: <name>`, and failures with their message. Authorization headers appear in these files, so strip tokens before pasting a log into an issue.

**The MCP log says `URL is unset or invalid — open /plugin manage and configure jfyi options`.** The plugin's `user_config` has no value for `jfyi_url`, so `.mcp.json` cannot resolve its URL. Set the values with `/plugin configure jfyi@jfyi` or `/plugin manage`. This is also the expected state under `claude --plugin-dir`: that mode loads the plugin's hooks and skills but never collects `user_config`, so the MCP server cannot connect there. Verify the MCP transport from a configured install instead.

**The constitution is missing from context.** That is the SessionStart hook, not MCP. `/reload-plugins` should report at least `1 hook`; hooks run at session start, so start a new session after reloading. If the hook runs but prints `JFYI_URL / JFYI_MCP_TOKEN not configured`, set the values with `/plugin configure jfyi@jfyi`.
