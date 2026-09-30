"""Synthetic-only tests; this module never reads the repository's real data."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from token_accounting import COMPONENTS, audit_aggregate


FIELDS = (*COMPONENTS, "totalTokens")


def counters(**values):
    row = dict.fromkeys(FIELDS, 0)
    row.update(values)
    return row


def write_builder_fixture(directory):
    """The existing pipeline's synthetic 122 headline / 80 provider example."""
    directory = Path(directory)
    def components(total):
        return counters(inputTokens=5, outputTokens=7, cacheCreationTokens=11,
                        cacheReadTokens=13, totalTokens=total)

    monthly = []
    agent_monthly = []
    for period, total in (("2026-06", 50), ("2026-07", 30)):
        monthly.append({"agent": "all", "period": period, **components(total),
                        "totalCost": 0, "modelsUsed": [], "modelBreakdowns": [],
                        "metadata": {"agents": ["droid"]}})
        agent_monthly.append({"month": period, **components(total),
                              "totalCost": 0, "modelsUsed": [], "models": {}})
    empty = {"totals": {}, "monthly": []}
    files = {"monthly.json": {"monthly": monthly}, "daily.json": {"daily": []},
             "codex-true.json": empty, "kimi-true.json": empty}
    for name in ("claude", "codex", "kimi", "opencode"):
        files[f"agent-{name}.json"] = empty
    files["agent-droid.json"] = {"totals": {**components(80), "totalCost": 0},
                                 "monthly": agent_monthly}
    files["baseline.json"] = {
        "totals": {**components(30), "totalCost": 0},
        "monthly": [{"agent": "all", "period": "2026-06", **components(30),
                     "totalCost": 0, "modelsUsed": [], "modelBreakdowns": [],
                     "metadata": {"agents": []}}],
        "daily": [], "agents": {},
    }
    for name, value in files.items():
        (directory / name).write_text(json.dumps(value))
    return directory / "baseline.json"


