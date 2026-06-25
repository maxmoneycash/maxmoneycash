#!/usr/bin/env bash
# Install the full polyglot dev toolchain on the agent box so Claude Code agents
# can actually build/test/run our projects. Idempotent + non-fatal per section
# (one tool failing never aborts the rest). Prebuilt binaries / official
# installers only — NEVER builds big Rust projects from source (8GB box = OOM).
#
# Stack covered: TS/React/Next/Vite (npm/yarn/pnpm/bun) · Python (uv/pipx) ·
# Rust · Go · Aptos Move · Sui · Solana/Anchor · Solidity/Foundry.
#
#   bash dev-tools.sh 2>&1 | tee ~/dev-tools-install.log
#
# Never sets ANTHROPIC_API_KEY.
set -uo pipefail   # deliberately NOT -e: keep going if one tool fails

ARCH="$(uname -m)"
log()  { echo -e "\n========== $* =========="; }
warn() { echo "WARN: $*" >&2; }
have() { command -v "$1" >/dev/null 2>&1; }
[ "$ARCH" = "x86_64" ] || warn "arch is $ARCH (script assumes x86_64; prebuilt URLs may be wrong)"

mkdir -p "$HOME/.local/bin"
# bin dirs on PATH for THIS run so later steps + the verify table see new tools
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$HOME/.bun/bin:$HOME/.foundry/bin:/usr/local/go/bin:$HOME/.local/share/solana/install/active_release/bin:$PATH"

# --- persist PATH in ~/.bashrc (idempotent) ---
add_path() { grep -qF "$1" "$HOME/.bashrc" 2>/dev/null || echo "$1" >> "$HOME/.bashrc"; }
add_path 'export PATH="$HOME/.local/bin:$PATH"'
add_path 'export PATH="$HOME/.cargo/bin:$PATH"'
add_path 'export PATH="$HOME/.bun/bin:$PATH"'
add_path 'export PATH="$HOME/.foundry/bin:$PATH"'
add_path 'export PATH="/usr/local/go/bin:$PATH"'
add_path 'export PATH="$HOME/.local/share/solana/install/active_release/bin:$PATH"'

# ===================== apt base =====================
log "apt base packages"
sudo apt-get update -qq || warn "apt update failed"
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  build-essential pkg-config libssl-dev libudev-dev clang cmake protobuf-compiler \
  ca-certificates curl wget gnupg unzip git jq ripgrep fd-find fzf tree \
  python3-venv python3-dev python3-pip libpq-dev || warn "apt install had errors"
# Ubuntu ships fd as 'fdfind' — give it the conventional 'fd' name
if have fdfind && ! have fd; then ln -sf "$(command -v fdfind)" "$HOME/.local/bin/fd"; fi

# ===================== GitHub CLI (official repo) =====================
log "gh (GitHub CLI)"
if ! have gh; then
  sudo mkdir -p -m 755 /etc/apt/keyrings
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null
  sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
  sudo apt-get update -qq && sudo apt-get install -y -qq gh || warn "gh install failed"
fi

# ===================== Node ecosystem (node20 already present) =====================
log "Node: global package managers + CLIs"
sudo corepack enable 2>/dev/null || warn "corepack enable failed (packageManager field may not auto-resolve)"
sudo npm install -g --silent pnpm yarn typescript tsx vercel 2>/dev/null || warn "global npm installs had errors"

