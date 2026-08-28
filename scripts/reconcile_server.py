#!/usr/bin/env python3
"""Detect and correct commits.sh server-side token drift.

The server's ledger merge is additive for non-operator publishers and never
re-anchors a headline downward, so app restarts and counter-scope changes can
mint phantom token deltas that accumulate silently. Observed 2026-08-27: the
public total reached 270.7B — 3.88x its own component sum — three days after a
clean 68.2B reconcile, with cost still correct. Only an operator ingest with
``reconcile: true`` re-anchors it (total = max(incoming.total, componentFloor)).

This runs after every collection: compares the server headline to the audited
ledger and posts an authoritative reconcile when they diverge by more than
DRIFT_THRESHOLD. Within one 15-minute collector cycle any future re-inflation
self-heals instead of sitting wrong for days.

The operator token is read from the login Keychain (service: cm-ingest-token),
never from the repo or environment files.

Usage: reconcile_server.py [--force] [--dry-run]
Exit 0 on no-drift or successful reconcile; 1 on failure to check or post.
"""
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


def main():
    force = "--force" in sys.argv
    dry = "--dry-run" in sys.argv

    ledger = json.loads(LEDGER.read_text())
    audited = ledger["totals"]["totalTokens"]
    try:
        current = server_total()
    except Exception as exc:
        print(f"reconcile: server unreachable ({exc}); skipping")
        return 1

    drift = abs(current - audited) / audited
    print(f"reconcile: server {current:,} vs ledger {audited:,} ({drift:+.2%} drift)")
    if drift <= DRIFT_THRESHOLD and not force:
        print("reconcile: within threshold; nothing to do")
        return 0

    token = keychain_token()
    if not token:
        print("reconcile: DRIFT DETECTED but no Keychain token (service cm-ingest-token)")
        return 1
    payload = build_payload(ledger)
    if dry:
        print("reconcile: dry run; would post authoritative reconcile")
        return 0

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
