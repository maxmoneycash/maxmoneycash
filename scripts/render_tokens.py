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


def _heading(y, text):
    return (f'<text x="{LEFT}" y="{y}" font-size="11" letter-spacing="2" '
            f'fill="{THEME["muted"]}">{esc(text)}</text>')


def _day(d):
    return datetime.date.fromisoformat(d["period"])


def extra_sections(tokens, colors):
    """(height, draw(y)) pairs, most telling first: what the receipt and the
    rest of this card don't already say. `y` is the section's heading line."""
    t = THEME
    daily = [d for d in tokens["daily"] if re.match(r"^\d{4}-\d{2}-\d{2}$", d.get("period", ""))]
    daily.sort(key=lambda d: d["period"])
    out = []

    # Last 7 days against the 7 before, the week's spend and the daily pace.
    if len(daily) >= 8:
        week, prior = daily[-7:], daily[-14:-7]
        wk = sum(d["totalTokens"] for d in week)
        pr = sum(d["totalTokens"] for d in prior)
        cost = sum(d.get("totalCost") or 0 for d in week)
        avg = sum(d["totalTokens"] for d in daily[-30:]) / max(len(daily[-30:]), 1)
        change = (wk - pr) / pr * 100 if pr else None

        def draw_week(y):
            col = INNER / 3
            delta = "" if change is None else (
                f'<tspan dx="6" fill="{t["phosphor"] if change >= 0 else "#ff7b72"}" font-size="11">'
                f'{"▲" if change >= 0 else "▼"}{abs(change):.0f}%</tspan>')
            cells = [
                (f'{compact(wk)}{delta}', "TOKENS · 7D"),
                (money(cost), "EST. COST · 7D"),
                (f"{compact(avg)}/day", "AVG · 30D"),
            ]
            body = "".join(
                f'<text x="{LEFT + i * col}" y="{y + 30}" font-size="19" font-weight="700" fill="{t["fg"]}">{value}</text>'
                f'<text x="{LEFT + i * col}" y="{y + 47}" font-size="9.5" letter-spacing="1.5" fill="{t["muted"]}">{label}</text>'
                for i, (value, label) in enumerate(cells)
            )
            return _heading(y, "THIS WEEK") + body
        out.append((48, draw_week))

    # Weekly rhythm: average tokens by weekday over the days on record.
    if len(daily) >= 14:
        by = defaultdict(list)
        for d in daily[-35:]:
            by[_day(d).weekday()].append(d["totalTokens"])
        avgs = [sum(by[i]) / len(by[i]) if by[i] else 0 for i in range(7)]
        top = max(avgs) or 1
        best = avgs.index(max(avgs))

        def draw_rhythm(y):
            bw, bh = INNER / 7, 46
            names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            bars = "".join(
                f'<rect x="{LEFT + i * bw + 6:.1f}" y="{y + 12 + bh - max(bh * v / top, 2):.1f}" width="{bw - 12:.1f}" '
                f'height="{max(bh * v / top, 2):.1f}" rx="3" fill="{t["amber"] if i == best else t["phosphor"]}" '
                f'opacity="{1 if i == best else 0.35 + 0.55 * v / top:.2f}"/>'
                f'<text x="{LEFT + i * bw + bw / 2:.1f}" y="{y + 12 + bh + 15}" text-anchor="middle" font-size="10" '
                f'fill="{t["amber"] if i == best else t["muted"]}">{names[i]}</text>'
                for i, v in enumerate(avgs)
            )
            return _heading(y, f"RHYTHM · AVG BY WEEKDAY · BUSIEST {names[best].upper()}") + bars
        out.append((76, draw_rhythm))

    # The last 30 days' model mix, beside the card's lifetime top models.
    fam_tok = defaultdict(int)
    for d in daily[-30:]:
        for b in d.get("modelBreakdowns") or []:
            fam_tok[family_of(b.get("modelName", ""))] += tokens_of(b)
    mix_total = sum(fam_tok.values())
    if mix_total:
        fams = [(k, label, colors[k]) for k, label, _ in FAMILIES + [OTHER] if fam_tok.get(k)]

        def draw_mix(y):
            x, parts = LEFT, []
            for k, _, color in fams:
                w = INNER * fam_tok[k] / mix_total
                parts.append(f'<rect x="{x:.1f}" y="{y + 10}" width="{max(w - 2, 1):.1f}" height="12" rx="3" fill="{color}"/>')
                x += w
            lx = LEFT
            for k, label, color in fams:
                pct = 100 * fam_tok[k] / mix_total
                text = f"{label} {pct:.0f}%" if pct >= 1 else f"{label} <1%"
                parts.append(
                    f'<rect x="{lx}" y="{y + 32}" width="9" height="9" rx="2" fill="{color}"/>'
                    f'<text x="{lx + 14}" y="{y + 40}" font-size="11" fill="{t["fg"]}">{text}</text>')
                lx += 14 + len(text) * 6.7 + 18
            return _heading(y, "MODEL MIX · LAST 30 DAYS") + "".join(parts)
        out.append((44, draw_mix))

    # Records: the busiest day and month on record, and the current run.
    if daily:
        busiest = max(daily, key=lambda d: d["totalTokens"])
        months = [m for m in tokens["monthly"] if m.get("totalTokens")]
        top_month = max(months, key=lambda m: m["totalTokens"]) if months else None
        run = 0
        for d in reversed(daily):
            if d["totalTokens"] <= 0:
                break
            run += 1
        run_label = f"{run}+ days" if run == len(daily) else f"{run} days"

        def draw_records(y):
            rows = [
                ("BUSIEST DAY", f'{_day(busiest):%b %-d}', compact(busiest["totalTokens"])),
                ("BUSIEST MONTH", datetime.date.fromisoformat(top_month["period"] + "-01").strftime("%b %Y") if top_month else "-",
                 compact(top_month["totalTokens"]) if top_month else ""),
                ("ACTIVE RUN", run_label, "every day with tokens"),
            ]
            body = "".join(
                f'<text x="{LEFT}" y="{y + 24 + i * 20}" font-size="11" fill="{t["muted"]}">{label}</text>'
                f'<text x="{LEFT + 150}" y="{y + 24 + i * 20}" font-size="12" fill="{t["fg"]}" font-weight="700">{esc(when)}</text>'
                f'<text x="{LEFT + 270}" y="{y + 24 + i * 20}" font-size="12" fill="{t["phosphor"] if i < 2 else t["muted"]}">{esc(value)}</text>'
                for i, (label, when, value) in enumerate(rows)
            )
            return _heading(y, "RECORDS") + body
        out.append((64, draw_records))

    return out