class AggregateAuditTests(unittest.TestCase):
    def test_matching_partitions_do_not_claim_coverage(self):
        row = counters(inputTokens=10, outputTokens=2, cacheReadTokens=3,
                       cacheCreationTokens=4, totalTokens=19)
        result = audit_aggregate(row, [row], {"private-provider-id": {"totals": row, "monthly": [row]}})
        for key in ("headlineMinusMonthly", "headlineMinusProviders", "providersMinusOwnMonths"):
            self.assertEqual(result[key]["status"], "match")
            self.assertEqual(result[key]["delta"], dict.fromkeys(FIELDS, "0"))
        self.assertEqual(result["totalMinusComponents"], dict.fromkeys(("headline", "monthly", "providers"), "0"))
        self.assertEqual(result["sourceCoverage"], "unknown")
        self.assertEqual(result["scopeOwnership"], "unknown")
        self.assertNotIn("private-provider-id", json.dumps(result))
        self.assertEqual(set(result), {"scope", "sourceCoverage", "scopeOwnership", "headlineMinusMonthly",
                                      "headlineMinusProviders", "providersMinusOwnMonths", "totalMinusComponents"})

    def test_retained_summary_arithmetic_without_provider_months(self):
        # Scalar aggregate values only, copied into this synthetic fixture.
        headline = counters(inputTokens=2_034_121_628, outputTokens=358_188_623,
                            cacheReadTokens=103_786_732_260, cacheCreationTokens=1_123_699_893,
                            totalTokens=107_306_025_736)
        providers = counters(inputTokens=1_977_604_871, outputTokens=357_641_873,
                             cacheReadTokens=103_112_546_150, cacheCreationTokens=1_123_699_893,
                             totalTokens=106_572_926_386)
        result = audit_aggregate(headline, [headline], {"synthetic-summary": {"totals": providers}})
        self.assertEqual(result["headlineMinusMonthly"]["status"], "match")
        self.assertEqual(result["headlineMinusProviders"]["status"], "mismatch")
        self.assertEqual(result["headlineMinusProviders"]["delta"], {
            "inputTokens": "56516757", "outputTokens": "546750", "cacheReadTokens": "674186110",
            "cacheCreationTokens": "0", "totalTokens": "733099350"})
        self.assertEqual(result["totalMinusComponents"], {
            "headline": "3283332", "monthly": "3283332", "providers": "1433599"})
        self.assertEqual(result["providersMinusOwnMonths"]["status"], "unknown")
        self.assertEqual(result["providersMinusOwnMonths"]["unavailableProviderRows"], 1)

    def test_signed_differences_and_component_mismatch_despite_equal_total(self):
        left = counters(inputTokens=8, outputTokens=2, totalTokens=10)
        right = counters(inputTokens=9, outputTokens=1, totalTokens=10)
        result = audit_aggregate(left, [right], {"p": {"totals": counters(totalTokens=12), "monthly": []}})
        self.assertEqual(result["headlineMinusMonthly"]["status"], "mismatch")
        self.assertEqual(result["headlineMinusMonthly"]["delta"]["inputTokens"], "-1")
        self.assertEqual(result["headlineMinusMonthly"]["delta"]["outputTokens"], "1")
        self.assertEqual(result["headlineMinusMonthly"]["delta"]["totalTokens"], "0")
        self.assertEqual(result["headlineMinusProviders"]["delta"]["totalTokens"], "-2")

    def test_opposite_provider_errors_cannot_cancel_status(self):
        ten = counters(inputTokens=10, totalTokens=10)
        twenty = counters(inputTokens=20, totalTokens=20)
        total = counters(inputTokens=30, totalTokens=30)
        providers = {"first": {"totals": ten, "monthly": [twenty]},
                     "second": {"totals": twenty, "monthly": [ten]}}
        result = audit_aggregate(total, [total], providers)["providersMinusOwnMonths"]
        self.assertEqual(result["delta"], dict.fromkeys(FIELDS, "0"))
        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(result["mismatchedProviderRows"], 2)
        self.assertEqual(result["unavailableProviderRows"], 0)

    def test_unavailable_counter_coordinate_never_becomes_zero(self):
        bad_values = [None, True, False, -1, "0", "30", 0.0, 1.5, float("nan"), float("inf"),
                      float("-inf"), [], {}]
        for field in FIELDS:
            for value in bad_values:
                with self.subTest(field=field, value=repr(value)):
                    row = counters(); row[field] = value
                    result = audit_aggregate(row, [counters()], {"p": {"totals": counters(), "monthly": [row]}})
                    self.assertEqual(result["headlineMinusMonthly"]["status"], "unknown")
                    self.assertIsNone(result["headlineMinusMonthly"]["delta"][field])
                    self.assertIsNone(result["totalMinusComponents"]["headline"])
                    self.assertEqual(result["providersMinusOwnMonths"]["unavailableProviderRows"], 1)
            row = counters(); del row[field]
            self.assertIsNone(audit_aggregate(row, [counters()], {})["headlineMinusMonthly"]["delta"][field])

    def test_unknown_is_absorbing_per_coordinate_and_known_mismatch_survives(self):
        partial = counters(inputTokens=1); del partial["outputTokens"]
        result = audit_aggregate(counters(), [partial, counters()], {})
        self.assertEqual(result["headlineMinusMonthly"]["status"], "mismatch")
        self.assertEqual(result["headlineMinusMonthly"]["delta"]["inputTokens"], "-1")
        self.assertIsNone(result["headlineMinusMonthly"]["delta"]["outputTokens"])
        self.assertEqual(result["headlineMinusMonthly"]["delta"]["cacheReadTokens"], "0")
        result = audit_aggregate(counters(), [], {"p": {"totals": counters(), "monthly": [partial]}})
        check = result["providersMinusOwnMonths"]
        self.assertEqual(check["status"], "mismatch")
        self.assertEqual(check["mismatchedProviderRows"], 1)
        self.assertEqual(check["unavailableProviderRows"], 1)

    def test_invalid_collections_and_malformed_children_are_unknown(self):
        for bad in (None, False, 0, "", {}, ()):
            result = audit_aggregate(counters(), bad, {})
            self.assertEqual(result["headlineMinusMonthly"]["status"], "unknown")
            self.assertEqual(result["headlineMinusMonthly"]["delta"], dict.fromkeys(FIELDS))
        for bad in (None, False, 0, "", [], ()):
            result = audit_aggregate(counters(), [], bad)
            self.assertEqual(result["headlineMinusProviders"]["status"], "unknown")
            self.assertEqual(result["providersMinusOwnMonths"]["status"], "unknown")
        for bad in (None, False, 0, "", []):
            result = audit_aggregate(counters(), [counters(), bad], {"p": bad})
            self.assertEqual(result["headlineMinusMonthly"]["delta"], dict.fromkeys(FIELDS))
            self.assertEqual(result["headlineMinusProviders"]["delta"], dict.fromkeys(FIELDS))
            self.assertEqual(result["providersMinusOwnMonths"]["unavailableProviderRows"], 1)
            self.assertEqual(result["providersMinusOwnMonths"]["status"], "unknown")

    def test_explicit_empty_and_zero_are_distinct_from_absence(self):
        result = audit_aggregate(counters(), [], {})
        self.assertEqual(result["headlineMinusMonthly"]["status"], "match")
        self.assertEqual(result["headlineMinusProviders"]["status"], "match")
        self.assertEqual(result["providersMinusOwnMonths"]["status"], "unknown")
        self.assertEqual(result["providersMinusOwnMonths"]["unavailableProviderRows"], 0)
        self.assertEqual(audit_aggregate(counters(), [], {"p": {"totals": counters(), "monthly": []}})
                         ["providersMinusOwnMonths"]["status"], "match")
        self.assertEqual(audit_aggregate(None, [], {})["headlineMinusMonthly"]["status"], "unknown")

    def test_large_integers_and_residuals_are_exact_canonical_strings(self):
        huge = 2 ** 100 + 2 ** 53 + 1
        row = counters(inputTokens=huge, totalTokens=huge + 3)
        result = audit_aggregate(row, [row, row], {"p": {"totals": row, "monthly": [row]}})
        self.assertEqual(result["headlineMinusMonthly"]["delta"]["inputTokens"], str(-huge))
        self.assertEqual(result["headlineMinusMonthly"]["delta"]["totalTokens"], str(-huge - 3))
        self.assertEqual(result["totalMinusComponents"], {"headline": "3", "monthly": "6", "providers": "3"})
        invalid_sum = counters(inputTokens=huge, totalTokens=huge - 1)
        result = audit_aggregate(invalid_sum, [invalid_sum], {})
        self.assertEqual(result["totalMinusComponents"]["headline"], "-1")
        self.assertEqual(result["headlineMinusMonthly"]["status"], "match")
        for check in ("headlineMinusMonthly", "headlineMinusProviders", "providersMinusOwnMonths"):
            for value in result[check]["delta"].values():
                if value is not None:
                    self.assertEqual(str(int(value)), value)
        self.assertEqual(json.loads(json.dumps(result)), result)

    def test_equal_duplicate_or_omitted_work_never_proves_coverage(self):
        for amount in (0, 10, 20):
            row = counters(inputTokens=amount, totalTokens=amount)
            result = audit_aggregate(row, [row], {"synthetic": {"totals": row, "monthly": [row]}})
            self.assertEqual(result["headlineMinusProviders"]["status"], "match")
            self.assertEqual(result["sourceCoverage"], "unknown")
            self.assertEqual(result["scopeOwnership"], "unknown")
            for field in ("complete", "reconciled", "safeToPublish", "pricingEligible"):
                self.assertNotIn(field, result)

    def test_deterministic_nonmutating_and_identifier_free(self):
        row = counters(inputTokens=9, totalTokens=9)
        row.update({"modelName": "PRIVATE-MODEL", "path": "PRIVATE-PATH", "cost": 1.5})
        totals = copy.deepcopy(row)
        monthly = [row]
        agents = {"PRIVATE-PROVIDER": {"totals": row, "monthly": monthly, "session": "PRIVATE-ID"}}
        before = copy.deepcopy((totals, monthly, agents))
        first = audit_aggregate(totals, monthly, agents)
        second = audit_aggregate(totals, monthly, agents)
        self.assertEqual(first, second)
        self.assertEqual((totals, monthly, agents), before)
        self.assertNotIn("PRIVATE", json.dumps(first))
        # Output mutations cannot change an input or a future diagnostic.
        first["headlineMinusMonthly"]["delta"]["inputTokens"] = "999"
        self.assertEqual(audit_aggregate(totals, monthly, agents), second)

    def test_synthetic_builder_preserves_legacy_values_and_attaches_audit(self):
        script = Path(__file__).with_name("build_tokens_json.py")
        with tempfile.TemporaryDirectory(prefix="aggregate-audit-test-") as tmp:
            baseline = write_builder_fixture(tmp)
            output = subprocess.check_output(
                [sys.executable, "-B", str(script), tmp, str(baseline)],
                env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=10)
        artifact = json.loads(output)
        self.assertEqual(artifact["totals"]["totalTokens"], 122)
        self.assertEqual(artifact["agents"]["droid"]["totals"]["totalTokens"], 80)
        self.assertEqual(sum(m["totalTokens"] for m in artifact["agents"]["droid"]["monthly"]), 86)
        self.assertEqual(artifact["corrections"]["accountingRevision"], "turbotokens-counter-v4")
        self.assertTrue(artifact["corrections"]["componentTotalsConserved"])
        result = artifact["corrections"]["aggregateAuditV1"]
        self.assertEqual(result, audit_aggregate(artifact["totals"], artifact["monthly"], artifact["agents"]))
        # Empty upstream totals are absent measurement, not explicit zero rows.
        self.assertIsNone(result["headlineMinusProviders"]["delta"]["totalTokens"])
        self.assertEqual(result["providersMinusOwnMonths"]["mismatchedProviderRows"], 1)
        self.assertEqual(result["providersMinusOwnMonths"]["unavailableProviderRows"], 7)
        self.assertEqual(result["providersMinusOwnMonths"]["status"], "mismatch")
        # The same numeric example with explicitly measured zero providers
        # exposes exact +42 / -6; the builder must not manufacture those zeros.
        agents = {
            name: row if name == "droid" else {"totals": counters(), "monthly": []}
            for name, row in artifact["agents"].items()
        }
        explicit = audit_aggregate(artifact["totals"], artifact["monthly"], agents)
        self.assertEqual(explicit["headlineMinusProviders"]["delta"]["totalTokens"], "42")
        self.assertEqual(explicit["providersMinusOwnMonths"]["delta"]["totalTokens"], "-6")


if __name__ == "__main__":
    unittest.main()
