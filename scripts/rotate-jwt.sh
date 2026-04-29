#!/usr/bin/env bash
#
# rotate-jwt.sh — rotate the JFYI JWT signing secret in a Kubernetes deployment.
#
# Mints a fresh 64-character random secret, patches the existing JWT Secret
# resource, and triggers a rolling restart of the JFYI Deployment. After
# rotation, every previously-issued MCP API token and dashboard session
# cookie is invalidated and clients must re-authenticate.
#
# Usage:
#   scripts/rotate-jwt.sh [-n NAMESPACE] [-r RELEASE]
#
# Defaults:
#   NAMESPACE = jfyi
#   RELEASE   = jfyi-mcp-server
#
# The script assumes the standard Helm chart layout: a Secret named
# "${RELEASE}-jwt" containing the key JFYI_JWT_SECRET, consumed by a
# Deployment that matches `app.kubernetes.io/name=jfyi-mcp-server`.

set -euo pipefail

NAMESPACE="jfyi"
RELEASE="jfyi-mcp-server"

while getopts ":n:r:h" opt; do
  case "${opt}" in
    n) NAMESPACE="${OPTARG}" ;;
    r) RELEASE="${OPTARG}" ;;
    h)
      sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown flag: -${OPTARG}" >&2; exit 2 ;;
  esac
done

SECRET_NAME="${RELEASE}-jwt"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "ERROR: kubectl is required" >&2
  exit 1
fi

echo "→ Verifying secret ${NAMESPACE}/${SECRET_NAME} exists…"
kubectl -n "${NAMESPACE}" get secret "${SECRET_NAME}" >/dev/null

NEW_SECRET="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 64)"
NEW_SECRET_B64="$(printf '%s' "${NEW_SECRET}" | base64 | tr -d '\n')"

echo "→ Patching ${NAMESPACE}/${SECRET_NAME} with a new JFYI_JWT_SECRET…"
# Pass the patch via stdin so the secret value never appears in process listings.
kubectl -n "${NAMESPACE}" patch secret "${SECRET_NAME}" \
  --type=json \
  -p- <<EOF
[{"op":"replace","path":"/data/JFYI_JWT_SECRET","value":"${NEW_SECRET_B64}"}]
EOF

echo "→ Rolling deployment ${NAMESPACE}/${RELEASE}…"
kubectl -n "${NAMESPACE}" rollout restart deployment "${RELEASE}"
kubectl -n "${NAMESPACE}" rollout status deployment "${RELEASE}" --timeout=180s

echo
echo "✓ JWT secret rotated."
echo "  All previously-issued MCP API keys and dashboard sessions are now invalid."
echo "  Users must re-authenticate; agents must mint new MCP API keys via the dashboard."