def render(gh, tokens, target_h=None):
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
    model_tot = defaultdict(lambda: [0, 0, 0.0])
    for m in tokens["monthly"]:
        for b in m["modelBreakdowns"]:
            name = normalize(b["modelName"])
            model_tot[name][0] += tokens_of(b)
            model_tot[name][1] += b["outputTokens"]
            model_tot[name][2] += b.get("cost", 0)
    # Rank by the same number the row prints. Ranking by output while showing
    # traffic made the list read as scrambled — gpt-5.4 has more traffic than
    # kimi-for-coding but less output, so it fell off the cut for no visible
    # reason. The bar still scales to output, which the heading names.
    top = sorted(
        ((name, values) for name, values in model_tot.items() if values[1] > 0),
        key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]),
    )[:8]
    top_max = max((values[1] for _, values in top), default=1) or 1

    tm_y = chart_y + chart_h + 78
    parts.append(
        f'<text x="{LEFT}" y="{tm_y - 14}" font-size="11" letter-spacing="2" '
        f'fill="{t["muted"]}">TOP MODELS · GENERATED OUTPUT</text>'
    )
    for i, (name, (traffic, output, _cost)) in enumerate(top):
        y = tm_y + i * 24
        wfrac = 150 * output / top_max
        color = colors[family_of(name)]
        parts.append(
            f'<text x="{LEFT}" y="{y + 9}" font-size="11" fill="{t["fg"]}">{esc(name[:23])}</text>'
            f'<rect x="{LEFT + 172}" y="{y}" width="{max(wfrac, 2):.1f}" height="11" rx="3" fill="{color}" opacity="0.9"/>'
            f'<text x="{LEFT + 172 + max(wfrac, 2) + 8:.1f}" y="{y + 9}" font-size="10" '
            f'fill="{t["muted"]}">{compact(output)} out · {compact(traffic)} traffic</text>'
        )

    # ---- opencode lab: every model ever tried there ----------------------
    # ccusage reports no model split for opencode, so modelsUsed is empty and
    # this used to render a bare "0 MODELS TESTED". Fall back to the models
    # dict when one exists, and say the split is unavailable rather than
    # claiming zero — opencode has 66M tokens, not none.
    oc_agent = tokens["agents"].get("opencode") or {}
    oc_months = oc_agent.get("monthly") or []
    oc_names = {name for m in oc_months for name in (m.get("modelsUsed") or [])}
    oc_names |= {name for m in oc_months for name in (m.get("models") or {})}
    oc_models = sorted(
        {normalize(name) for name in oc_names},
        key=lambda n: -model_tot.get(n, [0, 0, 0])[1],
    )
    oc_tokens = (oc_agent.get("totals") or {}).get("totalTokens", 0)
    if oc_models:
        oc_heading = f"OPENCODE LAB · {len(oc_models)} MODELS TESTED"
    elif oc_tokens:
        oc_heading = f"OPENCODE LAB · {compact(oc_tokens)} TOK · MODEL SPLIT UNAVAILABLE"
    else:
        oc_heading = "OPENCODE LAB · NO RUNS RECORDED"
    oc_y = tm_y + len(top) * 24 + 38
    parts.append(
        f'<text x="{LEFT}" y="{oc_y - 12}" font-size="11" letter-spacing="2" '
        f'fill="{t["muted"]}">{oc_heading}</text>'
    )
    cx, cy = LEFT, oc_y
    chip_h, chip_gap = 21, 7
    for name in oc_models:
        short = name.split("/")[-1]
        tok = model_tot.get(name, [0, 0, 0])[0]
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
    material_floor = max(1_000, totals["outputTokens"] * 0.005)
    material_models = sum(1 for values in model_tot.values() if values[1] >= material_floor)
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
    # If the receipt next door is naturally taller, anchor the footer lower
    # so both cards end up the same height.
    foot_y = max(d_y + d_h + 30, (target_h or 0) - 26)

    # ---- extra sections: fill the height the receipt gives us -------------
    # As many sections as fit (most telling first), the leftover height shared
    # evenly between them and the footer, so the card never grows past the
    # receipt, never crowds the footer, and never leaves one empty band.
    sections = extra_sections(tokens, colors)
    space = (foot_y - 14) - (d_y + d_h)
    MIN_GAP = 30
    while sections and sum(h for h, _ in sections) + MIN_GAP * (len(sections) + 1) > space:
        sections.pop()
    if sections:
        gap = (space - sum(h for h, _ in sections)) / (len(sections) + 1)
        y = d_y + d_h + gap + 10
        for height, draw in sections:
            parts.append(draw(round(y)))
            y += height + gap

    parts.append(
        f'<text x="{LEFT}" y="{foot_y}" font-size="10.5" fill="{t["muted"]}">'
        f'Σ <tspan fill="{t["phosphor"]}" font-weight="700">{totals["totalTokens"]:,}</tspan> tok'
        f' · cache <tspan fill="{t["phosphor"]}">{cache_pct:.1f}%</tspan>'
        f' · peak <tspan fill="{t["amber"]}">{compact(peak["totalTokens"]) if peak else "-"}</tspan>'
        f' · <tspan fill="{t["value"]}">{material_models}</tspan> output-significant models</text>'
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
<text x="{LEFT}" y="70" font-size="12" fill="{t['muted']}">~ <tspan fill="{t['phosphor']}">❯</tspan> <tspan fill="{t['fg']}">turbotokens monthly --json | jq .monthly</tspan></text>
{"".join(parts)}
<rect width="{W}" height="{H}" rx="14" fill="url(#scan)"/>
</svg>"""
    write_svg("token-ops.svg", svg)
    return H
