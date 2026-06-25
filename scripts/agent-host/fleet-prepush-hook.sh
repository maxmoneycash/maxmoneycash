#!/usr/bin/env bash
# pre-push gate: block any push whose DEPLOY would fail.
# Preferred: if we have a Vercel token + a linked project, run `vercel build` —
# the EXACT deploy build (respects .vercelignore, builds serverless functions),
# which catches the "passes locally, module-not-found on Vercel" class. Falls back
# to reproducing vercel.json's install+build locally. Override: git push --no-verify
set -uo pipefail
export PATH="$HOME/.local/bin:$HOME/.bun/bin:$HOME/.cargo/bin:/usr/local/go/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$root" || exit 0
[ -f package.json ] || exit 0

# ---------- preferred: exact `vercel build` ----------
VT=$(grep '^VERCEL_TOKEN=' "$HOME/fleet/secrets.env" 2>/dev/null | cut -d= -f2)
maindir=$(dirname "$(git rev-parse --git-common-dir 2>/dev/null)" 2>/dev/null)
vfile="$maindir/.vercel/project.json"
if [ -n "$VT" ] && [ -f vercel.json ] && [ -f "$vfile" ] && command -v node >/dev/null 2>&1; then
  export VERCEL_TOKEN="$VT"
  export VERCEL_ORG_ID=$(node -e "process.stdout.write(require('$vfile').orgId||'')" 2>/dev/null)
  export VERCEL_PROJECT_ID=$(node -e "process.stdout.write(require('$vfile').projectId||'')" 2>/dev/null)
  if [ -n "$VERCEL_PROJECT_ID" ]; then
    echo "[pre-push] EXACT vercel build (respects .vercelignore + functions) — protects prod"
    npx --yes vercel pull --yes --environment=preview >/tmp/prepush-vpull.log 2>&1 || true
    if ! npx --yes vercel build >/tmp/prepush-build.log 2>&1; then
      echo "=================================================================="
      echo "[pre-push] ❌ VERCEL BUILD FAILED — push BLOCKED (this is the real deploy)."
      echo "------------------------------------------------------------------"
      tail -45 /tmp/prepush-build.log
      echo "------------------------------------------------------------------"
      echo "Fix it, push again.  full log: /tmp/prepush-build.log"
      echo "=================================================================="
      exit 1
    fi
    echo "[pre-push] ✅ vercel build OK — push allowed."
    exit 0
  fi
fi

# ---------- fallback: reproduce vercel.json install+build locally ----------
if   [ -f bun.lockb ];      then DEF_INSTALL="bun install";                     DEF_BUILD="bun run build"
elif [ -f pnpm-lock.yaml ]; then DEF_INSTALL="pnpm install --frozen-lockfile"; DEF_BUILD="pnpm run build"
elif [ -f yarn.lock ];      then DEF_INSTALL="yarn install --frozen-lockfile"; DEF_BUILD="yarn build"
else                             DEF_INSTALL="npm install";                     DEF_BUILD="npm run build"; fi
VB=""; VI=""
if [ -f vercel.json ] && command -v node >/dev/null 2>&1; then
  VB=$(node -e 'try{process.stdout.write((require("./vercel.json").buildCommand)||"")}catch(e){}' 2>/dev/null)
  VI=$(node -e 'try{process.stdout.write((require("./vercel.json").installCommand)||"")}catch(e){}' 2>/dev/null)
fi
INSTALL_CMD="${VI:-$DEF_INSTALL}"; BUILD_CMD="${VB:-$DEF_BUILD}"
[ -n "$BUILD_CMD" ] || exit 0
{ [ -n "$VB" ] || grep -q '"build"' package.json; } 2>/dev/null || exit 0
echo "[pre-push] reproducing vercel build locally (no token/link): $BUILD_CMD"
sh -c "$INSTALL_CMD" >/tmp/prepush-install.log 2>&1 || { echo "[pre-push] ❌ INSTALL FAILED:"; tail -25 /tmp/prepush-install.log; exit 1; }
if ! sh -c "$BUILD_CMD" >/tmp/prepush-build.log 2>&1; then
  echo "[pre-push] ❌ BUILD FAILED — push BLOCKED:"; tail -45 /tmp/prepush-build.log; exit 1
fi
echo "[pre-push] ✅ build OK — push allowed."
exit 0
