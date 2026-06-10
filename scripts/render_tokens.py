"""Phosphor token-ops dashboard: monthly bars, top models, OpenCode lab, 30-day burn."""
import datetime
import re
from collections import defaultdict

from common import THEME, compact, esc, money, write_svg

MONO = "ui-monospace,'JetBrains Mono','SF Mono',Menlo,Consolas,monospace"

# Model-name → family bucket (per-month agent splits aren't in the unified
# ccusage JSON, but model families map cleanly onto the tools that ran them).
FAMILIES = [
    ("claude", "Claude", "#d97757"),
    ("gpt", "GPT", "#19c37d"),
    ("kimi", "Kimi", "#a371f7"),
    ("glm", "GLM", "#58a6ff"),
]
OTHER = ("other", "Other", "#8b949e")

W = 560
LEFT = 46
INNER = 470  # usable width inside the card


def family_of(model):
    m = model.lower()
    if "claude" in m or "haiku" in m or "opus" in m or "sonnet" in m or "fable" in m:
        return "claude"
    if "gpt" in m or "codex" in m:
        return "gpt"
    if "kimi" in m:
        return "kimi"
    if "glm" in m:
        return "glm"
    return "other"


def normalize(model):
    """Collapse vendor date-suffixes and dash/dot variants of the same model."""
    m = re.sub(r"-\d{8}$", "", model)  # claude-opus-4-5-20251101 → claude-opus-4-5
    m = re.sub(r"^gpt-(\d)-(\d)-", r"gpt-\1.\2-", m)  # gpt-5-3-codex → gpt-5.3-codex
    return m


def tokens_of(b):
    return (b["inputTokens"] + b["outputTokens"]
            + b.get("cacheCreationTokens", 0) + b.get("cacheReadTokens", 0))


