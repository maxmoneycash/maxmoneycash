"""Thermal-paper receipt card for all-time token spend."""
import datetime
import hashlib

from common import AGENT_LABELS, compact, esc, money, write_svg

PAPER = "#f7f3e9"
INK = "#211c16"
FAINT = "#6b6256"
MONO = "ui-monospace,'JetBrains Mono','SF Mono',Menlo,Consolas,monospace"

W = 420
PAD = 34
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

    def kv(self, k, v, bold=False, gap=LH):
        self.lines.append(("kv", (k, v, bold, gap)))

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
            k, v, bold, gap = p
            weight = ' font-weight="700"' if bold else ""
            out.append(
                f'<g font-size="13"{weight}>'
                f'<text x="{PAD}" y="{y}" fill="{INK}">{esc(k)}</text>'
                f'<text x="{W - PAD}" y="{y}" text-anchor="end" fill="{INK}">{esc(v)}</text></g>'
            )
            y += gap
        return "\n".join(out), y


def _paper_outline(h):
    """Receipt silhouette: zig-zag torn top and bottom edges."""
    step, amp = 14, 7
    top, bottom = [], []
    x, up = 0, True
    while x <= W:
        top.append((x, amp if up else 0))
        bottom.append((x, h - (amp if not up else 0)))
        up = not up
        x += step
    pts = [f"{x},{y}" for x, y in top]
    pts += [f"{x},{y}" for x, y in reversed(bottom)]
    return " ".join(pts)


def render(gh, tokens):
    totals = tokens["totals"]
    agents = tokens["agents"]
    now = datetime.datetime.now(datetime.timezone.utc)
    receipt_id = f"MMC_{now:%Y%m%d}_{hashlib.sha1(str(totals['totalTokens']).encode()).hexdigest()[:6].upper()}"

    p = Paper()
    p.space(16)
    p.center("MAXMONEYCASH COMPUTE CO.", 16, bold=True, gap=24)
    p.center("ARTISANAL TOKENS · SMALL BATCH", 11, color=FAINT, gap=18)
    p.center("SAN FRANCISCO TERMINAL NO. 1", 11, color=FAINT, gap=20)
    p.rule()
    p.kv("RECEIPT #", receipt_id)
    p.kv("DATE", f"{now:%Y-%m-%d %H:%M} UTC")
    p.kv("CASHIER", "5 CODING AGENTS")
    p.rule(heavy=True)
    p.kv("ITEM", "TOKENS", bold=True)
    p.rule()

    # Unified per-model totals (for the Claude generation split).
    import re
    from collections import defaultdict

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

    ordered = sorted(
        agents.items(), key=lambda kv: -(kv[1]["totals"].get("totalTokens") or 0)
    )
    for name, a in ordered:
        p.kv(AGENT_LABELS[name], compact(a["totals"].get("totalTokens") or 0))
        if name == "claude":
            for label, model in CLAUDE_SPLIT:
                if model_tot.get(model):
                    p.kv(label, compact(model_tot[model]), gap=17)
    p.kv("GROK BUILD", "UNTRACKED*")
    p.rule()
    p.kv("SUBTOTAL", f"{compact(totals['totalTokens'])} TOK", bold=True)
    cache_pct = 100 * totals["cacheReadTokens"] / totals["totalTokens"]
    p.kv("CACHE READS", f"{compact(totals['cacheReadTokens'])} ({cache_pct:.1f}%)")
    p.kv("OUTPUT TOK", compact(totals["outputTokens"]))
    p.rule(heavy=True)
    p.kv("TOTAL USD", money(totals["totalCost"], cents=True), bold=True, gap=24)
    p.kv("PRICE DATE", f"{now:%Y-%m-%d} · LITELLM", gap=20)
    p.rule()
    p.center("THE LOGO LOOKS CALM.", 12, gap=LH)
    p.center("THE BILL DOES NOT.", 12, gap=22)
    p.center(_barcode(receipt_id, 38), 14, gap=16)
    p.center(receipt_id, 10, color=FAINT, gap=20)
    p.center("★ THANK YOU FOR VIBING ★", 12, bold=True, gap=14)
    p.center("*grok stores no local token counts", 9, color=FAINT, gap=10)

    body, y_end = p.render(58)
    H = y_end + 26

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
