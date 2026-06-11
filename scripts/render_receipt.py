"""Thermal-paper receipt: the all-time AI compute bill, with a granular
token ledger (output by agent, all four token buckets)."""
import datetime
import hashlib
import re
from collections import defaultdict

from common import AGENT_LABELS, compact, esc, money, write_svg

PAPER = "#f7f3e9"
INK = "#211c16"
FAINT = "#6b6256"
MONO = "ui-monospace,'JetBrains Mono','SF Mono',Menlo,Consolas,monospace"

# Canvas matches token-ops (560 wide) so the two cards keep the same
# rendered height side by side on desktop and stacked on mobile.
W = 560
PAPER_W = 440
PAPER_X = (W - PAPER_W) // 2
PAD = PAPER_X + 36
LH = 19


def _barcode(seed, width_chars):
    digest = hashlib.sha1(seed.encode()).hexdigest()
    patterns = ["|", "||", "| ", " ||", "|||", " |"]
    raw = "".join(patterns[int(c, 16) % len(patterns)] for c in digest)
    return raw[:width_chars]


class Paper:
    def __init__(self):
        self.lines = []  # (kind, payload)

    def center(self, text, size=13, bold=False, color=INK, gap=LH):
        self.lines.append(("center", (text, size, bold, color, gap)))

    def kv(self, k, v, bold=False, gap=LH, color=INK):
        self.lines.append(("kv", (k, v, bold, gap, color)))

    def rule(self, heavy=False, gap=LH):
        self.lines.append(("rule", (heavy, gap)))

    def space(self, gap=10):
        self.lines.append(("space", gap))

    def render(self, y0):
        out, y = [], y0
        for kind, p in self.lines:
            if kind == "space":
                y += p
                continue
            if kind == "rule":
                heavy, gap = p
                ch = "━" if heavy else "─"
                out.append(
                    f'<text x="{W / 2}" y="{y}" text-anchor="middle" font-size="13" '
                    f'fill="{INK if heavy else FAINT}" xml:space="preserve">{ch * 27}</text>'
                )
                y += gap
                continue
            if kind == "center":
                text, size, bold, color, gap = p
                weight = ' font-weight="700"' if bold else ""
                out.append(
                    f'<text x="{W / 2}" y="{y}" text-anchor="middle" font-size="{size}" '
                    f'fill="{color}"{weight}>{esc(text)}</text>'
                )
                y += gap
                continue
            k, v, bold, gap, color = p
            weight = ' font-weight="700"' if bold else ""
            out.append(
                f'<g font-size="13"{weight}>'
                f'<text x="{PAD}" y="{y}" fill="{color}">{esc(k)}</text>'
                f'<text x="{W - PAD}" y="{y}" text-anchor="end" fill="{color}">{esc(v)}</text></g>'
            )
            y += gap
        return "\n".join(out), y

    def height(self, y0):
        return self.render(y0)[1]


def _paper_outline(h):
    """Receipt silhouette: zig-zag torn top and bottom edges."""
    step, amp = 14, 7
    top, bottom = [], []
    x, up = PAPER_X, True
    while x <= PAPER_X + PAPER_W:
        top.append((x, 6 + (amp if up else 0)))
        bottom.append((x, h - 6 - (amp if not up else 0)))
        up = not up
        x += step
    pts = [f"{x},{y}" for x, y in top]
    pts += [f"{x},{y}" for x, y in reversed(bottom)]
    return " ".join(pts)


