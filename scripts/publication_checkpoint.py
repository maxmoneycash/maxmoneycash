"""Decide when collected data needs publishing, relative to origin/main.

Local scans are committed even when a push is deferred. Their timestamps and
counters must not reset the publication threshold or freshness deadline.
"""
import argparse
import datetime
import json
import pathlib
import subprocess


PUBLISHED_REF = "refs/remotes/origin/main"


def coordinates(ledger):
    total = ledger["totals"]["totalTokens"]
    if isinstance(total, bool) or not isinstance(total, int) or total <= 0:
        raise ValueError("ledger total must be a positive integer")
    generated = datetime.datetime.strptime(ledger["generated_at"], "%Y-%m-%dT%H:%M:%SZ")
    return total, generated.replace(tzinfo=datetime.timezone.utc)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, timeout=15)


def decide(repo, threshold=25_000_000, max_age=3600, now=None):
    if threshold < 0 or max_age < 0:
        raise ValueError("publication threshold and age must be nonnegative")
    repo = pathlib.Path(repo)
    current_total, _ = coordinates(json.loads((repo / "data/tokens.json").read_text()))
    now = now or datetime.datetime.now(datetime.timezone.utc)
    ref = git(repo, "rev-parse", "--verify", PUBLISHED_REF)
    if ref.returncode:
        return True, "no confirmed published checkpoint; pushing"

    pending = git(repo, "rev-list", "--count", f"{PUBLISHED_REF}..HEAD")
    if pending.returncode:
        raise RuntimeError("could not inspect unpublished commits")
    if int(pending.stdout) == 0:
        return False, "no unpublished commits; nothing to push"

    published = git(repo, "show", f"{PUBLISHED_REF}:data/tokens.json")
    try:
        if published.returncode:
            raise ValueError("published ledger unavailable")
        published_total, published_at = coordinates(json.loads(published.stdout))
    except (KeyError, TypeError, ValueError):
        return True, "published checkpoint is missing or unreadable; pushing"

    delta = current_total - published_total
    age = int((now - published_at).total_seconds())
    if age < -300:
        return True, "published checkpoint is in the future; refreshing it"
    if age >= max_age:
        return True, f"published ledger age {age}s >= {max_age}s; pushing"
    if delta >= threshold:
        return True, f"unpublished delta {delta} >= {threshold}; pushing"
    return False, (f"unpublished delta {delta} < {threshold}, published ledger age "
                   f"{age}s < {max_age}s; deferring push")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=pathlib.Path, required=True)
    parser.add_argument("--threshold", type=int, default=25_000_000)
    parser.add_argument("--max-age", type=int, default=3600)
    args = parser.parse_args()
    try:
        publish, reason = decide(args.repo, args.threshold, args.max_age)
    except (OSError, KeyError, TypeError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"publication check failed: {exc}")
        return 1
    print(reason)
    return 0 if publish else 3


if __name__ == "__main__":
    raise SystemExit(main())
