# 24/7 Agent Host — Architecture

Goal: Claude agents working day and night on a cheap always-on cloud box,
billed to the **Max subscription** (never the metered API), pacing themselves
around the plan's limits, off-loading work from the laptop, and producing
reviewable PRs — with Hermes orchestrating and Claude Code + Droid executing.

---

## The one constraint that shapes everything

The Max plan caps usage on a **rolling 5-hour window** and a **weekly window**,
use-it-or-lose-it (nothing accumulates). So this system is **not literally
nonstop** — it works in bounded jobs and **sleeps when capped**, spreading the
full weekly allowance across the nights at **zero marginal cost**. Genuine 24/7
continuous would require the metered API ($$$), which this box refuses to use
(it never sets `ANTHROPIC_API_KEY`).

> Watch item: Anthropic has a *paused* change that would move headless / Agent-SDK
> usage to a **separate monthly credit pool** instead of the weekly limits. While
> paused, the box draws from the weekly cap. If it un-pauses, overnight work stops
> eating your interactive allowance — re-tune the pacing wider when that lands.

---

## Topology

```
  YOU (phone / laptop, anytime)
   │  add tasks → GitHub Issues (label: agent)        review ← GitHub PRs
   │  steer → issue comments                          alerts ← ntfy push
   ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │  DigitalOcean Droplet · Ubuntu 24.04 · 4GB · always on            │
 │                                                                    │
 │  systemd --user (linger) keeps everything alive across reboots     │
 │                                                                    │
 │   ┌─ ORCHESTRATOR ────────────┐    intake: GitHub Issues / worklist│
 │   │  Hermes (Phase 3)          │    pacing: ccusage + limit guard   │
 │   │  → sequences the queue,    │                                    │
 │   │    enforces pacing,        │                                    │
 │   │    fans out bounded waves  │                                    │
 │   └─────────┬─────────────────┘                                    │
 │             │ dispatches one bounded job at a time                  │
 │   ┌─────────▼─────────┐   ┌──────────────────┐                     │
 │   │ Claude Code (-p)  │   │ Droid (Phase 3)  │   ← WORKERS         │
 │   │ primary executor  │   │ second coder     │     (sub auth)      │
 │   └─────────┬─────────┘   └────────┬─────────┘                     │
 │             │ branch per task, commit, push                        │
 │   ┌─────────▼──────────────────────▼─────────┐                     │
 │   │ ~/work/<repo>  (git clones, PR-only)      │                     │
 │   │ ~/work/.agent-memory/  (lessons across runs)                   │
 │   └───────────────────────────────────────────┘                    │
 │                                                                    │
 │   ┌─ DATA PUBLISHER (timer) ──────────────────┐                    │
 │   │ renders GitHub-data cards daily (no laptop │                    │
 │   │ needed) + contributes box's own usage      │                    │
 │   └───────────────────────────────────────────┘                    │
 └──────────────────────────────────────────────────────────────────┘
            │ git push (scoped PAT)        │ ccusage (sub usage)
            ▼                              ▼
        GitHub (PRs, Issues, profile)   Anthropic (Max subscription)
```

---

## Layers

