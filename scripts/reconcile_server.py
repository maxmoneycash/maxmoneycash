#!/usr/bin/env python3
"""Detect and correct commits.sh server-side token drift.

The server's ledger merge is additive for non-operator publishers and never
re-anchors a headline downward, so app restarts and counter-scope changes can
mint phantom token deltas that accumulate silently. Observed 2026-08-27: the
public total reached 270.7B — 3.88x its own component sum — three days after a
clean 68.2B reconcile, with cost still correct. Only an operator ingest with
``reconcile: true`` re-anchors it (total = max(incoming.total, componentFloor)).

This runs before every collection: compares the server headline to the audited
ledger and posts an authoritative reconcile when they diverge. A reconcile sets
every server counter exactly (lower included) and erases other publishers'
state, so it is only allowed when the ledger can be trusted to be current:

  - the ledger must be fresh: generated_at at most MAX_LEDGER_AGE (2 h) old.
    A frozen ledger (collection refused for days, e.g. after the 2026-10-12
    transcript purge) must never pull production back to an old value.
  - RAISE production when it is more than DRIFT_THRESHOLD (2%) below the ledger.
  - LOWER production only when it is at least LOWER_RATIO (1.10x) the ledger.
    Every past inflation was a whole multiple (1.87x, 3.88x, ~1.97x); a few
    percent above the ledger is live usage the ledger has not caught up with.

The operator token is read from the login Keychain (service: cm-ingest-token),
never from the repo or environment files, and only when a POST will be sent.

Usage: reconcile_server.py [--dry-run] [--force] [--ledger PATH]
  --dry-run  print the decision and the would-be payload totals; never reads
             the Keychain, never POSTs
  --force    post even inside the thresholds (never with a stale ledger)
  --ledger   audit a different tokens.json (default data/tokens.json)
Exit 0: nothing to do, dry run, or reconcile accepted. 1: server unreachable,
no token, or POST failed. 2: refused (stale or unusable ledger).
"""
import datetime
import json
import pathlib
import subprocess
import sys
from collections import defaultdict

HANDLE = "maxmoneycash"
API = "https://commits.sh"
LEDGER = pathlib.Path(__file__).resolve().parent.parent / "data" / "tokens.json"
# Live drift between a 2s pulse and a committed artifact is <0.2%; restart
# minting shows up as whole multiples. 2% separates them with a wide margin.
DRIFT_THRESHOLD = 0.02
# Lower production only at a whole-multiple-like inflation, never on a few
# percent of not-yet-collected live usage.
LOWER_RATIO = 1.10
MAX_LEDGER_AGE = datetime.timedelta(hours=2)
MAX_MODEL_ROWS = 128


def keychain_token():
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", "cm-ingest-token", "-w"],
            capture_output=True, text=True, timeout=10,
        )
        token = out.stdout.strip()
        return token if out.returncode == 0 and token else None
    except Exception:
        return None


def _curl(args, timeout):
    """HTTP via curl: it uses the macOS system trust store, so this works under
    launchd too — the launchd PATH resolves python3 to an interpreter without a
    certificate bundle, and urllib fails there with CERTIFICATE_VERIFY_FAILED."""
    out = subprocess.run(["curl", "-sS", "--max-time", str(timeout), *args],
                         capture_output=True, text=True, timeout=timeout + 10)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"curl exit {out.returncode}")
    return json.loads(out.stdout)


def server_total():
    return _curl([f"{API}/api/usage?handle={HANDLE}"], 20)["tokens"]["total"]


def build_payload(ledger):
    totals = ledger["totals"]
    agg = defaultdict(lambda: {"in": 0, "out": 0, "cacheRead": 0, "cacheWrite": 0, "cost": 0.0})
    for month in ledger["monthly"]:
        for row in month.get("modelBreakdowns", []):
            a = agg[row["modelName"]]
            a["in"] += row.get("inputTokens", 0) or 0
            a["out"] += row.get("outputTokens", 0) or 0
            a["cacheRead"] += row.get("cacheReadTokens", 0) or 0
            a["cacheWrite"] += row.get("cacheCreationTokens", 0) or 0
            # listValue so no priceable row lands as $0 and gets re-estimated.
            a["cost"] += row.get("listValue", row.get("cost", 0)) or 0
    by_model = sorted(
        ({"name": name, **values} for name, values in agg.items()),
        key=lambda r: -(r["in"] + r["out"] + r["cacheRead"] + r["cacheWrite"]),
    )[:MAX_MODEL_ROWS]
    return {
        "handle": HANDLE,
        "reconcile": True,
        "tokens": {
            "total": totals["totalTokens"],
            "cost_usd_total": round(totals.get("listValueUsd", totals["totalCost"]), 6),
            "input_total": totals["inputTokens"],
            "output_total": totals["outputTokens"],
            "cache_read_total": totals["cacheReadTokens"],
            "cache_write_total": totals["cacheCreationTokens"],
            "apps_used": len(ledger.get("agents", {})),
            "models_used": len(agg),
            "by_model": by_model,
            "by_agent": sorted(
                ({"name": n, "tokens": a["totals"]["totalTokens"]}
                 for n, a in ledger.get("agents", {}).items()),
                key=lambda r: -r["tokens"],
            ),
        },
    }


