# TokenTracker — Product Context

register: product

## Product purpose

Local-first AI token-usage tracker. Parses logs from AI coding CLIs (Claude Code, Codex, Cursor, Gemini, Copilot, Kimi, and more) into a local dashboard so developers can see how many tokens they burn, the estimated cost, and how it trends. Privacy-first: token counts only, never prompts or conversation bodies. Ships as a CLI (`serve` on :7680), a web dashboard (www.tokentracker.cc), and a self-contained macOS menu-bar app.

## Users

Developers and AI-power-users who run multiple agent CLIs daily and want a single, trustworthy view of consumption and cost. They are fluent in tools like Linear, Raycast, Vercel, and GitHub. They check usage both at a desk (deep review) and on a phone (quick glance: "how much did I burn today / where am I on the leaderboard"). They distrust inflated numbers, so accuracy and legible key metrics matter more than decoration.

## Tone & principles

- Quiet, precise, trustworthy. The tool disappears into the task. Earned familiarity over novelty.
- Numbers are the hero content, but never the gradient-glow "hero-metric" cliché. Big figures must stay legible and never clip.
- Mobile is a first-class glance surface, not a shrunk desktop. Core metrics (total tokens, cost, your rank) must be visible without horizontal scrolling.
- Per-provider breakdown is secondary detail: fine to defer to a tap/expand on small screens.

## Anti-references

- SaaS-cream landing-page gloss, neon-on-black "crypto" dashboards, gratuitous glassmorphism.
- Wide data tables that force horizontal scrolling on phones and bury the key column off-screen.
- Fluid/clamp display type that shrinks unpredictably inside narrow panels.
