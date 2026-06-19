#!/usr/bin/env bash
set -euo pipefail

if ! command -v gh >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y gh jq curl
fi

if [[ -n "${GH_TOKEN:-}" ]]; then
  printf '%s' "$GH_TOKEN" | gh auth login --with-token
fi

mkdir -p ~/.ssh
if [[ -n "${PROD_SSH_KEY:-}" ]]; then
  printf '%s\n' "$PROD_SSH_KEY" > ~/.ssh/prod_ed25519
  chmod 600 ~/.ssh/prod_ed25519
fi

if ! grep -q "Host hermes-prod" ~/.ssh/config 2>/dev/null; then
  cat >> ~/.ssh/config <<'EOF'
Host hermes-prod
  HostName 167.233.53.205
  User root
  IdentityFile ~/.ssh/prod_ed25519
  StrictHostKeyChecking accept-new
EOF
fi

command -v curl >/dev/null 2>&1 || sudo apt-get install -y curl

echo "Hermes Bot setup complete."