def _build(tokens):
    totals = tokens["totals"]
    agents = tokens["agents"]
    now = datetime.datetime.now(datetime.timezone.utc)
    receipt_id = f"MMC_{now:%Y%m%d}_{hashlib.sha1(str(totals['totalTokens']).encode()).hexdigest()[:6].upper()}"
    first = datetime.datetime.strptime(tokens["monthly"][0]["period"], "%Y-%m")
    last = datetime.datetime.strptime(tokens["monthly"][-1]["period"], "%Y-%m")

    # Unified per-model totals (for the Claude generation split).
    model_tot = defaultdict(int)
    for m in tokens["monthly"]:
        for b in m["modelBreakdowns"]:
            name = re.sub(r"-\d{8}$", "", b["modelName"])
            model_tot[name] += (
                b["inputTokens"] + b["outputTokens"]
                + b.get("cacheCreationTokens", 0) + b.get("cacheReadTokens", 0)
            )

    CLAUDE_SPLIT = [
        ("  · OPUS 4.7", "claude-opus-4-7"),
        ("  · OPUS 4.8", "claude-opus-4-8"),
        ("  · FABLE 5", "claude-fable-5"),
    ]

    p = Paper()
    p.space(20)
    p.center("MAXMONEYCASH", 17, bold=True, gap=24)
    p.center("AI COMPUTE STATEMENT", 11, color=FAINT, gap=18)
    p.center(f"BILLING PERIOD: {first:%b %Y} — {last:%b %Y}".upper(), 11, color=FAINT, gap=20)
    p.rule()
    p.kv("STATEMENT #", receipt_id)
    p.kv("ISSUED", f"{now:%Y-%m-%d %H:%M} UTC")
    p.kv("BILLED TO", "MAX @MAXMONEYCASH")
    p.kv("SERVED BY", "5 CODING AGENTS")
    p.rule(heavy=True)
    p.kv("ITEM", "TOKENS", bold=True)
    p.rule()

    ordered = sorted(
        agents.items(), key=lambda kv: -(kv[1]["totals"].get("totalTokens") or 0)
    )
    for name, a in ordered:
        p.kv(AGENT_LABELS[name], compact(a["totals"].get("totalTokens") or 0))
        if name == "claude":
            for label, model in CLAUDE_SPLIT:
                if model_tot.get(model):
                    p.kv(label, compact(model_tot[model]), gap=17)
    p.kv("GROK BUILD", "0")
    p.rule()
    p.kv("SUBTOTAL", f"{compact(totals['totalTokens'])} TOK", bold=True)

    # ---- granular token ledger ------------------------------------------
    p.rule(heavy=True)
    p.kv("LEDGER", "READ vs WRITTEN", bold=True)
    p.rule()
    out_total = totals["outputTokens"]
    p.kv("OUTPUT (WRITTEN)", compact(out_total), bold=True)
    for name, a in ordered:
        out_a = a["totals"].get("outputTokens") or 0
        pct = 100 * out_a / out_total if out_total else 0
        p.kv(f"  · {AGENT_LABELS[name]}", f"{compact(out_a)} ({pct:.0f}%)", gap=17)
    novels = out_total * 0.75 / 90_000
    p.kv("  ≈ NOVELS WRITTEN", f"{novels:,.0f}", gap=20, color=FAINT)
    p.kv("FRESH INPUT (READ)", compact(totals["inputTokens"]))
    p.kv("CACHE WRITES", compact(totals["cacheCreationTokens"]))
    cache_pct = 100 * totals["cacheReadTokens"] / totals["totalTokens"]
    p.kv("CACHE READS", compact(totals["cacheReadTokens"]))
    p.kv("  · CONTEXT RE-READ", f"{cache_pct:.1f}% OF ALL TOK", gap=20, color=FAINT)
    reasoning = totals["totalTokens"] - sum(
        totals.get(c, 0)
        for c in ("inputTokens", "outputTokens", "cacheCreationTokens", "cacheReadTokens")
    )
    if reasoning > 100_000:
        p.kv("REASONING (DROID)", compact(reasoning), gap=20)
    p.rule(heavy=True)
    p.kv("TOTAL USD", money(totals["totalCost"], cents=True), bold=True, gap=24)
    months_active = max(len(tokens["monthly"]), 1)
    p.kv("AVG / MONTH", money(totals["totalCost"] / months_active, cents=True), gap=20)
    p.rule()
    p.center(f"{compact(totals['totalTokens'])} TOKENS.", 12, gap=LH)
    p.center("ZERO REGRETS.", 12, gap=22)
    p.center(_barcode(receipt_id, 38), 14, gap=16)
    p.center(receipt_id, 10, color=FAINT, gap=20)
    p.center("★ PAID IN FULL · NO REFUNDS ★", 12, bold=True, gap=14)
    return p


def natural_height(gh, tokens):
    return _build(tokens).height(58) + 30


def render(gh, tokens, target_h=None):
    p = _build(tokens)

    # Stretch to target_h (token-ops height) by padding around the total
    # block and before the barcode, so both cards share an aspect ratio.
    if target_h:
        natural = p.height(58) + 30
        extra = max(target_h - natural, 0)
        slots = [i for i, (kind, _) in enumerate(p.lines) if kind == "rule"]
        if len(slots) >= 2 and extra:
            a, b = slots[-2], slots[-1]
            p.lines.insert(b + 1, ("space", extra / 2))
            p.lines.insert(a, ("space", extra / 2))

    body, y_end = p.render(58)
    H = max(y_end + 30, target_h or 0)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" font-family="{MONO}">
<defs>
  <filter id="drop" x="-20%" y="-20%" width="140%" height="140%">
    <feDropShadow dx="0" dy="5" stdDeviation="7" flood-color="#000" flood-opacity="0.45"/>
  </filter>
</defs>
<polygon points="{_paper_outline(H)}" fill="{PAPER}" filter="url(#drop)"/>
{body}
</svg>"""
    write_svg("receipt.svg", svg)
