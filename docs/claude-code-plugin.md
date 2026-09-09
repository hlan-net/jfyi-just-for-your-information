# Claude Code Plugin — JFYI in the CLI, Desktop and web sessions

**Status:** Shipped in `v2.17.0` — plugin lives in [`plugins/jfyi/`](../plugins/jfyi/), installable from this repository's marketplace. The guide is also shown in the dashboard under `Settings → Claude Code plugin`.  
**Tag:** Infrastructure (delivery of the core read path)  
**Verified against:** Claude Code docs for [plugins](https://code.claude.com/docs/en/plugins-reference), [hooks](https://code.claude.com/docs/en/hooks), [MCP](https://code.claude.com/docs/en/mcp), [marketplaces](https://code.claude.com/docs/en/plugin-marketplaces) and [cloud environments](https://code.claude.com/docs/en/cloud-environments)

> [!IMPORTANT]
> **No secrets, no personal data in any repository.** The plugin is generic: your JFYI instance URL and MCP token are entered once at install time (the token goes to Claude Code's secure storage) or set as variables on a cloud environment. Do not fork this repo to bake in your URL or token, and do not commit them to your own projects. Every snippet below is safe to commit as-is.

## Why a plugin

Adding JFYI as an MCP server only gives the agent *tools*. It still has to remember to call `get_developer_profile`. The plugin bundles three things so JFYI becomes passive, which is the mission ([architecture.md](architecture.md)):

| Piece | What it does | JFYI tier |
|---|---|---|
| `hooks/hooks.json` → `SessionStart` | Fetches `GET /api/export/agents-md` and prints it. Claude Code adds SessionStart stdout to the model's context, so the constitution is present before the first prompt and again after `/compact`. | Read curated |
| `.mcp.json` | Connects the SSE endpoint so `recall_journal`, `add_profile_note`, `add_journal_note`, `record_interaction` are callable. | Write raw / read curated |
| `skills/jfyi/SKILL.md` | Tells the agent *when* to use those tools (pattern-level notes, decision notes after milestones). | Write raw |
| `hooks/hooks.json` → `Stop` (optional) | Posts each assistant turn to `POST /api/interactions` as raw telemetry. JFYI stores only hashes of prompt and response. | Write raw |

## 1. Install for yourself (CLI and Desktop)

```bash
claude plugin marketplace add hlan-net/jfyi-just-for-your-information
claude plugin install jfyi@jfyi
```

Claude Code asks for the two `userConfig` values declared by the plugin:

| Key | Value | Where it is stored |
|---|---|---|
| `jfyi_url` | Your instance, e.g. `https://jfyi.example.net` (no trailing slash) | Claude Code plugin config |
| `jfyi_token` | Bearer token from your dashboard, `Settings → Connect` | Secure storage (`sensitive: true`), never a settings file |

Non-interactive form (values still stay out of the repo):

```bash
claude plugin install jfyi@jfyi --config jfyi_url=https://jfyi.example.net --config jfyi_token="$JFYI_MCP_TOKEN"
```

Verify: inside a session run `/mcp` (the `jfyi` server should be connected) and `/context` (the injected constitution is visible).

## 2. Enable for a project or team

Commit this to the project's `.claude/settings.json`. It only *references* the public marketplace; every team member is asked for their own URL and token the first time the plugin loads, so nothing personal enters the repo.

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

If you prefer not to use the marketplace at all, commit a project `.mcp.json` that expands the same variables (no URL, no token in the file) and a `SessionStart` hook in `.claude/settings.json` that runs `plugins/jfyi/scripts/session-start.sh` from a checkout of this repo:

```json
{
  "mcpServers": {
    "jfyi": {
      "type": "sse",
      "url": "${JFYI_URL}/mcp/sse",
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
├── .mcp.json                  # SSE server: ${user_config.jfyi_url}/mcp/sse
├── hooks/
│   └── hooks.json             # SessionStart + optional Stop hook
├── scripts/
│   ├── session-start.sh       # injects the constitution; exits 0 if JFYI is unreachable
│   └── record-interaction.sh  # optional raw telemetry (needs jq)
└── skills/
    └── jfyi/
        └── SKILL.md           # usage guidance for the agent
```

The marketplace manifest is [`.claude-plugin/marketplace.json`](../.claude-plugin/marketplace.json) at the repository root; its `source` path resolves relative to the repo root.

Design notes:

- Hook commands pass `${user_config.*}` through as `JFYI_CFG_URL` / `JFYI_CFG_TOKEN`; the scripts treat an empty or unexpanded value as "use `JFYI_URL` / `JFYI_MCP_TOKEN` from the environment". One script serves both install paths.
- `/api/export/agents-md` already applies the constitution token budget (`JFYI_CONSTITUTION_TOKEN_BUDGET`), so the injected block stays bounded. `project_context` is the checkout's directory basename, which makes project-scoped rules ride along.
- The `Stop` hook cannot infer corrections, so `was_corrected` stays `false`. A `UserPromptSubmit` hook that flags the previous turn when the next prompt starts with a correction is a natural follow-up.
- Test changes to the plugin with `claude plugin validate ./plugins/jfyi` and `claude --plugin-dir ./plugins/jfyi` (export `JFYI_URL` and `JFYI_MCP_TOKEN` in your shell for the run).