### 1. Host & persistence
- **DigitalOcean Droplet**, Ubuntu 24.04, 4 GB (Claude Code's hard minimum). Any
  4 GB+ Ubuntu VPS is a drop-in; provider only changes the create step.
- **systemd `--user` services + `loginctl enable-linger`** — survives logout and
  reboot, auto-restarts on crash (`Restart=always`). Already wired in
  `paced-runner.sh --install`.

### 2. Auth (the whole point)
- **Claude Code** logs into the **Max subscription** via the OAuth device flow
  (browser-code, works over SSH). Creds live in `~/.claude`.
- **Hermes / Droid** authenticate against the *same* subscription (the capability
  Anthropic just enabled) — verified live in Phase 3, not guessed here.
- **Hard rule:** `ANTHROPIC_API_KEY` is never set; the runner aborts if it is.
  That's what keeps everything on the flat sub instead of metered API.
- **GitHub:** a **fine-grained PAT** (or `gh auth login`) scoped to just these
  repos, contents+PR write. The only outbound credential on the box.

### 3. Orchestration
- **Phase 1:** `paced-runner.sh` is the orchestrator — one bounded Claude Code
  job at a time.
- **Phase 3:** **Hermes** becomes the orchestrator — pulls the queue, enforces
  pacing, fans out small parallel waves (≤3) to **Claude Code** and **Droid**,
  collects results. The Fable-orchestrates / cheap-workers pattern: a smart
  planner sequencing bounded executors.

### 4. Pacing (stay-within-limits)
- Usage signal: `npx -y ccusage@latest blocks --active --json`.
- Loop: run a bounded wave → on success, short gap → next task; on failure OR a
  usage-cap hit (any non-zero `claude` exit), **back off to the next 5-hour
  window** and resume. Belt-and-suspenders so it can never blow the weekly cap.
- Resume verifies the *real* window via ccusage, not just elapsed time.

### 5. Work intake
- **Phase 1:** `worklist.md` (file queue, committed so it survives rebuilds).
- **Phase 2:** **GitHub Issues** labeled `agent` become the real queue — add
  tasks from your phone, steer with comments, and the PR that fixes it
  auto-closes the issue. Natural, reviewable, no custom UI.

### 6. Execution model
- Each task → fresh branch `agent/<timestamp>` → executor runs with a prompt that
  injects guardrails (smallest change, no unrelated refactors, **stop and leave a
  note if ambiguous**) → commit → push branch → **open a PR** (never push `main`).
- `--dangerously-skip-permissions` is acceptable here *because* the box is a
  dedicated, isolated, throwaway VM scoped to specific repos with only a narrow
  GitHub token — there's nothing else to damage.

### 7. Output & review
- **GitHub PRs** are the review surface — you merge in the morning.
- **ntfy.sh** (free, phone push, one curl) for "job done / blocked / capped"
  alerts. Swappable for a Slack/Discord webhook.
- **Daily recap** (red/yellow/green): what ran, PRs opened, failures, usage spent
  — pushed via ntfy and written to `recaps/`.

### 8. Memory across runs
- `~/work/.agent-memory/*.md` — one lesson per file (conventions, gotchas,
  confirmed approaches), committed to a branch. Agents read it before work and
  append to it after, so quality compounds instead of resetting every night.

### 9. Data pipeline (resolves the stale-README root cause)
- **GitHub-data cards** (heatmaps, SF city, perp dashboard, wrapped) pull from the
  GitHub API — **no laptop dependency** — so the box renders them on a timer and
  they're always fresh even with the laptop closed. This is the real fix for the
  freeze we hit.
- **Token cards** depend on local `ccusage` logs, which live per-machine. The box
  can only see its *own* agent usage. So: the box becomes the always-on
  **publisher** and contributes its usage; the laptop keeps its collector for its
  richer multi-agent history; `build_tokens_json.py` **merges both**. Net: the
  README stays fresh daily, and the box's overnight work is counted too.

---

## Complete tool stack

| Concern | Tool | Why |
|---|---|---|
| Host | DigitalOcean Droplet (Ubuntu 24.04, 4GB) | Easiest UI, browser console, meets 4GB floor |
| Persistence | systemd `--user` + `loginctl enable-linger` | Survives reboot/logout, auto-restart |
| Primary agent | **Claude Code** (`claude -p`, headless) | Native sub auth, headless, tool use |
| Orchestrator | **Hermes** (Phase 3) | Sequences queue, paces, fans out waves |
| Second worker | **Droid / Factory** (Phase 3) | Parallel coding capacity, variety |
| Auth (models) | Claude subscription OAuth (`~/.claude`) | Flat-rate, no metered API |
| Auth (git) | Fine-grained GitHub PAT / `gh` | Scoped push + PR only |
| Usage signal | **ccusage** (`blocks --active --json`) | Drives the limit guard |
| Pacing | `paced-runner.sh` (stay-within-limits loop) | Bounded waves, back off when capped |
| Task queue | `worklist.md` → **GitHub Issues** (label `agent`) | File first, then phone-addable issues |
| Output | git branches → **GitHub PRs** | Reviewable, never touches `main` |
| Alerts | **ntfy.sh** (or Slack/Discord webhook) | Free phone push on done/blocked |
| Recap | red/yellow/green daily digest | Know what happened overnight |
| Memory | `~/work/.agent-memory/*.md` | Compounding quality across nights |
| Runtime | Node 20, Python 3, git, ripgrep, jq | ccusage + render pipeline + tooling |
| Render pipeline | existing `scripts/*.py` on a systemd timer | Fresh README without the laptop |

---

## Failure handling

| Failure | Response |
|---|---|
| Reboot / logout | linger + `Restart=always` bring the runner back |
| Usage cap hit | back off to next 5h window, re-check ccusage, resume |
| `claude` non-zero exit (any error) | treat as cap/transient → back off, retry |
| git push conflict | fetch + rebase + retry (the pattern we already hardened) |
| Ambiguous task | agent makes no change, writes a note in the PR/issue |
| Bad change | PR-only means nothing hits `main` unreviewed; delete branch |
| Network blip | command retries; next wave re-fetches |
| Box dies entirely | repos + worklist state live in git → rebuild from bootstrap in 10 min |

## Guardrails

- **PR-only**, never push `main` (default; `PUSH=1` opt-in after `gh auth login`).
- **Repo allowlist** — only the clones under `~/work`.
- **No production secrets** on the box — just the scoped GitHub PAT.
- Per-task prompt enforces minimal, in-scope, stop-if-unsure behavior.
- Subscription-only — capped means sleep, never spend.

---

## Build phases

- **Phase 1 (mostly built):** Claude Code paced-runner, `worklist.md`, PR-only,
  ntfy alerts. → first autonomous overnight run.
- **Phase 2:** GitHub Issues queue, daily recap, move GitHub-data renders onto the
  box (kills the laptop dependency), agent-memory.
- **Phase 3:** Hermes orchestrator + Droid worker on the same sub auth, parallel
  bounded waves, box contributes its usage to the token cards.
