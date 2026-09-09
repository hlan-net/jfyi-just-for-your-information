#!/usr/bin/env bash
# JFYI SessionStart hook — inject the developer constitution into context.
# stdout of a SessionStart hook is added to Claude's context.
#
# Configuration comes from plugin userConfig (JFYI_CFG_*) or, as a fallback,
# from the JFYI_URL / JFYI_MCP_TOKEN environment variables (cloud environments).
# Nothing is read from files in the repository.
set -u

pick() { case "$1" in ''|'${user_config'*) printf '%s' "$2" ;; *) printf '%s' "$1" ;; esac; }
URL="$(pick "${JFYI_CFG_URL:-}" "${JFYI_URL:-}")"
TOKEN="$(pick "${JFYI_CFG_TOKEN:-}" "${JFYI_MCP_TOKEN:-}")"
[ -n "$URL" ] && [ -n "$TOKEN" ] || { echo "JFYI: JFYI_URL / JFYI_MCP_TOKEN not configured; skipping." >&2; exit 0; }

PROJECT="$(basename "${CLAUDE_PROJECT_DIR:-$PWD}")"
if BODY="$(curl -sS --fail --max-time 8 -H "Authorization: Bearer ${TOKEN}" \
     "${URL%/}/api/export/agents-md?project_context=${PROJECT}")"; then
  printf '%s\n\n' "$BODY"
  echo "JFYI MCP tools are connected: call recall_journal before proposing changes that may already have been decided; file stable preferences with add_profile_note and decisions with add_journal_note."
else
  echo "JFYI: constitution unavailable (${URL} unreachable); continuing without it." >&2
fi
exit 0
