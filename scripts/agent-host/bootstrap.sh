#!/usr/bin/env bash
# Bootstrap an always-on agent host (fresh Ubuntu 22.04/24.04, x64 or ARM64).
#
# Gets Claude Code running headless against your Max SUBSCRIPTION (not the
# metered API), plus node/ripgrep/jq/ccusage for the paced runner. Idempotent.
#
# Usage on the box (as a normal sudo user, NOT root, NOT with sudo):
#   git clone https://github.com/maxmoneycash/maxmoneycash.git
#   bash maxmoneycash/scripts/agent-host/bootstrap.sh
#   claude            # one-time login: open the printed URL, paste the code
#
# CRITICAL: never export ANTHROPIC_API_KEY on this box. If it is set, Claude
# Code authenticates with the metered API instead of your subscription.
set -euo pipefail

if [ "$(id -u)" = "0" ]; then
  echo "Run as a normal user with sudo, not as root (the claude installer refuses root)." >&2
  exit 1
fi
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  echo "ANTHROPIC_API_KEY is set — unset it or this box will burn metered API \$." >&2
  echo "Add 'unset ANTHROPIC_API_KEY' to ~/.bashrc and re-login, then re-run." >&2
  exit 1
fi

echo "==> apt deps"
sudo apt-get update -qq
sudo apt-get install -y -qq git curl jq ripgrep python3 python3-pip ca-certificates >/dev/null

echo "==> node 20 (for ccusage / npx)"
if ! command -v node >/dev/null || [ "$(node -v | cut -d. -f1 | tr -d v)" -lt 18 ]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - >/dev/null 2>&1
  sudo apt-get install -y -qq nodejs >/dev/null
fi
node -v

echo "==> Claude Code (native installer)"
if ! command -v claude >/dev/null && [ ! -x "$HOME/.local/bin/claude" ]; then
  curl -fsSL https://claude.ai/install.sh | bash
fi
export PATH="$HOME/.local/bin:$PATH"
grep -q '.local/bin' "$HOME/.bashrc" || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
claude --version

echo "==> work dir + repos"
mkdir -p "$HOME/work"
cd "$HOME/work"
for repo in maxmoneycash commit-markets; do
  [ -d "$repo/.git" ] || git clone "https://github.com/maxmoneycash/$repo.git" 2>/dev/null || true
done

echo
echo "============================================================"
echo "Base ready. Two manual steps remain:"
echo "  1. Log Claude Code into your Max subscription:"
echo "       claude"
echo "     -> choose 'Subscription', open the URL it prints on any device,"
echo "        paste the code back. (Do NOT pick the API-key option.)"
echo "     Verify with:  claude  ->  /status   (should show your Max plan)"
echo "  2. Start the paced overnight runner:"
echo "       bash ~/work/maxmoneycash/scripts/agent-host/paced-runner.sh --install"
echo "============================================================"
