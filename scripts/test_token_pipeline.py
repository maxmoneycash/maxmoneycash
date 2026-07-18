#!/usr/bin/env python3
import importlib.util
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
common = load_module("common")
accounting = load_module("token_accounting")
baseline = load_module("make_cloud_baseline")


class TokenPipelineTests(unittest.TestCase):
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
        tokens = {"sources": [
            {"label": "local", "totals": {"totalTokens": 100}},
            {"label": "cloud", "totals": {"totalTokens": 20}},
            {"label": "cloud-baseline", "totals": {"totalTokens": 30}},
            {"label": "cloud-hermes", "totals": {"totalTokens": 40}},
        ]}
        self.assertEqual(common.source_total(tokens, "cloud"), 90)
        self.assertEqual(common.source_total(tokens, "local"), 100)

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
        self.assertEqual(build.ACCOUNTING_REVISION, "headline-component-floor-v2")
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
