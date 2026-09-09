#!/usr/bin/env bash
# JFYI Stop hook — record the assistant turn as a raw interaction (optional).
# JFYI stores only hashes of prompt and response, never the text.
set -u
command -v jq >/dev/null 2>&1 || exit 0

URL="${CLAUDE_PLUGIN_OPTION_JFYI_URL:-${JFYI_URL:-}}"
TOKEN="${CLAUDE_PLUGIN_OPTION_JFYI_TOKEN:-${JFYI_MCP_TOKEN:-}}"
[ -n "$URL" ] && [ -n "$TOKEN" ] || exit 0

INPUT="$(cat)"
SESSION="$(printf '%s' "$INPUT" | jq -r '.session_id // empty')"
RESPONSE="$(printf '%s' "$INPUT" | jq -r '.last_assistant_message // empty' | head -c 4000)"
[ -n "$RESPONSE" ] || exit 0

jq -n --arg s "$SESSION" --arg r "$RESPONSE" \
  '{agent_name: "claude-code", session_id: $s, prompt: "(claude-code turn)", response: $r, was_corrected: false}' \
| curl -sS --max-time 5 -o /dev/null \
    -H "Authorization: Bearer ${TOKEN}" -H 'Content-Type: application/json' \
    -d @- "${URL%/}/api/interactions" || true
exit 0
