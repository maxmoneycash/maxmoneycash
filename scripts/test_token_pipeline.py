#!/usr/bin/env python3
import contextlib
import datetime
import importlib.util
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
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
