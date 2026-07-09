# Quality per dollar / Effective Tokens (opt-in)

TokenTracker answers *"what did the tokens **cost**?"*. This optional layer adds
*"what did they **buy**?"* — by joining a small, vendor-neutral sidecar of
**outcomes** to the token/$ rows TokenTracker already tracks.

It is **off by default** and **degrades to cost-only**: with no sidecar file,
nothing about TokenTracker changes.

## The metrics

- **Quality per dollar (Qual/$)** = accepted, gate-passing outcomes ÷ dollars
  spent, per model and per tool. The numerator is an **accepted outcome** (a
  merged PR / a passed task) — never lines of code (LOC would just reward bloat).
- **Effective Tokens (ET)** = the share of tokens that produced accepted work
  vs. rework (`total_tokens × acceptance_rate`).

Costs come entirely from TokenTracker's existing pricing. The sidecar only
supplies the *accepted/total* counts.

## The sidecar: `outcomes.jsonl`

Location: `~/.tokentracker/tracker/outcomes.jsonl` (next to `queue.jsonl`, but
**never** read or written by the queue/sync path). One JSON object per line:

```jsonl
{"timestamp":"2026-06-30T14:02:11Z","tool":"claude","model":"claude-opus-4-8","accepted":true,"task_type":"feature"}
{"timestamp":"2026-06-30T14:40:55Z","tool":"opencode","model":"kimi-k2.7-code","accepted":true}
{"timestamp":"2026-06-30T15:10:03Z","tool":"cursor","model":"gpt-5.5","accepted":false}
```

| field | required | meaning |
|-------|----------|---------|
| `timestamp` | yes | ISO‑8601; used to join to the token/$ rows by day window |
| `model` | no (defaults `unknown`) | model id, matched to the same pricing as queue rows |
| `tool` | no (falls back to `source`, then `unknown`) | the agent/tool (`claude`, `codex`, `cursor`, …) |
| `accepted` | no (defaults `false`) | **strictly** `true` for a gate-passing outcome; anything else = rework |
| `task_type` | no | optional low-cardinality label (`feature`, `bugfix`, …) |

Any agent (or a merged‑PR backfill, or a human) can append to this file.
See [`outcomes.sample.jsonl`](../outcomes.sample.jsonl).

### Privacy invariant — metadata only

`outcomes.jsonl` is **metadata only**. The reader
(`src/lib/outcomes-engine.js` → `sanitizeOutcome`) whitelists the scalar fields
above and **drops everything else at read time** — so PR bodies, diffs, prompts,
or message text can never reach the dashboard even if a writer accidentally
includes them. TokenTracker records token counts only; this keeps that promise.

## Enabling the card

1. Create `~/.tokentracker/tracker/outcomes.jsonl` (copy the sample to start).
2. In the dashboard, open **Settings → Labs → Quality per dollar** and turn it on.

The card appears in the dashboard **only when both** the toggle is on **and**
outcome data exists. With the toggle on but no data, nothing new renders.

## How it works (read-time join, never the hot path)

- `GET /functions/tokentracker-outcomes?from=&to=` reads the sidecar and joins
  it to the scoped queue rows in memory, returning per-model / per-tool
  `quality_per_dollar`, `effective_tokens`, `acceptance_rate`, plus totals.
- When the file is absent it returns `{ "available": false, … }` and the UI
  renders nothing new.
- It **never** touches `queue.jsonl`'s schema or the `sync` path, so a bug in
  this layer cannot corrupt the token/$ data.
