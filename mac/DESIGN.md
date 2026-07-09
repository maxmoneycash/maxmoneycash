# TokenTracker — Design System

Derived from `dashboard/src/styles.css` + `dashboard/tailwind.config.cjs`. Tailwind utility classes use the `oai-*` token names.

## Color (OKLCH, green-tinted neutrals, hue 145)

- **Neutrals** `oai-gray-50…950`: every neutral is tinted toward green (chroma ~0.005–0.03, hue 145). Surfaces, borders, text. Dark mode inverts the ramp; dashboard defaults dark.
- **Brand accent**: emerald — `--oai-blue: #059669` (token name is legacy; the brand is green), light `#10b981`, dark `#047857`. Exposed as `oai-brand` utilities. Used for primary action, current selection, cost figure, and "you/me" highlight only. Restrained: accent ≤10% of surface.
- **Semantic**: success `#10b981`, warning `#f59e0b`, error `#ef4444`, info `#059669`.
- Never `#000`/`#fff`: base black `#0a0a0a`, white `#fafafa`.
- Per-provider category colors come from `getProviderColor()` (data-viz only, in distribution bars/charts).

## Typography

- **Sans**: `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, …` (system stack, `font-oai`). One family carries everything.
- **Mono**: `"SF Mono", SFMono-Regular, ui-monospace, Menlo, …` (`font-mono`) for token counts, terminal-style copy, IDs.
- Numbers use `tabular-nums`.
- Fixed rem-ish scale (Tailwind `text-xs … text-7xl`); product UI uses fixed steps, NOT fluid clamp headings. The one giant metric is the exception and must be width-bounded.

## Layout & components

- Card primitive: `Card` (single border + subtle elevation). No nested cards.
- Responsive shell: desktop sidebar `hidden lg:flex`; mobile drawer + `MobileTopBar` (hamburger) `lg:hidden`. Content scrolls inside `div.flex-1.overflow-y-auto`.
- Breakpoints: Tailwind defaults (`sm`=640, `md`=768, `lg`=1024). Phone target 360–430px.
- Motion: `motion/react`, ease-out, 150–250ms, state-conveying only. Respect `prefers-reduced-motion`.

## Mobile structural rules (this project)

- Tab/segment groups: single horizontal-scroll row, never `flex-wrap` into stacks.
- Big metric: cap with `clamp()`/responsive font so it never clips at 360px.
- Data tables: collapse secondary columns below `sm`; keep the key metric on-screen (no horizontal scroll for core data). Detail goes to the profile/expand view.
- Touch targets ≥40px; tap feedback via `active:` states.
