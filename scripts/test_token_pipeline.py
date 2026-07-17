#!/usr/bin/env python3
import importlib.util
import json
import pathlib
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


class TokenPipelineTests(unittest.TestCase):
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

    def test_accounting_revision_is_stable_for_one_time_consumer_adoption(self):
        self.assertEqual(build.ACCOUNTING_REVISION, "codex-cumulative-v1")
        with open(ROOT.parent / "data" / "tokens.json") as fh:
            artifact = json.load(fh)
        self.assertEqual(
            artifact.get("corrections", {}).get("accountingRevision"),
            build.ACCOUNTING_REVISION,
        )
        for month in artifact.get("monthly", []):
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
