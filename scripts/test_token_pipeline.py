#!/usr/bin/env python3
import contextlib
import datetime
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from collections import defaultdict


ROOT = pathlib.Path(__file__).resolve().parent


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


codex = load_module("codex_true_usage")
merge = load_module("merge_token_sources")
build = load_module("build_tokens_json")
hermes = load_module("hermes_true_usage")
grok_usage = load_module("grok_true_usage")
common = load_module("common")
accounting = load_module("token_accounting")
baseline = load_module("make_cloud_baseline")
purge = load_module("make_purge_baseline")
reconcile = load_module("reconcile_server")
cursor_usage = load_module("cursor_usage")
audit_guard = load_module("audit_dir_guard")
agent_drops = load_module("agent_drops")
heatmaps = load_module("render_heatmaps")

COMPONENT_KEYS = ["inputTokens", "outputTokens", "cacheCreationTokens", "cacheReadTokens"]


def usage_row(values, cost=0.0):
    row = dict(zip(COMPONENT_KEYS, values))
    row["totalTokens"] = sum(values)
    row["cost"] = cost
    return row


def write_scan(directory, usage, daily):
    """Write a collector input dir from {agent: {month: {model: (i, o, cw, cr)}}}.

    Claude rows carry a quoted cost; Codex rows report zero (subscription)."""
    directory.mkdir(parents=True, exist_ok=True)
    cost_of = lambda agent, v: round((v[0] + v[1]) / 1000, 6) if agent == "claude" else 0.0
    months = sorted({m for per_agent in usage.values() for m in per_agent})
    monthly = []
    for month in months:
        breakdowns, agents = [], []
        for agent in sorted(usage):
            for model, v in sorted(usage[agent].get(month, {}).items()):
                breakdowns.append({"modelName": model, **dict(zip(COMPONENT_KEYS, v)),
                                   "cost": cost_of(agent, v)})
                if agent not in agents:
                    agents.append(agent)
        row = {c: sum(b[c] for b in breakdowns) for c in COMPONENT_KEYS}
        monthly.append({
            "agent": "all", "period": month, **row,
            "totalTokens": sum(row.values()),
            "totalCost": sum(b["cost"] for b in breakdowns),
            "modelsUsed": [b["modelName"] for b in breakdowns],
            "modelBreakdowns": breakdowns,
            "metadata": {"agents": agents},
        })
    (directory / "monthly.json").write_text(json.dumps({"monthly": monthly}))
    (directory / "daily.json").write_text(json.dumps({"daily": [
        {"agent": "all", "period": day, **dict(zip(COMPONENT_KEYS, v)),
         "totalTokens": sum(v), "totalCost": 0.0, "modelsUsed": [],
         "modelBreakdowns": [], "metadata": {"agents": []}}
        for day, v in sorted(daily.items())
    ]}))
    empty = {"totals": {}, "monthly": []}
    for agent in ("claude", "codex", "droid", "kimi", "opencode"):
        rows = []
        for month, models in sorted(usage.get(agent, {}).items()):
            comps = {c: sum(dict(zip(COMPONENT_KEYS, v))[c] for v in models.values())
                     for c in COMPONENT_KEYS}
            rows.append({
                "month": month, **comps, "totalTokens": sum(comps.values()),
                "totalCost": sum(cost_of(agent, v) for v in models.values()),
                "models": {m: usage_row(v, cost_of(agent, v)) for m, v in models.items()},
            })
        totals = {c: sum(r[c] for r in rows) for c in COMPONENT_KEYS + ["totalTokens", "totalCost"]}
        doc = {"totals": totals, "monthly": rows} if rows else empty
        (directory / f"agent-{agent}.json").write_text(json.dumps(doc))
    # Under turbotokens the true counters are the counter's own agent reports.
    (directory / "codex-true.json").write_text((directory / "agent-codex.json").read_text())
    (directory / "kimi-true.json").write_text(json.dumps(empty))


def build_ledger(directory, *baselines):
    return json.loads(subprocess.check_output(
        [sys.executable, str(ROOT / "build_tokens_json.py"), str(directory),
         *[str(b) for b in baselines]],
        text=True,
    ))


MISSING = object()


class FakeServer:
    """Stands in for curl: GET /api/usage answers `total`, POST /api/ingest
    accepts the payload. Records every call; the network is never touched."""

    def __init__(self, total):
        self.total = total
        self.calls = []

    def __call__(self, args, timeout):
        self.calls.append(list(args))
        if "-X" in args and args[args.index("-X") + 1] == "POST":
            payload = json.loads(args[args.index("--data-binary") + 1])
            return {"reconciled": True, "accepted": {"total": payload["tokens"]["total"]}}
        return {"tokens": {} if self.total is MISSING else {"total": self.total}}

    @property
    def posts(self):
        return [c for c in self.calls if "POST" in c]


# Loaded into every python3 the collector starts (PYTHONPATH): records and
# answers curl, `security` and urlopen in-process, so a shell-level test can
# never reach the network or the Keychain even if a guard under test breaks.
# GET answers an absurd production total so that any reconcile that gets past
# its guards would try to POST (and be recorded, not sent).
INTERCEPT = r'''
import json, os, subprocess, urllib.request
_LOG = os.environ["TOKENSTATS_INTERCEPT_LOG"]
_run = subprocess.run
def _record(kind, argv):
    with open(_LOG, "a") as fh:
        fh.write(json.dumps([kind, [a for a in argv if "Bearer" not in a]]) + "\n")
def run(args, *a, **kw):
    argv = [str(x) for x in args] if isinstance(args, (list, tuple)) else [str(args)]
    name = os.path.basename(argv[0])
    if name == "security":
        _record("security", argv[:2])
        return subprocess.CompletedProcess(argv, 0, "test-token\n", "")
    if name == "curl":
        posting = "-X" in argv
        _record("POST" if posting else "GET", argv[-1:] if not posting else ["POST"])
        body = {"reconciled": True, "accepted": {"total": 1}} if posting else {"tokens": {"total": 10 ** 15}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(body), "")
    return _run(args, *a, **kw)
subprocess.run = run
def urlopen(*a, **kw):
    _record("urlopen", [str(a[0])[:60]])
    raise OSError("network blocked by test")
urllib.request.urlopen = urlopen
'''


def stale_ledger(generated_at="2026-10-13T05:49:22Z", total=126_563_586_184):
    comps = dict(zip(COMPONENT_KEYS, (1, 1, 1, total - 3)))
    return {
        "generated_at": generated_at,
        "totals": {**comps, "totalTokens": total, "totalCost": 0.0, "listValueUsd": 0.0},
        "monthly": [{"period": "2026-10", **comps, "totalTokens": total, "totalCost": 0.0,
                     "modelBreakdowns": [{"modelName": "claude-opus-4-8", **comps, "cost": 0.0}]}],
        "daily": [], "agents": {"claude": {"totals": {"totalTokens": total}, "monthly": []}},
        "sources": [], "corrections": {"accountingRevision": build.ACCOUNTING_REVISION},
    }


class CollectorSandbox:
    """A throwaway git repo holding a copy of scripts/ and data/, plus a
    HOME, fake lockf, interceptor and empty agent logs, for running
    collect_tokens.sh end to end without touching anything real."""

    def __init__(self, tmp, ledger):
        self.tmp = pathlib.Path(tmp)
        self.repo = self.tmp / "repo"
        (self.repo / "data").mkdir(parents=True)
        shutil.copytree(ROOT, self.repo / "scripts",
                        ignore=shutil.ignore_patterns("__pycache__", "agent-host", "launchd"))
        for name in ("cloud-baseline.json", "grok-cache.json", "hermes-cache.json",
                     "cursor-cache.json", "local-purge-baseline.json"):
            source = ROOT.parent / "data" / name
            if source.exists():
                shutil.copy(source, self.repo / "data" / name)
        (self.repo / "data" / "tokens.json").write_text(json.dumps(ledger))
        git = ["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        subprocess.run(git[:3] + ["init", "-q"], check=True)
        subprocess.run(git + ["add", "."], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "fixture"], check=True)
        self.home = self.tmp / "home"
        (self.home / "Library" / "Logs").mkdir(parents=True)
        (self.tmp / "tmpdir").mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        lockf = self.bin / "lockf"
        lockf.write_text("#!/bin/sh\nexit 0\n")  # macOS-only tool; the lock is not under test
        lockf.chmod(0o755)
        self.site = self.tmp / "site"
        self.site.mkdir()
        (self.site / "sitecustomize.py").write_text(INTERCEPT)
        self.intercept_log = self.tmp / "intercept.log"
        self.intercept_log.write_text("")
        self.grok_home = self.tmp / "grok"
        (self.grok_home / "logs").mkdir(parents=True)

    def run(self, cwd=None, script=None, **env):
        full_env = {
            "PATH": f"{self.bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "HOME": str(self.home),
            "TMPDIR": str(self.tmp / "tmpdir"),
            "PYTHONPATH": str(self.site),
            "TOKENSTATS_INTERCEPT_LOG": str(self.intercept_log),
            "GROK_HOME": str(self.grok_home),
            "CCUSAGE": "false",            # every scan fails fast
            "TOKENSTATS_OFFLINE": "1",     # no Cursor, no cloud box
            "TOKENSTATS_SCAN_TIMEOUT": "60",
            **env,
        }
        return subprocess.run(
            ["bash", str(script or self.repo / "scripts" / "collect_tokens.sh")],
            cwd=str(cwd or self.tmp), env=full_env, capture_output=True, text=True, timeout=600,
        )

    def intercepted(self):
        return [json.loads(line) for line in self.intercept_log.read_text().splitlines()]

    def digest(self, *names):
        return {n: hashlib.sha256((self.repo / "data" / n).read_bytes()).hexdigest()
                for n in names if (self.repo / "data" / n).exists()}