def parse_time(value):
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return None


def ledger_age(ledger, now):
    generated = parse_time(ledger.get("generated_at"))
    return None if generated is None else now - generated


def stale_reason(ledger, now):
    age = ledger_age(ledger, now)
    if age is None:
        return f"ledger generated_at {ledger.get('generated_at')!r} is unreadable"
    if age > MAX_LEDGER_AGE:
        hours = age.total_seconds() / 3600
        return (f"ledger generated_at {ledger['generated_at']} is {hours:.1f}h old "
                f"(limit {MAX_LEDGER_AGE.total_seconds() / 3600:g}h)")
    if age < -datetime.timedelta(minutes=5):
        return f"ledger generated_at {ledger['generated_at']} is in the future"
    return None


def decide(server, audited, force=False):
    """Return (action, reason); action is one of none / raise / lower."""
    ratio = server / audited
    if server < audited * (1 - DRIFT_THRESHOLD):
        return "raise", f"server {ratio:.4f}x ledger, more than {DRIFT_THRESHOLD:.0%} low"
    if ratio >= LOWER_RATIO:
        return "lower", f"server {ratio:.4f}x ledger, at or above the {LOWER_RATIO:.2f}x lowering floor"
    if force and server != audited:
        return ("raise" if server < audited else "lower"), f"forced at {ratio:.4f}x"
    if server > audited * (1 + DRIFT_THRESHOLD):
        return "none", (f"server {ratio:.4f}x ledger: above, but below the "
                        f"{LOWER_RATIO:.2f}x lowering floor; not lowering")
    return "none", f"server {ratio:.4f}x ledger, within {DRIFT_THRESHOLD:.0%}"


def payload_summary(payload):
    t = payload["tokens"]
    return (f"total={t['total']:,} cost_usd_total={t['cost_usd_total']:,.2f} "
            f"input={t['input_total']:,} output={t['output_total']:,} "
            f"cache_read={t['cache_read_total']:,} cache_write={t['cache_write_total']:,} "
            f"models={t['models_used']} apps={t['apps_used']}")


def main(argv=None, now=None):
    argv = sys.argv[1:] if argv is None else argv
    force = "--force" in argv
    dry = "--dry-run" in argv
    ledger_path = LEDGER
    if "--ledger" in argv:
        ledger_path = pathlib.Path(argv[argv.index("--ledger") + 1])
    now = now or datetime.datetime.now(datetime.timezone.utc)

    ledger = json.loads(pathlib.Path(ledger_path).read_text())
    audited = ledger["totals"]["totalTokens"]
    reason = stale_reason(ledger, now)
    if reason is None and not audited > 0:
        reason = f"ledger total {audited!r} is not positive"
    if reason:
        print(f"reconcile: REFUSED, not posting: {reason}")
        return 2

    try:
        current = server_total()
    except Exception as exc:
        print(f"reconcile: server unreachable ({exc}); skipping")
        return 1

    drift = (current - audited) / audited
    print(f"reconcile: server {current:,} vs ledger {audited:,} ({drift:+.2%} drift)")
    action, why = decide(current, audited, force)
    if action == "none":
        print(f"reconcile: nothing to do ({why})")
        return 0

    payload = build_payload(ledger)
    verb = "raise" if action == "raise" else "lower"
    if dry:
        print(f"reconcile: dry run; WOULD POST a reconcile to {verb} production "
              f"{current:,} -> {audited:,} ({why})")
        print(f"reconcile: dry run payload {payload_summary(payload)}")
        return 0

    token = keychain_token()
    if not token:
        print(f"reconcile: {verb} needed ({why}) but no Keychain token (service cm-ingest-token)")
        return 1
    print(f"reconcile: posting to {verb} production ({why})")
    body = _curl([
        "-X", "POST", f"{API}/api/ingest",
        "-H", f"authorization: Bearer {token}",
        "-H", "content-type: application/json",
        "--data-binary", json.dumps(payload),
    ], 30)
    accepted = (body.get("accepted") or {}).get("total")
    ok = body.get("reconciled") is True and accepted == audited
    print(f"reconcile: posted, reconciled={body.get('reconciled')} accepted={accepted:,}"
          if accepted else f"reconcile: unexpected response {body}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