log "bun"
have bun || { curl -fsSL https://bun.sh/install | bash || warn "bun install failed"; }

# ===================== Python: uv + pipx =====================
log "uv (Astral) — agents should use uv/venv, not system pip (PEP 668)"
have uv || { curl -LsSf https://astral.sh/uv/install.sh | sh || warn "uv install failed"; }
log "pipx"
if ! have pipx; then sudo apt-get install -y -qq pipx && pipx ensurepath || warn "pipx install failed"; fi

# ===================== Rust =====================
log "rustup + cargo"
if ! have cargo; then
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path \
    || warn "rustup install failed"
fi
[ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"
have rustup && rustup component add clippy rustfmt >/dev/null 2>&1 || true

# ===================== Go =====================
log "Go"
if ! have go; then
  GO_VER="$(curl -fsSL 'https://go.dev/VERSION?m=text' 2>/dev/null | head -1)"
  [ -n "${GO_VER:-}" ] || GO_VER="go1.23.4"
  if curl -fsSL "https://go.dev/dl/${GO_VER}.linux-amd64.tar.gz" -o /tmp/go.tgz; then
    sudo rm -rf /usr/local/go && sudo tar -C /usr/local -xzf /tmp/go.tgz && rm -f /tmp/go.tgz
  else warn "go download failed"; fi
fi

# ===================== Foundry (Solidity) =====================
log "Foundry (forge/cast/anvil) — prebuilt"
if ! have forge; then
  curl -L https://foundry.paradigm.xyz | bash || warn "foundryup bootstrap failed"
  "$HOME/.foundry/bin/foundryup" || warn "foundryup failed"
fi

# ===================== Aptos CLI (prebuilt) =====================
log "Aptos CLI — prebuilt (59 Move.toml repos)"
if ! have aptos; then
  if curl -fsSL https://aptos.dev/scripts/install_cli.sh | sh; then :; else
    warn "aptos official script failed — trying GitHub release zip"
    url="$(curl -fsSL https://api.github.com/repos/aptos-labs/aptos-core/releases?per_page=30 \
          | grep -Eo 'https://[^"]*aptos-cli-[0-9.]+-Linux-x86_64\.zip' | head -1)"
    if [ -n "${url:-}" ]; then
      curl -fsSL "$url" -o /tmp/aptos.zip && unzip -o -q /tmp/aptos.zip -d "$HOME/.local/bin" \
        && chmod +x "$HOME/.local/bin/aptos" && rm -f /tmp/aptos.zip || warn "aptos zip install failed"
    else warn "could not find aptos release asset"; fi
  fi
fi

# ===================== Sui CLI (prebuilt — NEVER cargo-build) =====================
log "Sui CLI — prebuilt release binary (cargo build would OOM)"
if ! have sui; then
  url="$(curl -fsSL https://api.github.com/repos/MystenLabs/sui/releases?per_page=15 \
        | grep -Eo 'https://[^"]*ubuntu-x86_64\.tgz' | head -1)"
  if [ -n "${url:-}" ]; then
    curl -fsSL "$url" -o /tmp/sui.tgz && mkdir -p /tmp/suix && tar -C /tmp/suix -xzf /tmp/sui.tgz \
      && find /tmp/suix -maxdepth 3 -type f \( -name 'sui' -o -name 'sui-*' \) -exec install -m755 {} "$HOME/.local/bin/" \; \
      && rm -rf /tmp/suix /tmp/sui.tgz || warn "sui install failed"
  else warn "could not find sui ubuntu-x86_64 release asset"; fi
fi

# ===================== Solana (Anza/Agave) =====================
log "Solana CLI (Anza)"
have solana || { sh -c "$(curl -sSfL https://release.anza.xyz/stable/install)" || warn "solana install failed"; }

# ===================== Anchor (OPTIONAL — builds from source) =====================
log "Anchor: installing 'avm' only (optional). Run 'avm install latest' later — it compiles from source."
if have cargo && ! have avm && ! have anchor; then
  cargo install --git https://github.com/coral-xyz/anchor avm --locked 2>/dev/null \
    || warn "avm install skipped/failed (optional)"
fi

# ===================== verification =====================
log "VERIFICATION (version or MISSING)"
for t in git gh make gcc node npm pnpm yarn bun tsc tsx vercel \
         python3 uv pipx rustc cargo go aptos sui solana forge cast anvil avm anchor \
         fd fzf tree jq rg tmux ttyd tailscale claude; do
  if command -v "$t" >/dev/null 2>&1; then
    printf "  %-10s %s\n" "$t" "$("$t" --version 2>/dev/null | head -1)"
  else
    printf "  %-10s MISSING\n" "$t"
  fi
done
echo
echo "Done. Re-run anytime (idempotent). Log: ~/dev-tools-install.log"