class TokenPipelineTests(unittest.TestCase):
    def test_readme_keeps_the_july_card_compositions(self):
        readme = (ROOT.parent / "README.md").read_text()

        for expected in (
            './assets/neofetch.svg',
            'style=pro-classic',
            './assets/tokens-row.svg',
            'assets/tokens-stack.svg',
            'style=burn-classic',
            './assets/wrapped.svg',
        ):
            self.assertIn(expected, readme)

        for redesigned in (
            'style=profile',
            'style=ledger-row',
            'style=ledger-stack',
            'style=wrapped&',
        ):
            self.assertNotIn(redesigned, readme)

    def test_grok_build_model_timeline_tracks_the_active_recorded_model(self):
        timelines = {"session-a": [
            ("2026-07-08T00:00:00.000Z", "grok-4.20"),
            ("2026-07-08T08:00:00.000Z", "grok-4.5"),
        ]}

        self.assertEqual(
            grok_usage.model_at(
                timelines, "session-a", "2026-07-08T07:59:59.999Z"
            ),
            "grok-4.20",
        )
        self.assertEqual(
            grok_usage.model_at(
                timelines, "session-a", "2026-07-08T08:00:00.000Z"
            ),
            "grok-4.5",
        )
        self.assertEqual(
            grok_usage.model_at(timelines, "missing", "2026-07-08T09:00:00.000Z"),
            "unknown",
        )
        self.assertEqual(
            grok_usage.model_at(
                timelines, "session-a", "2026-07-07T23:59:59.999Z"
            ),
            "unknown",
        )

    def test_grok_build_cache_migration_preserves_total_and_marks_rotated_history(self):
        monthly = {"2026-07": {
            "inputTokens": 20,
            "outputTokens": 10,
            "cacheCreationTokens": 0,
            "cacheReadTokens": 70,
            "totalTokens": 100,
            "calls": 3,
        }}
        records = [{
            "id": "inference-a",
            "month": "2026-07",
            "model": "grok-4.5",
            "usage": {
                "inputTokens": 5,
                "outputTokens": 2,
                "cacheCreationTokens": 0,
                "cacheReadTokens": 28,
                "totalTokens": 35,
            },
        }]

        grok_usage.migrate_legacy_months(monthly, records, {"inference-a"})

        month = monthly["2026-07"]
        self.assertEqual(month["totalTokens"], 100)
        self.assertEqual(month["models"]["grok-4.5"]["totalTokens"], 35)
        self.assertEqual(month["models"]["unknown"]["totalTokens"], 65)
        for component in grok_usage.COMPONENTS + ["totalTokens"]:
            self.assertEqual(
                sum(model[component] for model in month["models"].values()),
                month[component],
            )

    def test_public_calendar_fallback_parses_exact_counts_and_bounds_future_days(self):
        markup = """
        <td data-date="2025-12-31" id="day-0"></td>
        <tool-tip for="day-0">5 contributions on December 31st.</tool-tip>
        <td data-date="2026-07-17" id="day-1"></td>
        <tool-tip for="day-1">1,234 contributions on July 17th.</tool-tip>
        <td data-date="2026-07-18" id="day-2"></td>
        <tool-tip for="day-2">No contributions on July 18th.</tool-tip>
        <td data-date="2026-07-19" id="day-3"></td>
        <tool-tip for="day-3">9 contributions on July 19th.</tool-tip>
        """
        calendar = heatmaps.parse_public_calendar(markup, through="2026-07-18")
        days = calendar["weeks"][0]["contributionDays"]
        self.assertEqual(days, [
            {"date": "2026-07-17", "contributionCount": 1234},
            {"date": "2026-07-18", "contributionCount": 0},
        ])
        self.assertEqual(calendar["totalContributions"], 1234)

    def test_public_calendar_fallback_rejects_malformed_numeric_grouping(self):
        markup = """
        <td data-date="2026-07-17" id="day-1"></td>
        <tool-tip for="day-1">1,,234 contributions on July 17th.</tool-tip>
        """
        with self.assertRaises(RuntimeError):
            heatmaps.parse_public_calendar(markup, through="2026-07-18")

    def test_public_calendar_fallback_rejects_partial_or_duplicate_markup(self):
        mismatched = """
        <td data-date="2026-07-17" id="day-1"></td>
        <tool-tip for="day-1">1,234 contributions on July 17th.</tool-tip>
        <td data-date="2026-07-18" id="day-2"></td>
        <tool-tip for="wrong-day">2 contributions on July 18th.</tool-tip>
        """
        with self.assertRaises(RuntimeError):
            heatmaps.parse_public_calendar(mismatched, through="2026-07-18")

        duplicate = """
        <td data-date="2026-07-17" id="day-1"></td>
        <tool-tip for="day-1">1,234 contributions on July 17th.</tool-tip>
        <td data-date="2026-07-17" id="day-2"></td>
        <tool-tip for="day-2">2 contributions on July 17th.</tool-tip>
        """
        with self.assertRaises(RuntimeError):
            heatmaps.parse_public_calendar(duplicate, through="2026-07-18")

    def test_public_calendar_fallback_validates_every_cell_before_bounding(self):
        malformed_future = """
        <td data-date="2026-07-17" id="day-1"></td>
        <tool-tip for="day-1">1 contribution on July 17th.</tool-tip>
        <td data-date="2026-7-19" id="day-2"></td>
        <tool-tip for="day-2">2 contributions on July 19th.</tool-tip>
        """
        with self.assertRaises(RuntimeError):
            heatmaps.parse_public_calendar(malformed_future, through="2026-07-18")

        impossible_date = """
        <td data-date="2026-00-99" id="day-1"></td>
        <tool-tip for="day-1">1 contribution on July 17th.</tool-tip>
        """
        with self.assertRaises(RuntimeError):
            heatmaps.parse_public_calendar(impossible_date, through="2026-07-18")

        missing_id = '<td data-date="2026-07-17"></td>'
        with self.assertRaises(RuntimeError):
            heatmaps.parse_public_calendar(missing_id, through="2026-07-18")

    def test_calendar_fallback_requires_exact_structured_limit_error_type(self):
        self.assertTrue(heatmaps.is_github_limit_error(RuntimeError([
            {"type": "RESOURCE_LIMITS_EXCEEDED", "message": "limited"},
        ])))
        self.assertTrue(heatmaps.is_github_limit_error(RuntimeError([
            {"type": "RATE_LIMITED", "message": "limited"},
        ])))
        self.assertFalse(heatmaps.is_github_limit_error(RuntimeError([
            {"type": "OTHER", "message": "not RESOURCE_LIMITS_EXCEEDED"},
        ])))
        self.assertFalse(heatmaps.is_github_limit_error(RuntimeError([
            {"type": "RATE_LIMITED"}, {"type": "OTHER"},
        ])))
        self.assertFalse(heatmaps.is_github_limit_error(
            RuntimeError("RESOURCE_LIMITS_EXCEEDED")
        ))

    def assert_components_conserved(self, row):
        if all(component in row and row[component] is not None for component in accounting.COMPONENTS):
            self.assertGreaterEqual(
                row.get("totalTokens", 0),
                accounting.component_total(row),
            )

    def test_component_floor_raises_undercount_and_preserves_provider_surplus(self):
        undercount = {
            "inputTokens": 5,
            "outputTokens": 7,
            "cacheCreationTokens": 11,
            "cacheReadTokens": 13,
            "totalTokens": 30,
        }
        provider_surplus = dict(undercount, totalTokens=50)

        accounting.floor_total_tokens(undercount)
        accounting.floor_total_tokens(provider_surplus)

        self.assertEqual(undercount["totalTokens"], 36)
        self.assertEqual(provider_surplus["totalTokens"], 50)

    def test_frozen_baseline_conserves_subtracted_rows_and_headline(self):
        rows = baseline.sub_series(
            [
                {
                    "period": "2026-06",
                    "inputTokens": 5,
                    "outputTokens": 7,
                    "cacheCreationTokens": 11,
                    "cacheReadTokens": 13,
                    "totalTokens": 50,
                    "totalCost": 0,
                    "modelBreakdowns": [{
                        "modelName": "model-a",
                        "inputTokens": 5,
                        "outputTokens": 7,
                        "cacheCreationTokens": 11,
                        "cacheReadTokens": 13,
                        "cost": 0,
                    }],
                },
                {
                    "period": "2026-07",
                    "inputTokens": 5,
                    "outputTokens": 7,
                    "cacheCreationTokens": 11,
                    "cacheReadTokens": 13,
                    "totalTokens": 30,
                    "totalCost": 0,
                },
            ],
            [],
            "period",
        )

        self.assertEqual([row["totalTokens"] for row in rows], [50, 36])
        self.assertEqual(
            accounting.component_total(rows[0]["modelBreakdowns"][0]),
            36,
        )
        self.assertEqual(baseline.totals_of(rows)["totalTokens"], 86)

    def test_merge_conserves_month_daily_agent_and_true_source_totals(self):
        def row(period_key, period, total):
            return {
                period_key: period,
                "inputTokens": 5,
                "outputTokens": 7,
                "cacheCreationTokens": 11,
                "cacheReadTokens": 13,
                "totalTokens": total,
                "totalCost": 0,
                "modelsUsed": [],
                "modelBreakdowns": [],
                "metadata": {"agents": []},
                "models": {},
            }

        monthly_rows = [row("period", "2026-07", 30), row("period", "2026-07", 50)]
        daily_rows = [row("period", "2026-07-18", 30), row("period", "2026-07-18", 50)]
        agent_rows = [row("month", "2026-07", 30), row("month", "2026-07", 50)]
        true_rows = [row("month", "2026-07", 30), row("month", "2026-07", 50)]
        for rows in (agent_rows, true_rows):
            for source_row in rows:
                source_row["models"] = {"model-a": {
                    "inputTokens": 5,
                    "outputTokens": 7,
                    "cacheCreationTokens": 11,
                    "cacheReadTokens": 13,
                    "totalTokens": source_row["totalTokens"],
                    "cost": 0,
                }}

        monthly = merge.merge_monthly([
            {"monthly": [monthly_rows[0]]},
            {"monthly": [monthly_rows[1]]},
        ])
        daily = merge.merge_daily([
            {"daily": [daily_rows[0]]},
            {"daily": [daily_rows[1]]},
        ])
        agent = merge.merge_agent([
            {"monthly": [agent_rows[0]]},
            {"monthly": [agent_rows[1]]},
        ])
        true_source = merge.merge_true([
            {"monthly": [true_rows[0]]},
            {"monthly": [true_rows[1]]},
        ])

        for result, section in (
            (monthly, "monthly"),
            (daily, "daily"),
            (agent, "monthly"),
            (true_source, "monthly"),
        ):
            self.assertEqual(result[section][0]["totalTokens"], 86)
            self.assertEqual(result["totals"]["totalTokens"], 86)
        self.assertEqual(agent["monthly"][0]["models"]["model-a"]["totalTokens"], 86)
        self.assertEqual(true_source["monthly"][0]["models"]["model-a"]["totalTokens"], 86)

        # Finalization must operate on copies, not mutate caller-owned receipts.
        for rows in (monthly_rows, daily_rows, agent_rows, true_rows):
            self.assertEqual([source_row["totalTokens"] for source_row in rows], [30, 50])
        self.assertEqual(agent_rows[0]["models"]["model-a"]["totalTokens"], 30)
        self.assertEqual(true_rows[0]["models"]["model-a"]["totalTokens"], 30)

    def test_build_conserves_every_public_accounting_boundary(self):
        def components(total):
            return {
                "inputTokens": 5,
                "outputTokens": 7,
                "cacheCreationTokens": 11,
                "cacheReadTokens": 13,
                "totalTokens": total,
            }

        monthly = []
        agent_monthly = []
        for period, total in (("2026-06", 50), ("2026-07", 30)):
            monthly.append({
                "agent": "all",
                "period": period,
                **components(total),
                "totalCost": 0,
                "modelsUsed": [],
                "modelBreakdowns": [],
                "metadata": {"agents": ["droid"]},
            })
            agent_monthly.append({
                "month": period,
                **components(total),
                "totalCost": 0,
                "modelsUsed": [],
                "models": {},
            })

        with tempfile.TemporaryDirectory() as tmp:
            directory = pathlib.Path(tmp)
            (directory / "monthly.json").write_text(json.dumps({"monthly": monthly}))
            (directory / "daily.json").write_text(json.dumps({
                "daily": [{
                    "agent": "all",
                    "period": "2026-07-18",
                    **components(30),
                    "totalCost": 0,
                    "modelsUsed": [],
                    "modelBreakdowns": [],
                    "metadata": {"agents": ["droid"]},
                }],
            }))
            empty = {"totals": {}, "monthly": []}
            for name in ("claude", "codex", "kimi", "opencode"):
                (directory / f"agent-{name}.json").write_text(json.dumps(empty))
            droid = {
                "totals": {**components(80), "totalCost": 0},
                "monthly": agent_monthly,
            }
            (directory / "agent-droid.json").write_text(json.dumps(droid))
            (directory / "codex-true.json").write_text(json.dumps(empty))
            (directory / "kimi-true.json").write_text(json.dumps(empty))
            (directory / "sources.json").write_text(json.dumps([
                {"label": "provider-surplus", "totals": components(50)},
                {"label": "component-undercount", "totals": components(30)},
            ]))
            baseline = {
                "totals": {**components(30), "totalCost": 0},
                "monthly": [{
                    "agent": "all",
                    "period": "2026-06",
                    **components(30),
                    "totalCost": 0,
                    "modelsUsed": [],
                    "modelBreakdowns": [],
                    "metadata": {"agents": []},
                }],
                "daily": [],
                "agents": {},
            }
            baseline_path = directory / "baseline.json"
            baseline_path.write_text(json.dumps(baseline))

            artifact = json.loads(subprocess.check_output(
                [
                    sys.executable,
                    str(ROOT / "build_tokens_json.py"),
                    str(directory),
                    str(baseline_path),
                ],
                text=True,
            ))

        months = {row["period"]: row for row in artifact["monthly"]}
        sources = {row["label"]: row["totals"] for row in artifact["sources"]}
        # Independent provider surplus (50 vs 36 components) and baseline
        # undercount (30 vs 36) are conserved before their rows are added.
        self.assertEqual(months["2026-06"]["totalTokens"], 86)
        self.assertEqual(months["2026-07"]["totalTokens"], 36)
        self.assertEqual(artifact["totals"]["totalTokens"], 122)
        self.assertEqual(artifact["daily"][0]["totalTokens"], 36)
        self.assertEqual(artifact["agents"]["droid"]["totals"]["totalTokens"], 80)
        self.assertEqual(artifact["agents"]["droid"]["monthly"][1]["totalTokens"], 36)
        self.assertEqual(sources["provider-surplus"]["totalTokens"], 50)
        self.assertEqual(sources["component-undercount"]["totalTokens"], 36)
        self.assertEqual(sources["cloud-baseline"]["totalTokens"], 36)
        self.assertEqual(
            artifact["corrections"]["accountingRevision"],
            build.ACCOUNTING_REVISION,
        )

    def test_cloud_source_family_includes_baseline_and_live_hermes(self):
        tokens = {"totals": {"totalTokens": 150}, "sources": [
            {"label": "local", "totals": {"totalTokens": 100}},
            {"label": "cloud", "totals": {"totalTokens": 20}},
            {"label": "cloud-baseline", "totals": {"totalTokens": 30}},
            {"label": "cloud-hermes", "totals": {"totalTokens": 40}},
        ]}
        self.assertEqual(common.source_total(tokens, "cloud"), 90)
        self.assertEqual(common.source_total(tokens, "local"), 60)

    def test_hermes_profile_overlap_fence_counts_cloud_sessions_once(self):
        rows = [
            {
                "profile": "main",
                "id": "mirrored",
                "started_at": 1783294784,
                "model": "gpt-main",
                "input_tokens": 10,
                "output_tokens": 3,
                "reasoning_tokens": 2,
                "cache_write_tokens": 5,
                "cache_read_tokens": 20,
            },
            {
                "profile": "builder",
                "id": "cloud-only",
                "started_at": 1783294785,
                "model": "gpt-builder",
                "input_tokens": 7,
                "output_tokens": 1,
                "reasoning_tokens": 0,
                "cache_write_tokens": 0,
                "cache_read_tokens": 12,
            },
        ]
        ccusage = {"monthly": [{
            "period": "2026-07",
            "inputTokens": 10,
            "outputTokens": 3,
            "cacheCreationTokens": 5,
            "cacheReadTokens": 20,
            "totalTokens": 40,
        }]}
        self.assertTrue(hermes.profile_is_covered_by_ccusage("main", rows, ccusage))

        sessions = {}
        for row in rows:
            key = f"{row['profile']}:{row['id']}"
            sessions[key] = {
                "month": hermes.month_of(row["started_at"]),
                "model": row["model"],
                "inputTokens": row["input_tokens"],
                "outputTokens": row["output_tokens"] + row["reasoning_tokens"],
                "cacheCreationTokens": row["cache_write_tokens"],
                "cacheReadTokens": row["cache_read_tokens"],
            }

        full, _ = hermes.aggregate_sessions(sessions)
        cloud_only, _ = hermes.aggregate_sessions(sessions, {"main"})
        self.assertEqual(full["totalTokens"], 60)
        self.assertEqual(cloud_only["totalTokens"], 20)
        self.assertEqual(ccusage["monthly"][0]["totalTokens"] + cloud_only["totalTokens"], 60)

        incomplete = json.loads(json.dumps(ccusage))
        incomplete["monthly"][0]["cacheReadTokens"] = 19
        self.assertFalse(hermes.profile_is_covered_by_ccusage("main", rows, incomplete))

    def test_hermes_pruned_sessions_survive_current_dump_overlap_fence(self):
        sessions = {
            "main:old": {
                "month": "2026-06",
                "model": "gpt-main",
                "inputTokens": 25,
                "outputTokens": 5,
                "cacheCreationTokens": 0,
                "cacheReadTokens": 70,
            }
        }
        rows = [{
            "profile": "main",
            "id": "live",
            "started_at": 1783294784,
            "model": "gpt-main",
            "input_tokens": 2,
            "output_tokens": 1,
            "reasoning_tokens": 0,
            "cache_write_tokens": 0,
            "cache_read_tokens": 7,
        }]
        dump_keys = hermes.fold_rows(sessions, rows)
        ccusage = {"monthly": [{
            "period": "2026-07",
            "inputTokens": 2,
            "outputTokens": 1,
            "cacheCreationTokens": 0,
            "cacheReadTokens": 7,
            "totalTokens": 10,
        }]}
        self.assertTrue(
            hermes.session_keys_are_covered_by_ccusage(
                sessions, dump_keys, ccusage
            )
        )
        full, _ = hermes.aggregate_sessions(sessions)
        publishable, _ = hermes.aggregate_sessions(
            sessions, excluded_keys=dump_keys
        )
        self.assertEqual(full["totalTokens"], 110)
        self.assertEqual(publishable["totalTokens"], 100)
        self.assertEqual(
            publishable["totalTokens"]
            + ccusage["monthly"][0]["totalTokens"],
            full["totalTokens"],
        )

    def test_hermes_regressed_live_row_cannot_hide_larger_cached_session(self):
        sessions = {
            "main:live": {
                "month": "2026-07",
                "model": "gpt-main",
                "inputTokens": 25,
                "outputTokens": 5,
                "cacheCreationTokens": 0,
                "cacheReadTokens": 70,
            }
        }
        dump_keys = hermes.fold_rows(sessions, [{
            "profile": "main",
            "id": "live",
            "started_at": 1783294784,
            "model": "gpt-main",
            "input_tokens": 2,
            "output_tokens": 1,
            "reasoning_tokens": 0,
            "cache_write_tokens": 0,
            "cache_read_tokens": 7,
        }])
        ccusage = {"monthly": [{
            "period": "2026-07",
            "inputTokens": 2,
            "outputTokens": 1,
            "cacheCreationTokens": 0,
            "cacheReadTokens": 7,
            "totalTokens": 10,
        }]}
        self.assertFalse(
            hermes.session_keys_are_covered_by_ccusage(
                sessions, dump_keys, ccusage
            )
        )
        full, _ = hermes.aggregate_sessions(sessions)
        self.assertEqual(full["totalTokens"], 100)

    def test_hermes_fold_is_componentwise_monotonic(self):
        sessions = {
            "main:offset": {
                "month": "2026-07",
                "model": "gpt-main",
                "inputTokens": 100,
                "outputTokens": 10,
                "cacheCreationTokens": 0,
                "cacheReadTokens": 100,
            }
        }
        hermes.fold_rows(sessions, [{
            "profile": "main",
            "id": "offset",
            "started_at": 1783294784,
            "model": "gpt-main",
            "input_tokens": 90,
            "output_tokens": 31,
            "reasoning_tokens": 0,
            "cache_write_tokens": 0,
            "cache_read_tokens": 100,
        }])
        entry = sessions["main:offset"]
        self.assertEqual(entry["inputTokens"], 100)
        self.assertEqual(entry["outputTokens"], 31)
        self.assertEqual(entry["cacheReadTokens"], 100)
        total, _ = hermes.aggregate_sessions(sessions)
        self.assertEqual(total["totalTokens"], 231)

    def test_hermes_overlap_requires_raw_output_coverage(self):
        rows = [{
            "profile": "main",
            "id": "output",
            "started_at": 1783294784,
            "model": "gpt-main",
            "input_tokens": 100,
            "output_tokens": 100,
            "reasoning_tokens": 0,
            "cache_write_tokens": 0,
            "cache_read_tokens": 0,
        }]
        ccusage = {"monthly": [{
            "period": "2026-07",
            "inputTokens": 200,
            "outputTokens": 0,
            "cacheCreationTokens": 0,
            "cacheReadTokens": 0,
            "totalTokens": 200,
        }]}
        self.assertFalse(
            hermes.profile_is_covered_by_ccusage("main", rows, ccusage)
        )

    def test_accounting_revision_is_stable_for_one_time_consumer_adoption(self):
        # Pinned on purpose: consumers adopt a corrected total exactly once per
        # distinct revision string, so this must only change deliberately and
        # together with the committed artifact below.
        self.assertEqual(build.ACCOUNTING_REVISION, "turbotokens-counter-v4")
        with open(ROOT.parent / "data" / "tokens.json") as fh:
            artifact = json.load(fh)
        self.assertEqual(
            artifact.get("corrections", {}).get("accountingRevision"),
            build.ACCOUNTING_REVISION,
        )
        self.assertTrue(artifact.get("corrections", {}).get("componentTotalsConserved"))
        self.assert_components_conserved(artifact["totals"])
        for month in artifact.get("monthly", []):
            self.assert_components_conserved(month)
            rows = month.get("modelBreakdowns", [])
            for component in build.COMPONENTS:
                self.assertLessEqual(
                    sum(row.get(component, 0) or 0 for row in rows),
                    month.get(component, 0) or 0,
                )
            self.assertLessEqual(
                sum(row.get("cost", 0) or 0 for row in rows),
                (month.get("totalCost", 0) or 0) + 1e-9,
            )
        for day in artifact.get("daily", []):
            self.assert_components_conserved(day)
        for agent in artifact.get("agents", {}).values():
            self.assert_components_conserved(agent.get("totals", {}))
            for month in agent.get("monthly", []):
                self.assert_components_conserved(month)
                for model in (month.get("models") or {}).values():
                    self.assert_components_conserved(model)
        for source in artifact.get("sources", []):
            self.assert_components_conserved(source.get("totals", {}))

    def test_codex_uses_cumulative_deltas_and_preserves_model_components(self):
        rows = [
            {"type": "session_meta", "timestamp": "2026-07-16T10:00:00Z", "payload": {}},
            {"type": "turn_context", "payload": {"model": "gpt-5.3-codex"}},
            self.token_event(100, 80, 20, 120, "2026-07-16T10:00:01Z"),
            self.token_event(100, 80, 20, 120, "2026-07-16T10:00:02Z"),
            self.token_event(160, 120, 30, 190, "2026-07-16T10:00:03Z"),
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")
            fh.flush()
            totals = codex.new_bucket()
            monthly = defaultdict(codex.new_bucket)
            models = defaultdict(lambda: defaultdict(codex.new_bucket))
            codex.process_file(fh.name, totals, monthly, models)

        expected = {
            "inputTokens": 40,
            "outputTokens": 30,
            "cacheCreationTokens": 0,
            "cacheReadTokens": 120,
            "totalTokens": 190,
        }
        self.assertEqual(totals, expected)
        self.assertEqual(models["2026-07"]["gpt-5.3-codex"], expected)

    def test_true_source_merge_keeps_the_full_model_receipt(self):
        source = {
            "monthly": [{
                "month": "2026-07",
                "inputTokens": 5,
                "outputTokens": 7,
                "cacheCreationTokens": 11,
                "cacheReadTokens": 13,
                "totalTokens": 36,
                "totalCost": 2.5,
                "models": {"model-a": {
                    "inputTokens": 5,
                    "outputTokens": 7,
                    "cacheCreationTokens": 11,
                    "cacheReadTokens": 13,
                    "totalTokens": 36,
                    "cost": 2.5,
                }},
            }],
        }
        result = merge.merge_true([source])
        self.assertEqual(result["monthly"][0]["models"]["model-a"], source["monthly"][0]["models"]["model-a"])

    def test_verified_slice_replaces_inflated_rows_and_drops_placeholders(self):
        month = {
            "inputTokens": 110,
            "outputTokens": 55,
            "cacheCreationTokens": 0,
            "cacheReadTokens": 1_100,
            "totalTokens": 1_265,
            "modelBreakdowns": [
                {"modelName": "other", "inputTokens": 10, "outputTokens": 5, "cacheCreationTokens": 0, "cacheReadTokens": 100, "cost": 1},
                {"modelName": "gpt-5-3-codex", "inputTokens": 100, "outputTokens": 50, "cacheCreationTokens": 0, "cacheReadTokens": 1_000, "cost": 10},
                {"modelName": "default", "inputTokens": 0, "outputTokens": 0, "cacheCreationTokens": 0, "cacheReadTokens": 0, "cost": 0},
            ],
        }
        reported = {
            "inputTokens": 100,
            "outputTokens": 50,
            "cacheCreationTokens": 0,
            "cacheReadTokens": 1_000,
            "totalTokens": 1_150,
            "models": {"gpt-5-3-codex": {
                "inputTokens": 100,
                "outputTokens": 50,
                "cacheCreationTokens": 0,
                "cacheReadTokens": 1_000,
                "totalTokens": 1_150,
                "cost": 10,
            }},
        }
        corrected = {
            "inputTokens": 20,
            "outputTokens": 10,
            "cacheCreationTokens": 0,
            "cacheReadTokens": 200,
            "totalTokens": 230,
            "models": {"gpt-5.3-codex": {
                "inputTokens": 20,
                "outputTokens": 10,
                "cacheCreationTokens": 0,
                "cacheReadTokens": 200,
                "totalTokens": 230,
            }},
        }

        build.replace_agent_month(month, reported, corrected)

        self.assertEqual(month["totalTokens"], 345)
        self.assertEqual(month["modelsUsed"], ["gpt-5.3-codex", "other"])
        rows = {row["modelName"]: row for row in month["modelBreakdowns"]}
        self.assertNotIn("default", rows)
        self.assertEqual(build.model_total(rows["gpt-5.3-codex"]), 230)
        self.assertAlmostEqual(rows["gpt-5.3-codex"]["cost"], 2.0)
        self.assertEqual(build.model_total(rows["other"]), 115)

    def test_codex_replacement_removes_orphan_codex_rows(self):
        month = {
            "inputTokens": 250,
            "outputTokens": 0,
            "cacheCreationTokens": 0,
            "cacheReadTokens": 0,
            "totalTokens": 250,
            "modelBreakdowns": [
                {"modelName": "gpt-5.5", "inputTokens": 100, "outputTokens": 0, "cacheCreationTokens": 0, "cacheReadTokens": 0, "cost": 10},
                {"modelName": "gpt-5-3-codex", "inputTokens": 50, "outputTokens": 0, "cacheCreationTokens": 0, "cacheReadTokens": 0, "cost": 5},
                {"modelName": "gpt-5", "inputTokens": 50, "outputTokens": 0, "cacheCreationTokens": 0, "cacheReadTokens": 0, "cost": 3},
                {"modelName": "other", "inputTokens": 50, "outputTokens": 0, "cacheCreationTokens": 0, "cacheReadTokens": 0, "cost": 2},
            ],
        }
        reported = {
            "inputTokens": 200,
            "totalTokens": 200,
            "models": {
                "gpt-5.5": {"inputTokens": 100},
                "gpt-5": {"inputTokens": 50},
            },
        }
        corrected = {
            "inputTokens": 80,
            "totalTokens": 80,
            "models": {"gpt-5.5": {"inputTokens": 80}},
        }

        build.replace_agent_month(
            month,
            reported,
            corrected,
            reported_model_predicate=lambda name: "codex" in name,
        )

        self.assertEqual(month["inputTokens"], 130)
        self.assertEqual(
            sum(row["inputTokens"] for row in month["modelBreakdowns"]),
            130,
        )
        self.assertNotIn(
            "gpt-5.3-codex",
            {row["modelName"] for row in month["modelBreakdowns"]},
        )
        self.assertNotIn(
            "gpt-5",
            {row["modelName"] for row in month["modelBreakdowns"]},
        )

    def test_model_breakdowns_are_capped_to_verified_components(self):
        month = {
            "inputTokens": 100,
            "outputTokens": 20,
            "cacheCreationTokens": 0,
            "cacheReadTokens": 200,
            "totalCost": 10.0,
            "modelBreakdowns": [
                {"modelName": "a", "inputTokens": 60, "outputTokens": 15, "cacheCreationTokens": 0, "cacheReadTokens": 150, "cost": 8.0},
                {"modelName": "b", "inputTokens": 60, "outputTokens": 15, "cacheCreationTokens": 0, "cacheReadTokens": 150, "cost": 8.0},
            ],
        }
        rows = build.cap_model_breakdowns(month)
        self.assertEqual(sum(row["inputTokens"] for row in rows), 100)
        self.assertEqual(sum(row["outputTokens"] for row in rows), 20)
        self.assertEqual(sum(row["cacheReadTokens"] for row in rows), 200)
        self.assertAlmostEqual(sum(row["cost"] for row in rows), 10.0)

        rounded = build.cap_model_breakdowns({
            "inputTokens": 1,
            "outputTokens": 0,
            "cacheCreationTokens": 0,
            "cacheReadTokens": 0,
            "totalCost": 0,
            "modelBreakdowns": [
                {"modelName": "a", "inputTokens": 1},
                {"modelName": "b", "inputTokens": 1},
            ],
        })
        self.assertEqual(len(rounded), 1)
        self.assertEqual(rounded[0]["inputTokens"], 1)


    # --- local purge baseline (2026-10-12 transcript deletion) ---------------

    FULL_USAGE = {
        "claude": {
            "2026-08": {"claude-opus-4-8": (100, 50, 10, 1000), "claude-haiku-4-5": (20, 10, 0, 70)},
            "2026-09": {"claude-opus-4-8": (10, 5, 1, 100)},
            "2026-10": {"claude-opus-4-8": (1, 1, 1, 10)},
        },
        "codex": {
            "2026-08": {"gpt-5.5": (200, 20, 0, 2000)},
            "2026-10": {"gpt-6-sol": (5, 5, 0, 50)},
        },
    }
    # After the purge: August lost most Claude and Codex transcripts, the
    # Haiku session entirely; September survived; October kept accruing.
    PURGED_USAGE = {
        "claude": {
            "2026-08": {"claude-opus-4-8": (40, 20, 4, 400)},
            "2026-09": {"claude-opus-4-8": (10, 5, 1, 100)},
            "2026-10": {"claude-opus-4-8": (3, 3, 3, 30)},
        },
        "codex": {
            "2026-08": {"gpt-5.5": (50, 5, 0, 500)},
            "2026-10": {"gpt-6-sol": (9, 9, 0, 90)},
        },
    }
    FULL_DAILY = {"2026-09-20": (10, 5, 1, 100), "2026-10-02": (1, 1, 1, 10)}
    PURGED_DAILY = {"2026-09-20": (4, 2, 0, 40), "2026-10-02": (3, 3, 3, 30)}

    def purge_fixture(self, tmp):
        tmp = pathlib.Path(tmp)
        cloud = tmp / "cloud-baseline.json"
        cloud.write_text(json.dumps({
            "totals": {**dict(zip(COMPONENT_KEYS, (1, 2, 3, 994))), "totalTokens": 1000, "totalCost": 0.5},
            "monthly": [{
                "agent": "all", "period": "2026-06",
                **dict(zip(COMPONENT_KEYS, (1, 2, 3, 994))), "totalTokens": 1000, "totalCost": 0.5,
                "modelsUsed": ["claude-opus-4-8"],
                "modelBreakdowns": [{"modelName": "claude-opus-4-8",
                                     **dict(zip(COMPONENT_KEYS, (1, 2, 3, 994))), "cost": 0.5}],
                "metadata": {"agents": ["claude"]},
            }],
            "daily": [],
            "agents": {"claude": {
                "totals": {**dict(zip(COMPONENT_KEYS, (1, 2, 3, 994))), "totalTokens": 1000, "totalCost": 0.5},
                "monthly": [{"month": "2026-06", **dict(zip(COMPONENT_KEYS, (1, 2, 3, 994))),
                             "totalTokens": 1000, "totalCost": 0.5, "models": {}}],
            }},
        }))
        write_scan(tmp / "full", self.FULL_USAGE, self.FULL_DAILY)
        write_scan(tmp / "purged", self.PURGED_USAGE, self.PURGED_DAILY)
        old = build_ledger(tmp / "full", cloud)
        old["generated_at"] = "2026-10-13T05:49:22Z"
        fresh = build_ledger(tmp / "purged", cloud)
        return tmp, cloud, old, fresh

    def test_purge_baseline_is_old_minus_fresh_per_month_agent_and_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, old, fresh = self.purge_fixture(tmp)
        result = purge.compute_baseline(old, fresh, "2026-10")

        # Only August lost usage: September is fully covered by the fresh
        # scan, October is the open month, and June is the cloud baseline
        # present on both sides.
        self.assertEqual([m["period"] for m in result["monthly"]], ["2026-08"])
        august = result["monthly"][0]
        lost = {"claude-opus-4-8": (60, 30, 6, 600), "claude-haiku-4-5": (20, 10, 0, 70),
                "gpt-5.5": (150, 15, 0, 1500)}
        self.assertEqual(
            {b["modelName"]: tuple(b[c] for c in COMPONENT_KEYS) for b in august["modelBreakdowns"]},
            lost,
        )
        self.assertEqual(august["totalTokens"], sum(sum(v) for v in lost.values()))
        self.assertEqual(august["metadata"]["agents"], ["claude", "codex"])
        self.assertAlmostEqual(august["totalCost"], (60 + 30) / 1000 + (20 + 10) / 1000)

        self.assertEqual(sorted(result["agents"]), ["claude", "codex"])
        claude = result["agents"]["claude"]
        self.assertEqual([r["month"] for r in claude["monthly"]], ["2026-08"])
        self.assertEqual(claude["monthly"][0]["models"]["claude-haiku-4-5"]["totalTokens"], 100)
        self.assertEqual(claude["totals"]["totalTokens"], 696 + 100)
        self.assertEqual(result["agents"]["codex"]["totals"]["totalTokens"], 1665)

        # September's day lost usage too; October's day belongs to the scan.
        self.assertEqual([(d["period"], d["totalTokens"]) for d in result["daily"]],
                         [("2026-09-20", 70)])
        # A day before the fresh scan's 35-day window is out of range, not purged.
        early = json.loads(json.dumps(old))
        early["daily"].insert(0, dict(early["daily"][0], period="2026-09-01"))
        self.assertEqual([d["period"] for d in purge.compute_baseline(early, fresh, "2026-10")["daily"]],
                         ["2026-09-20"])
        self.assertEqual(result["totals"]["totalTokens"],
                         sum(m["totalTokens"] for m in result["monthly"]))
        self.assertEqual(result["label"], purge.LABEL)

        # Floors: a model that GREW in a finished month never goes negative,
        # and attributed models stay within the month's components.
        grown = json.loads(json.dumps(fresh))
        for row in grown["monthly"]:
            if row["period"] == "2026-08":
                row["modelBreakdowns"].append({"modelName": "gpt-5.4", **dict(zip(COMPONENT_KEYS, (5, 0, 0, 0))), "cost": 0})
        floored = purge.compute_baseline(old, grown, "2026-10")
        for month in floored["monthly"]:
            for c in COMPONENT_KEYS:
                self.assertGreaterEqual(month[c], 0)
                self.assertLessEqual(sum(b[c] for b in month["modelBreakdowns"]), month[c])

    def test_rebuild_with_purge_baseline_restores_finished_months_and_keeps_open_month_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp, cloud, old, fresh = self.purge_fixture(tmp)
            baseline_path = tmp / "local-purge-baseline.json"
            baseline_path.write_text(json.dumps(purge.compute_baseline(old, fresh, "2026-10")))
            rebuilt = build_ledger(tmp / "purged", cloud, baseline_path)

        old_m = {m["period"]: m for m in old["monthly"]}
        new_m = {m["period"]: m for m in rebuilt["monthly"]}
        fresh_m = {m["period"]: m for m in fresh["monthly"]}
        models = lambda m: {b["modelName"]: tuple(b[c] for c in COMPONENT_KEYS) for b in m["modelBreakdowns"]}
        for period in ("2026-06", "2026-08", "2026-09"):
            for key in COMPONENT_KEYS + ["totalTokens"]:
                self.assertEqual(new_m[period][key], old_m[period][key], (period, key))
            self.assertEqual(models(new_m[period]), models(old_m[period]))
            self.assertAlmostEqual(new_m[period]["totalCost"], old_m[period]["totalCost"])
            self.assertAlmostEqual(new_m[period]["listValueUsd"], old_m[period]["listValueUsd"])
        self.assertEqual(new_m["2026-10"]["totalTokens"], fresh_m["2026-10"]["totalTokens"])
        self.assertEqual(models(new_m["2026-10"]), models(fresh_m["2026-10"]))
        self.assertEqual(
            rebuilt["totals"]["totalTokens"],
            old["totals"]["totalTokens"] - old_m["2026-10"]["totalTokens"]
            + fresh_m["2026-10"]["totalTokens"],
        )
        self.assertGreater(rebuilt["totals"]["totalTokens"], old["totals"]["totalTokens"])

        for agent in ("claude", "codex"):
            old_a = {r["month"]: r for r in old["agents"][agent]["monthly"]}
            new_a = {r["month"]: r for r in rebuilt["agents"][agent]["monthly"]}
            fresh_a = {r["month"]: r for r in fresh["agents"][agent]["monthly"]}
            for month in old_a:
                expected = fresh_a if month == "2026-10" else old_a
                self.assertEqual(new_a[month]["totalTokens"], expected[month]["totalTokens"], (agent, month))
        days = {d["period"]: d["totalTokens"] for d in rebuilt["daily"]}
        self.assertEqual(days, {"2026-09-20": 116, "2026-10-02": 39})
        self.assertEqual(
            sorted(s["label"] for s in rebuilt["sources"]),
            ["cloud-baseline", "local-purge-baseline"],
        )
        self.assert_components_conserved(rebuilt["totals"])

    def test_purge_baseline_refuses_partial_or_disagreeing_scans(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp, _, old, fresh = self.purge_fixture(tmp)

            def audit_dir(name, ledger, failures=""):
                d = tmp / name
                d.mkdir()
                (d / "tokens.json").write_text(json.dumps(ledger))
                (d / "scan-failures.txt").write_text(failures)
                return d

            old_path = tmp / "last-good.json"
            old_path.write_text(json.dumps(old))
            a = audit_dir("fresh-a", fresh)
            b = audit_dir("fresh-b", fresh)
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(purge.main([str(old_path), str(a), str(b)]), 0)
            written = json.loads(out.getvalue())
            self.assertEqual(written["open_month"], "2026-10")
            self.assertGreater(written["agreement"]["finished_rows_compared"], 0)

            # A finished month that moved between the two runs: refuse.
            moved = json.loads(json.dumps(fresh))
            next(m for m in moved["monthly"] if m["period"] == "2026-08")["totalTokens"] += 1
            # ...while the open month may keep growing between runs.
            grown = json.loads(json.dumps(fresh))
            next(m for m in grown["monthly"] if m["period"] == "2026-10")["totalTokens"] += 99
            self.assertGreater(purge.check_agreement(fresh, grown, "2026-10"), 0)
            # A timed-out scan, an agent that vanished, an already-patched
            # build, and a non-purged agent losing usage: refuse.
            vanished = json.loads(json.dumps(fresh))
            vanished["agents"]["codex"] = {"totals": {}, "monthly": []}
            patched = json.loads(json.dumps(fresh))
            patched["sources"].append({"label": purge.LABEL, "totals": {}})
            cases = [
                (audit_dir("moved", moved), "disagree on 1 finished-month row(s): monthly/2026-08"),
                (audit_dir("timed-out", fresh, "grok-true exit=124 300s\n"), "timed out: grok-true exit=124"),
                (audit_dir("vanished", vanished), "agent 'codex' has no usage at all"),
                (audit_dir("patched", patched), "already includes local-purge-baseline"),
            ]
            for second, reason in cases:
                err = io.StringIO()
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(err):
                    self.assertEqual(purge.main([str(old_path), str(a), str(second)]), 2, second)
                self.assertIn("REFUSED", err.getvalue())
                self.assertIn(reason, err.getvalue())
                self.assertEqual(stdout.getvalue(), "")  # nothing to redirect into the data file
            with self.assertRaises(purge.BaselineError):
                purge.compute_baseline(old, fresh, "2026-10", purged_agents=("claude",))

    def test_committed_purge_baseline_is_conserved_and_finished_months_only(self):
        path = ROOT.parent / "data" / "local-purge-baseline.json"
        if not path.exists():
            self.skipTest("no committed purge baseline")
        data = json.loads(path.read_text())
        self.assertEqual(data["label"], purge.LABEL)
        for row in data["monthly"]:
            self.assertLess(row["period"], data["open_month"])
            self.assert_components_conserved(row)
            for c in COMPONENT_KEYS:
                self.assertLessEqual(sum(b[c] for b in row["modelBreakdowns"]), row[c])
        self.assertEqual(data["totals"]["totalTokens"], sum(r["totalTokens"] for r in data["monthly"]))
        for agent in data["agents"].values():
            for row in agent["monthly"]:
                self.assertLess(row["month"], data["open_month"])
                self.assert_components_conserved(row)
        for row in data["daily"]:
            self.assertLess(row["period"], data["open_month"])


    def test_purge_baseline_rerun_after_a_later_deletion_replaces_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp, cloud, old, fresh = self.purge_fixture(tmp)
            first = tmp / "first-baseline.json"
            first.write_text(json.dumps(purge.compute_baseline(old, fresh, "2026-10")))
            # The ledger that shipped with the first baseline, built in November.
            shipped = build_ledger(tmp / "purged", cloud, first)
            shipped["generated_at"] = "2026-11-02T00:00:00Z"
            self.assertIn(purge.LABEL, purge.source_labels(shipped))
            # A second cleanup takes more of August and part of September and
            # October; November keeps accruing.
            again = json.loads(json.dumps(self.PURGED_USAGE))
            again["codex"]["2026-08"] = {"gpt-5.5": (10, 1, 0, 100)}
            again["claude"]["2026-09"] = {"claude-opus-4-8": (2, 1, 0, 20)}
            again["claude"]["2026-10"] = {"claude-opus-4-8": (1, 1, 1, 10)}
            again["claude"]["2026-11"] = {"claude-opus-4-8": (7, 7, 7, 70)}
            write_scan(tmp / "purged-again", again, self.PURGED_DAILY)
            fresh_again = build_ledger(tmp / "purged-again", cloud)  # no purge baseline
            fresh_again["generated_at"] = "2026-11-05T00:00:00Z"
            dirs = []
            for name in ("again-a", "again-b"):
                d = tmp / name
                d.mkdir()
                (d / "tokens.json").write_text(json.dumps(fresh_again))
                (d / "scan-failures.txt").write_text("")
                dirs.append(str(d))
            shipped_path = tmp / "shipped.json"
            shipped_path.write_text(json.dumps(shipped))
            second = tmp / "second-baseline.json"
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(purge.main([str(shipped_path), *dirs, "--out", str(second)]), 0,
                                 err.getvalue())
            replaced = json.loads(second.read_text())
            self.assertEqual(replaced["open_month"], "2026-11")
            rebuilt = build_ledger(tmp / "purged-again", cloud, second)

        shipped_m = {m["period"]: m for m in shipped["monthly"]}
        rebuilt_m = {m["period"]: m for m in rebuilt["monthly"]}
        fresh_m = {m["period"]: m for m in fresh_again["monthly"]}
        for period, row in shipped_m.items():  # every finished month, both purges restored
            for key in COMPONENT_KEYS + ["totalTokens"]:
                self.assertEqual(rebuilt_m[period][key], row[key], (period, key))
        self.assertEqual(rebuilt_m["2026-11"]["totalTokens"], fresh_m["2026-11"]["totalTokens"])
        self.assertEqual(sum(1 for s in rebuilt["sources"] if s["label"] == purge.LABEL), 1)
        first_aug = next(m for m in json.loads(json.dumps(purge.compute_baseline(old, fresh, "2026-10")))["monthly"]
                         if m["period"] == "2026-08")
        second_aug = next(m for m in replaced["monthly"] if m["period"] == "2026-08")
        self.assertGreater(second_aug["totalTokens"], first_aug["totalTokens"])

    # --- collect_tokens.sh in a sandbox repo ----------------------------------

    def test_hook_path_reconcile_with_a_stale_ledger_makes_no_post(self):
        """The SessionEnd hook runs collect_tokens.sh, whose first step is
        reconcile_server.py against data/tokens.json. With the Oct 13 ledger it
        must refuse before any network call; the positive control (a fresh
        ledger, production absurdly high) shows the harness does see a POST."""
        with tempfile.TemporaryDirectory() as tmp:
            box = CollectorSandbox(tmp, stale_ledger())
            before = box.digest("tokens.json")
            result = box.run(TOKENSTATS_STRICT_SCANS="1")
            log = (box.home / "Library" / "Logs" / "tokenstats-reconcile.log").read_text()
            self.assertIn("REFUSED, not posting", log, result.stdout + result.stderr)
            self.assertIn("server drift check refused or failed", result.stdout)
            self.assertEqual(box.intercepted(), [])  # no GET, no Keychain, no POST
            self.assertEqual(result.returncode, 3, result.stdout)  # strict: stops before building
            self.assertEqual(box.digest("tokens.json"), before)

            fresh_now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            (box.repo / "data" / "tokens.json").write_text(json.dumps(stale_ledger(fresh_now)))
            box.run(TOKENSTATS_STRICT_SCANS="1")
            kinds = [kind for kind, _ in box.intercepted()]
            self.assertEqual(kinds, ["GET", "security", "POST"])  # recorded, never sent

    def test_audit_dir_inside_any_checkout_of_the_repo_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            box = CollectorSandbox(tmp, stale_ledger())
            worktree = box.tmp / "worktree"
            subprocess.run(["git", "-C", str(box.repo), "worktree", "add", "-q", "--detach",
                            str(worktree)], check=True)
            (box.tmp / "elsewhere").mkdir()
            (box.tmp / "link").symlink_to(box.repo / "data")
            before = box.digest("tokens.json", "grok-cache.json")
            script = worktree / "scripts" / "collect_tokens.sh"
            cases = [
                (worktree, "data"),                                   # relative, in the worktree
                (worktree, "."),
                (worktree, "data/new/deeper"),
                (box.tmp, str(box.repo / "data")),                    # another checkout, same repo
                (box.tmp, str(box.tmp / "elsewhere" / ".." / "repo" / "data")),
                (box.tmp, str(box.tmp / "nope" / ".." / "repo" / "data")),
                (box.tmp, str(box.tmp / "link")),                     # symlink into a checkout
                (box.tmp, str(box.repo / ".git" / "audit")),
            ]
            refused, _, _ = self.guard_fixture(box)
            cases += [(box.tmp, str(path)) for path in refused]   # wrong case, symlinked parent, clones
            for cwd, audit_dir in cases:
                result = box.run(cwd=cwd, script=script, TOKENSTATS_AUDIT_DIR=audit_dir)
                self.assertEqual(result.returncode, 2, (audit_dir, result.stdout, result.stderr))
                self.assertIn("inside a checkout of this repository", result.stdout)
            self.assertFalse((worktree / "data" / "cache").exists())
            self.assertFalse((worktree / "data" / "new").exists())
            self.assertFalse((box.repo / "data" / "cache").exists())
            self.assertFalse((box.repo / ".git" / "audit").exists())
            self.assertFalse((box.tmp / "nope").exists())
            self.assertFalse((box.tmp / "clone" / "data" / "cache").exists())
            self.assertFalse((box.tmp / "clone" / "deep").exists())
            self.assertFalse((box.tmp / "origin-only" / "out").exists())
            self.assertEqual(box.digest("tokens.json", "grok-cache.json"), before)
            self.assertEqual(box.intercepted(), [])

    def guard_fixture(self, box):
        """Other spellings and copies of the sandbox repo, for the audit guard."""
        t = box.tmp
        (t / "alias").symlink_to(t, target_is_directory=True)          # symlinked parent
        subprocess.run(["git", "clone", "-q", str(box.repo), str(t / "clone")], check=True)
        subprocess.run(["git", "init", "-q", str(t / "origin-only")], check=True)
        subprocess.run(["git", "-C", str(t / "origin-only"), "remote", "add", "origin",
                        "https://github.com/MaxMoneyCash/maxmoneycash.git"], check=True)
        (t / "elsewhere").mkdir(exist_ok=True)
        refused = [
            t / "alias" / "repo" / "data",
            t / "alias" / "alias" / "repo" / "data" / "new",
            t / "clone" / "data",                     # separate full clone
            t / "clone" / "deep" / "er",
            t / "origin-only" / "out",                # same origin, no collector checked out
        ]
        wrong_case = t / "REPO" / "data"
        case_insensitive = wrong_case.exists()
        if case_insensitive:                         # APFS default: same directory
            refused += [wrong_case, t / "Repo" / "DATA" / "new", t / "alias" / "REPO" / ".GIT" / "x"]
        allowed = [t / "elsewhere", t / "elsewhere" / "new" / "dir", t / "alias" / "elsewhere"]
        return refused, allowed, case_insensitive

    def test_audit_dir_guard_compares_directories_by_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            box = CollectorSandbox(tmp, stale_ledger())
            refused, allowed, case_insensitive = self.guard_fixture(box)
            missing = [path for path in refused + allowed if not path.exists()]
            for path in refused:
                self.assertIsNotNone(audit_guard.refusal(str(path), str(box.repo)), path)
            for path in allowed:
                self.assertIsNone(audit_guard.refusal(str(path), str(box.repo)), path)
            if not case_insensitive:
                # Case-sensitive disk (CI): REPO really is another directory.
                self.assertIsNone(audit_guard.refusal(str(box.tmp / "REPO" / "data"), str(box.repo)))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(audit_guard.main([str(refused[0]), str(box.repo)]), 2)
            self.assertTrue(out.getvalue().startswith("REFUSED: "))
            self.assertEqual([path for path in missing if path.exists()], [])  # nothing created

    # --- per-agent drop guard ---------------------------------------------------

    def test_agent_drop_guard_names_an_agent_a_failed_scan_erased(self):
        old = {"agents": {"codex": {"totals": {"totalTokens": 39_852_796_916}},
                          "claude": {"totals": {"totalTokens": 90_000_000_000}}}}
        new = {"agents": {"codex": {"totals": {"totalTokens": 22_686_433_567}},
                          "claude": {"totals": {"totalTokens": 90_400_000_000}}}}
        self.assertEqual(agent_drops.drops(old, new), ["codex 39852796916->22686433567"])
        self.assertEqual(agent_drops.drops(old, old), [])
        one = {"agents": {"kimi": {"totals": {"totalTokens": 1_000_000}}}}
        self.assertEqual(agent_drops.drops(one, {"agents": {"kimi": {"totals": {"totalTokens": 996_000}}}}), [],
                         "rounding noise is not a lost source")
        self.assertEqual(agent_drops.drops(one, {"agents": {}}), ["kimi 1000000->0"])
        self.assertEqual(agent_drops.drops({}, new), [], "a first ledger has nothing to lose")
        self.assertEqual(agent_drops.drops(new, {**new, "agents": {**new["agents"], "droid": {}}}), [])

    def fake_counter(self, box, codex_fails):
        """A stand-in for turbotokens whose Codex scans fail like the 300 s
        timeouts of 2026-10-20 while every other scan succeeds."""
        comps = {"inputTokens": 1, "outputTokens": 1, "cacheCreationTokens": 1, "cacheReadTokens": 97}
        breakdown = {"modelName": "claude-opus-4-8", **comps, "cost": 0}
        model = {**comps, "totalTokens": 100, "cost": 0}
        def row(key, period):
            return {key: period, **comps, "totalTokens": 100, "totalCost": 0,
                    "modelsUsed": ["claude-opus-4-8"], "modelBreakdowns": [breakdown],
                    "metadata": {"agents": []}, "models": {"claude-opus-4-8": model}}
        fixtures = box.tmp / "fake-counter"
        fixtures.mkdir()
        (fixtures / "monthly.json").write_text(json.dumps({"monthly": [row("period", "2026-10")]}))
        (fixtures / "daily.json").write_text(json.dumps({"daily": [row("period", "2026-10-20")]}))
        (fixtures / "agent.json").write_text(json.dumps({"monthly": [row("month", "2026-10")],
                                                         "totals": {**comps, "totalTokens": 100}}))
        fake = box.bin / "fake-turbotokens"
        codex = "exit 124" if codex_fails else 'cat "$D/agent.json"'
        fake.write_text("#!/bin/sh\n"
                        f"D='{fixtures}'\n"
                        'case "$1" in\n'
                        '  monthly) cat "$D/monthly.json" ;;\n'
                        '  daily) cat "$D/daily.json" ;;\n'
                        f"  codex) {codex} ;;\n"
                        '  *) cat "$D/agent.json" ;;\n'
                        "esac\n")
        fake.chmod(0o755)
        return fake

    def test_collector_refuses_a_ledger_where_a_failed_scan_erased_an_agent(self):
        """2026-10-20: agent-codex and codex-true timed out and fell back to empty;
        Codex fell from 39.85B to 22.69B while the overall total still grew, so
        the total guard alone published it."""
        with tempfile.TemporaryDirectory() as tmp:
            ledger = stale_ledger(generated_at="2026-10-20T16:14:31Z", total=1_000)
            ledger["agents"]["codex"] = {"totals": {"totalTokens": 10 ** 13}, "monthly": []}
            box = CollectorSandbox(tmp, ledger)
            before = box.digest("tokens.json")
            fake = self.fake_counter(box, codex_fails=True)
            result = box.run(CCUSAGE=str(fake), TOKENSTATS_AUDIT_DIR=str(box.tmp / "audit"))
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("agent total dropped (codex", result.stdout)
            self.assertNotIn("guard accepts", result.stdout)
            self.assertEqual(box.digest("tokens.json"), before)
            self.assertFalse((box.tmp / "audit" / "tokens.json").exists() and "guard accepts" in result.stdout)

    def test_collector_accepts_the_same_ledger_when_every_agent_holds(self):
        with tempfile.TemporaryDirectory() as tmp:
            box = CollectorSandbox(tmp, stale_ledger(generated_at="2026-10-20T16:14:31Z", total=1_000))
            fake = self.fake_counter(box, codex_fails=False)
            result = box.run(CCUSAGE=str(fake), TOKENSTATS_AUDIT_DIR=str(box.tmp / "audit"))
            self.assertIn("guard accepts", result.stdout, result.stdout + result.stderr)
            self.assertNotIn("agent total dropped", result.stdout)

    def test_audit_run_keeps_side_caches_and_ledger_out_of_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            box = CollectorSandbox(tmp, stale_ledger())
            # One new Grok inference, so grok_true_usage.py must rewrite its cache.
            (box.grok_home / "logs" / "unified.jsonl").write_text(json.dumps({
                "msg": "shell.turn.inference_done", "ts": "2026-10-17T10:00:00.000Z",
                "sid": "sandbox-session", "ctx": {"prompt_tokens": 100, "cached_prompt_tokens": 40,
                                                  "completion_tokens": 7, "loop_index": 0},
            }) + "\n")
            names = ("tokens.json", "grok-cache.json", "hermes-cache.json", "cursor-cache.json")
            before = box.digest(*names)
            audit = box.tmp / "audit"
            result = box.run(TOKENSTATS_AUDIT_DIR=str(audit))
            self.assertIn("audit mode", result.stdout, result.stderr)
            self.assertEqual(box.digest(*names), before)  # data/ byte-identical
            status = subprocess.run(["git", "-C", str(box.repo), "status", "--porcelain", "--", "data"],
                                    capture_output=True, text=True, check=True).stdout
            self.assertEqual(status, "")
            grok = json.loads((audit / "cache" / "grok-cache.json").read_text())
            self.assertIn("2026-10", grok["monthly"])
            self.assertTrue(any("sandbox-session" in seen for seen in grok["seen"]))
            for name in ("hermes-cache.json", "cursor-cache.json"):
                if (box.repo / "data" / name).exists():
                    self.assertTrue((audit / "cache" / name).exists(), name)
            self.assertEqual(box.intercepted(), [])

    # --- reconcile guards (network mocked) ------------------------------------

    NOW = datetime.datetime(2026, 10, 18, 12, 0, tzinfo=datetime.timezone.utc)

    def run_reconcile(self, server_total, ledger_age_hours=0.25, extra=(),
                      ledger_flag=False, ledger_total=1_000_000):
        """Run main() against a temp ledger with curl and the Keychain mocked.
        The temp file stands in for data/tokens.json (reconcile.LEDGER) unless
        ledger_flag passes it with --ledger instead."""
        with tempfile.TemporaryDirectory() as tmp:
            ledger = {
                "generated_at": (self.NOW - datetime.timedelta(hours=ledger_age_hours))
                .strftime("%Y-%m-%dT%H:%M:%SZ"),
                "totals": {"totalTokens": ledger_total, "inputTokens": 100_000,
                           "outputTokens": 50_000, "cacheCreationTokens": 50_000,
                           "cacheReadTokens": 800_000, "totalCost": 10.0,
                           "listValueUsd": 12.0},
                "monthly": [{"period": "2026-10", "modelBreakdowns": [{
                    "modelName": "claude-opus-4-8", "inputTokens": 100_000,
                    "outputTokens": 50_000, "cacheCreationTokens": 50_000,
                    "cacheReadTokens": 800_000, "cost": 10.0, "listValue": 12.0}]}],
                "agents": {"claude": {"totals": {"totalTokens": 1_000_000}}},
            }
            path = pathlib.Path(tmp) / "tokens.json"
            path.write_text(json.dumps(ledger))
            server = FakeServer(server_total)
            keychain_reads = []
            saved = reconcile._curl, reconcile.keychain_token, reconcile.LEDGER
            reconcile._curl = server
            reconcile.keychain_token = lambda: keychain_reads.append(1) or "test-token"
            argv = list(extra)
            if ledger_flag:
                argv += ["--ledger", str(path)]
            else:
                reconcile.LEDGER = path
            out = io.StringIO()
            try:
                with contextlib.redirect_stdout(out):
                    code = reconcile.main(argv, now=self.NOW)
            finally:
                reconcile._curl, reconcile.keychain_token, reconcile.LEDGER = saved
        return code, server, keychain_reads, out.getvalue()

    def test_reconcile_refuses_a_stale_ledger_without_any_network_call(self):
        code, server, keychain_reads, out = self.run_reconcile(2_000_000, ledger_age_hours=3)
        self.assertEqual(code, 2)
        self.assertEqual(server.calls, [])
        self.assertEqual(keychain_reads, [])
        self.assertIn("REFUSED", out)

    def test_reconcile_lowers_production_only_at_the_inflation_floor(self):
        code, server, _, out = self.run_reconcile(2_000_000)
        self.assertEqual(code, 0)
        self.assertEqual(len(server.posts), 1)
        payload = json.loads(server.posts[0][server.posts[0].index("--data-binary") + 1])
        self.assertTrue(payload["reconcile"])
        self.assertEqual(payload["tokens"]["total"], 1_000_000)
        self.assertIn("lower", out)

        for above in (1_030_000, 1_099_000):
            code, server, keychain_reads, out = self.run_reconcile(above)
            self.assertEqual((code, server.posts, keychain_reads), (0, [], []), above)
            self.assertIn("not lowering", out)

    def test_reconcile_raises_production_past_two_percent_drift(self):
        code, server, _, out = self.run_reconcile(950_000)
        self.assertEqual(code, 0)
        self.assertEqual(len(server.posts), 1)
        self.assertIn("raise", out)
        code, server, _, _ = self.run_reconcile(985_000)
        self.assertEqual((code, server.posts), (0, []))

    def test_reconcile_dry_run_reports_without_keychain_or_post(self):
        code, server, keychain_reads, out = self.run_reconcile(2_000_000, extra=["--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(server.posts, [])
        self.assertEqual(len(server.calls), 1)  # the read-only GET
        self.assertEqual(keychain_reads, [])
        self.assertIn("WOULD POST", out)
        self.assertIn("total=1,000,000", out)

    def test_reconcile_ledger_flag_is_always_a_dry_run(self):
        # Reviewer probe: a fresh 97.8B audit build passed with --ledger used
        # to POST and lower 131.6B production (1.346x is past the 1.10x floor).
        for extra in ((), ("--force",)):
            code, server, keychain_reads, out = self.run_reconcile(
                1_346_000, ledger_flag=True, extra=extra)
            self.assertEqual(code, 0)
            self.assertEqual(server.posts, [], extra)
            self.assertEqual(keychain_reads, [], extra)
            self.assertIn("--ledger audits only", out)
            self.assertIn("WOULD POST", out)

    def test_reconcile_refuses_unusable_server_or_ledger_totals(self):
        for total in (0, None, MISSING, "131573155351", True, -5, 1.5, float("nan")):
            code, server, keychain_reads, out = self.run_reconcile(total)
            self.assertEqual(code, 2, total)
            self.assertEqual(server.posts, [], total)
            self.assertEqual(keychain_reads, [], total)
            self.assertIn("REFUSED", out)
            self.assertIn("server total", out)
        for total in (0, True, None, "1000000"):
            code, server, keychain_reads, out = self.run_reconcile(2_000_000, ledger_total=total)
            self.assertEqual((code, server.calls, keychain_reads), (2, [], []), total)
            self.assertIn("ledger total", out)
        # A whole-number float total is a count (JSON has no int type).
        code, server, _, _ = self.run_reconcile(2_000_000.0)
        self.assertEqual((code, len(server.posts)), (0, 1))

    # --- cursor dashboard time budget -----------------------------------------

    def test_cursor_fetches_newest_months_first_and_caches_the_rest(self):
        months = [(f"2026-{m:02d}", m, m) for m in range(1, 11)]
        cache = {f"2026-{m:02d}": {"month": f"2026-{m:02d}", "inputTokens": 1, "outputTokens": 0,
                                    "cacheCreationTokens": 0, "cacheReadTokens": 0,
                                    "totalTokens": 1, "totalCost": 0.0, "models": {}}
                 for m in range(1, 10)}
        clock = {"t": 0.0}
        fetched = []

        def fetch(s_ms, e_ms):
            clock["t"] += 40  # every request is slow
            fetched.append(s_ms)
            return {"aggregations": [{"modelIntent": "gpt-5", "inputTokens": 10 * s_ms}]}

        out, degraded = cursor_usage.collect(months, fetch, cache, clock=lambda: clock["t"],
                                             budget=100, sleep=lambda _: None)
        self.assertEqual(fetched, [10, 9, 8])  # newest first, then the budget ran out
        by_month = {r["month"]: r["totalTokens"] for r in out["monthly"]}
        self.assertEqual(by_month["2026-10"], 100)  # the current month is live
        self.assertEqual(by_month["2026-08"], 80)
        self.assertEqual(by_month["2026-01"], 1)    # served from cache
        self.assertEqual([r["month"] for r in out["monthly"]], sorted(by_month))
        self.assertEqual(out["totals"]["totalTokens"], sum(by_month.values()))
        self.assertEqual(len(degraded), 7)

        def forbidden(s_ms, e_ms):
            raise urllib.error.HTTPError("u", 401, "no", {}, None)
        with self.assertRaises(urllib.error.HTTPError):
            cursor_usage.collect(months, forbidden, cache, clock=lambda: 0, sleep=lambda _: None)

    @staticmethod
    def token_event(input_tokens, cached_tokens, output_tokens, total_tokens, timestamp):
        return {
            "type": "event_msg",
            "timestamp": timestamp,
            "payload": {
                "type": "token_count",
                "info": {"total_token_usage": {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                }},
            },
        }


if __name__ == "__main__":
    unittest.main()
