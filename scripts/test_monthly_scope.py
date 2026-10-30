import copy
import json
import tempfile
import unittest

import test_token_pipeline as pipeline
from validate_monthly_scope import validate


def fixture():
    usage = {"inputTokens": 10, "outputTokens": 3, "cacheReadTokens": 5,
             "cacheCreationTokens": 0, "totalTokens": 20, "totalCost": 2.5}
    return {"monthly": [{"period": "2026-10", **usage,
                         "metadata": {"agents": ["new-agent"]},
                         "modelBreakdowns": [{"modelName": "shared", **{k: v for k, v in usage.items()
                                              if k not in ("totalTokens", "totalCost")}, "cost": 2.5}],
                         "agents": [{"agent": "new-agent", **usage}]}], "totals": usage.copy()}


class MonthlyScopeTests(unittest.TestCase):
    def test_accepts_unknown_agents_and_headline_reasoning_without_mutation(self):
        report = fixture()
        before = copy.deepcopy(report)
        validate(report)
        self.assertEqual(report, before)
        validate({"monthly": [], "totals": {k: 0 for k in report["totals"]}})

    def test_rejects_missing_scope_grok_and_inconsistent_totals(self):
        for defect in ("no-agents", "no-metadata", "grok", "bad-count", "bad-total",
                       "bad-cost", "duplicate", "bad-headline", "missing-models", "wrong-model-cost"):
            with self.subTest(defect=defect):
                report = fixture()
                month = report["monthly"][0]
                if defect == "no-agents": del month["agents"]
                if defect == "no-metadata": del month["metadata"]
                if defect == "grok":
                    month["agents"][0]["agent"] = "grok"
                    month["metadata"]["agents"] = ["grok"]
                if defect == "bad-count": month["agents"][0]["inputTokens"] = True
                if defect == "bad-total": report["totals"]["totalTokens"] += 1
                if defect == "bad-cost": month["agents"][0]["totalCost"] = float("nan")
                if defect == "duplicate": month["agents"] *= 2
                if defect == "bad-headline": month["agents"][0]["totalTokens"] = 1
                if defect == "missing-models": month["modelBreakdowns"] = []
                if defect == "wrong-model-cost": month["modelBreakdowns"][0]["cost"] = 0
                with self.assertRaises(ValueError): validate(report)

    def test_collector_excludes_only_monthly_scan_and_preserves_real_grok_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            box = pipeline.CollectorSandbox(tmp, pipeline.stale_ledger(total=1_000))
            fake = pipeline.TokenPipelineTests().fake_counter(box, codex_fails=False)
            trace = box.tmp / "scope-trace"
            fake.write_text(fake.read_text().replace('#!/bin/sh\n',
                '#!/bin/sh\nprintf "%s|%s|%s\\n" "$1" "$GROK_HOME" "$*" >> ' + str(trace) + '\n'))
            before = box.digest("tokens.json", "grok-cache.json")
            audit = box.tmp / "audit"
            result = box.run(CCUSAGE=str(fake), TOKENSTATS_AUDIT_DIR=str(audit))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("guard accepts", result.stdout)
            calls = [line.split("|", 2) for line in trace.read_text().splitlines()]
            for name, grok_home, args in calls:
                if name == "monthly":
                    self.assertNotEqual(grok_home, str(box.grok_home))
                    self.assertTrue(grok_home.endswith("/grok-excluded"))
                    self.assertIn("--by-agent", args)
                else:
                    self.assertEqual(grok_home, str(box.grok_home))
            self.assertEqual(box.digest("tokens.json", "grok-cache.json"), before)
            saved = json.loads((audit / "cache/grok-cache.json").read_text())
            self.assertGreater(sum(m["totalTokens"] for m in saved["monthly"].values()), 0)

    def test_collector_aborts_on_invalid_scope_or_failed_durable_scan_without_strict_mode(self):
        for defect in ("native-grok", "missing-breakdown", "cache-unreadable", "cache-missing",
                       "multiple-homes", "empty-home", "missing-home"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as tmp:
                box = pipeline.CollectorSandbox(tmp, pipeline.stale_ledger(total=1_000))
                fake = pipeline.TokenPipelineTests().fake_counter(box, codex_fails=False)
                monthly = box.tmp / "fake-counter/monthly.json"
                data = json.loads(monthly.read_text())
                if defect == "native-grok":
                    data["monthly"][0]["agents"][0]["agent"] = "grok"
                    data["monthly"][0]["metadata"]["agents"] = ["grok"]
                if defect == "missing-breakdown": del data["monthly"][0]["agents"]
                monthly.write_text(json.dumps(data))
                if defect == "cache-unreadable": (box.repo / "data/grok-cache.json").write_text('{"monthly":')
                if defect == "cache-missing":
                    (box.repo / "data/grok-cache.json").unlink()
                    ledger = pipeline.stale_ledger(total=1_000)
                    ledger["agents"]["grok"] = {"totals": {"totalTokens": 100}}
                    (box.repo / "data/tokens.json").write_text(json.dumps(ledger))
                before = box.digest("tokens.json", "grok-cache.json")
                env = {"GROK_HOME": str(box.grok_home) + ",other"} if defect == "multiple-homes" else {}
                if defect == "empty-home": env["GROK_HOME"] = ""
                if defect == "missing-home": env["GROK_HOME"] = str(box.tmp / "missing-home")
                audit = box.tmp / "audit"
                result = box.run(CCUSAGE=str(fake), TOKENSTATS_AUDIT_DIR=str(audit), **env)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse((audit / "tokens.json").exists())
                self.assertEqual(box.digest("tokens.json", "grok-cache.json"), before)
                if defect in ("cache-unreadable", "cache-missing"):
                    self.assertIn("durable Grok scan failed", result.stdout)
                if defect == "cache-missing": self.assertFalse((audit / "cache/grok-cache.json").exists())


if __name__ == "__main__":
    unittest.main()
