#!/usr/bin/env bash
# JFYI SessionStart hook — inject the developer constitution into context.
# stdout of a SessionStart hook is added to Claude's context.
#
# Configuration: Claude Code exports plugin userConfig values to hook processes
# as CLAUDE_PLUGIN_OPTION_<KEY>. Fallback: JFYI_URL / JFYI_MCP_TOKEN environment
# variables (cloud environments, --plugin-dir testing). Nothing is read from
# files in the repository.
#
# Always exits 0: a missing or misconfigured instance must not block the session.
set -u

URL="${CLAUDE_PLUGIN_OPTION_JFYI_URL:-${JFYI_URL:-}}"
TOKEN="${CLAUDE_PLUGIN_OPTION_JFYI_TOKEN:-${JFYI_MCP_TOKEN:-}}"
[[ -n "$URL" && -n "$TOKEN" ]] || { echo "JFYI: JFYI_URL / JFYI_MCP_TOKEN not configured; skipping." >&2; exit 0; }

# jfyi_url is the instance root. The value people have at hand is often the MCP
# endpoint from the dashboard, so tolerate a trailing /mcp, /mcp/ or /mcp/sse.
BASE="${URL%/}"
case "$BASE" in
  */mcp/sse) BASE="${BASE%/mcp/sse}" ;;
  */mcp)     BASE="${BASE%/mcp}" ;;
  *)         ;;  # already the instance root
esac
BASE="${BASE%/}"
if [[ "$BASE" != "${URL%/}" ]]; then
  echo "JFYI: jfyi_url should be the instance root (${BASE}), not the MCP endpoint (${URL}). The constitution is still loaded, but the MCP tools will not connect until you fix it with /plugin configure jfyi@jfyi." >&2
fi

PROJECT="$(basename "${CLAUDE_PROJECT_DIR:-$PWD}")"
ENDPOINT="${BASE}/api/export/agents-md"
BODY_FILE="$(mktemp)"
trap 'rm -f "$BODY_FILE"' EXIT

if ! STATUS="$(curl -sS --max-time 8 -o "$BODY_FILE" -w '%{http_code}' \
     -H "Authorization: Bearer ${TOKEN}" \
     -G --data-urlencode "project_context=${PROJECT}" "$ENDPOINT")"; then
  echo "JFYI: constitution unavailable (could not connect to ${BASE}); continuing without it." >&2
  exit 0
fi

case "$STATUS" in
  2*)
    cat "$BODY_FILE"
    printf '\n\n'
    echo "JFYI MCP tools are connected: invoke discover_tools(tool_name='recall_journal', arguments={...}) before proposing changes that may already have been decided; file stable preferences via discover_tools(tool_name='add_profile_note', arguments={...}) and decisions via discover_tools(tool_name='add_journal_note', arguments={...})."
    ;;
  404)
    echo "JFYI: constitution unavailable (HTTP 404 from ${ENDPOINT}). A server answered but the path is wrong: jfyi_url must be the instance root with no path, e.g. https://jfyi.example.net. Fix it with /plugin configure jfyi@jfyi. Continuing without it." >&2
    ;;
  401|403)
    echo "JFYI: constitution unavailable (HTTP ${STATUS} from ${BASE}): the token was rejected. Generate a new one under Settings → Connect and set it with /plugin configure jfyi@jfyi. Continuing without it." >&2
    ;;
  *)
    echo "JFYI: constitution unavailable (HTTP ${STATUS} from ${ENDPOINT}); continuing without it." >&2
    ;;
esac
exit 0
