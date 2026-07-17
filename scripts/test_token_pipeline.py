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


class TokenPipelineTests(unittest.TestCase):
    def test_accounting_revision_is_stable_for_one_time_consumer_adoption(self):
        self.assertEqual(build.ACCOUNTING_REVISION, "codex-cumulative-v1")

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