def render(gh, tokens):
    t = THEME
    months = tokens["monthly"][-9:]
    daily = tokens["daily"][-30:]
    totals = tokens["totals"]
    parts = []

    # ---- monthly stacked bars -------------------------------------------
    stacks, max_total = [], 1
    for m in months:
        per = defaultdict(int)
        for b in m["modelBreakdowns"]:
            per[family_of(b["modelName"])] += tokens_of(b)
        stacks.append((m["period"], per, m["totalTokens"]))
        max_total = max(max_total, m["totalTokens"])

    chart_y, chart_h = 92, 180
    bar_gap = 14
    bar_w = (INNER - bar_gap * (len(stacks) - 1)) / len(stacks)
    order = [f[0] for f in FAMILIES] + [OTHER[0]]
    colors = {k: c for k, _, c in FAMILIES} | {OTHER[0]: OTHER[2]}
    for i, (period, per, total) in enumerate(stacks):
        x = LEFT + i * (bar_w + bar_gap)
        y = chart_y + chart_h
        for fam in order:
            v = per.get(fam, 0)
            if not v:
                continue
            h = chart_h * v / max_total
            y -= h
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{max(h, 1.5):.1f}" '
                f'rx="2" fill="{colors[fam]}"/>'
            )
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{y - 7:.1f}" text-anchor="middle" '
            f'font-size="9" fill="{t["phosphor"]}">{compact(total)}</text>'
        )
        label = datetime.datetime.strptime(period, "%Y-%m").strftime("%b")
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{chart_y + chart_h + 16}" text-anchor="middle" '
            f'font-size="10" fill="{t["muted"]}">{label}</text>'
        )

    lx = LEFT
    for key, label, color in FAMILIES + [OTHER]:
        parts.append(
            f'<rect x="{lx}" y="{chart_y + chart_h + 30}" width="9" height="9" rx="2" fill="{color}"/>'
            f'<text x="{lx + 14}" y="{chart_y + chart_h + 38}" font-size="10" fill="{t["fg"]}">{label}</text>'
        )
        lx += 14 + len(label) * 7 + 22

    # ---- top models all-time (normalized → opus 4.7 vs 4.8 separate) ----
    model_tot = defaultdict(lambda: [0, 0.0])
    for m in tokens["monthly"]:
        for b in m["modelBreakdowns"]:
            name = normalize(b["modelName"])
            model_tot[name][0] += tokens_of(b)
            model_tot[name][1] += b.get("cost", 0)
    top = sorted(model_tot.items(), key=lambda kv: -kv[1][0])[:8]
    top_max = top[0][1][0] if top else 1

    tm_y = chart_y + chart_h + 78
    parts.append(
        f'<text x="{LEFT}" y="{tm_y - 14}" font-size="11" letter-spacing="2" '
        f'fill="{t["muted"]}">TOP MODELS · ALL-TIME</text>'
    )
    for i, (name, (tok, cost)) in enumerate(top):
        y = tm_y + i * 24
        wfrac = 150 * tok / top_max
        color = colors[family_of(name)]
        parts.append(
            f'<text x="{LEFT}" y="{y + 9}" font-size="11" fill="{t["fg"]}">{esc(name[:23])}</text>'
            f'<rect x="{LEFT + 172}" y="{y}" width="{max(wfrac, 2):.1f}" height="11" rx="3" fill="{color}" opacity="0.9"/>'
            f'<text x="{LEFT + 172 + max(wfrac, 2) + 8:.1f}" y="{y + 9}" font-size="10" '
            f'fill="{t["muted"]}">{compact(tok)} · {money(cost)}</text>'
        )

    # ---- opencode lab: every model ever tried there ----------------------
    oc_months = tokens["agents"]["opencode"].get("monthly") or []
    oc_models = sorted(
        {normalize(name) for m in oc_months for name in m.get("modelsUsed", [])},
        key=lambda n: -model_tot.get(n, [0, 0])[0],
    )
    oc_y = tm_y + len(top) * 24 + 38
    parts.append(
        f'<text x="{LEFT}" y="{oc_y - 12}" font-size="11" letter-spacing="2" '
        f'fill="{t["muted"]}">OPENCODE LAB · {len(oc_models)} MODELS TESTED</text>'
    )
    cx, cy = LEFT, oc_y
    chip_h, chip_gap = 21, 7
    for name in oc_models:
        short = name.split("/")[-1]
        tok = model_tot.get(name, [0, 0])[0]
        label = f"{short} · {compact(tok)}" if tok else short
        cw = round(len(label) * 6.3) + 18
        if cx + cw > LEFT + INNER:
            cx = LEFT
            cy += chip_h + chip_gap
        color = colors[family_of(name)]
        parts.append(
            f'<rect x="{cx}" y="{cy}" width="{cw}" height="{chip_h}" rx="10.5" '
            f'fill="{t["panel"]}" stroke="{color}" stroke-opacity="0.55"/>'
            f'<text x="{cx + cw / 2}" y="{cy + 14}" text-anchor="middle" font-size="10" '
            f'fill="{t["fg"]}">{esc(label)}</text>'
        )
        cx += cw + chip_gap
    oc_end = cy + chip_h

    # ---- last 30 days ----------------------------------------------------
    d_y = oc_end + 44
    d_h = 60
    d_max = max((d["totalTokens"] for d in daily), default=1)
    parts.append(
        f'<text x="{LEFT}" y="{d_y - 10}" font-size="11" letter-spacing="2" '
        f'fill="{t["muted"]}">LAST 30 DAYS · TOKENS/DAY</text>'
    )
    dw = INNER / max(len(daily), 1)
    for i, d in enumerate(daily):
        h = max(d_h * d["totalTokens"] / d_max, 2)
        x = LEFT + i * dw
        last = i == len(daily) - 1
        parts.append(
            f'<rect x="{x:.1f}" y="{d_y + d_h - h:.1f}" width="{dw - 3:.1f}" height="{h:.1f}" '
            f'rx="2" fill="{t["amber"] if last else t["phosphor"]}" '
            f'opacity="{1 if last else 0.35 + 0.65 * d["totalTokens"] / d_max:.2f}"/>'
        )

    peak = max(tokens["daily"], key=lambda d: d["totalTokens"], default=None)
    cache_pct = 100 * totals["cacheReadTokens"] / totals["totalTokens"]
    foot_y = d_y + d_h + 30
    parts.append(
        f'<text x="{LEFT}" y="{foot_y}" font-size="11" fill="{t["muted"]}">'
        f'cache hit <tspan fill="{t["phosphor"]}">{cache_pct:.1f}%</tspan>'
        f' · peak day <tspan fill="{t["amber"]}">{compact(peak["totalTokens"]) if peak else "-"}</tspan>'
        f' · models all-time <tspan fill="{t["value"]}">{len(model_tot)}</tspan></text>'
    )

    H = foot_y + 26
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" font-family="{MONO}">
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{t['bg']}"/><stop offset="1" stop-color="{t['bg2']}"/>
  </linearGradient>
  <pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse">
    <rect width="4" height="2" fill="#000" opacity="0.14"/>
  </pattern>
</defs>
<rect width="{W}" height="{H}" rx="14" fill="url(#bg)" stroke="{t['border']}"/>
<circle cx="24" cy="24" r="6" fill="#ff5f56"/><circle cx="44" cy="24" r="6" fill="#ffbd2e"/><circle cx="64" cy="24" r="6" fill="#27c93f"/>
<text x="{W / 2}" y="28" text-anchor="middle" font-size="12" fill="{t['muted']}">token-ops</text>
<line x1="0" y1="42" x2="{W}" y2="42" stroke="{t['border']}"/>
<text x="{LEFT}" y="70" font-size="12" fill="{t['muted']}">~ <tspan fill="{t['phosphor']}">❯</tspan> <tspan fill="{t['fg']}">ccusage monthly --json | jq .monthly</tspan></text>
{"".join(parts)}
<rect width="{W}" height="{H}" rx="14" fill="url(#scan)"/>
</svg>"""
    write_svg("token-ops.svg", svg)
