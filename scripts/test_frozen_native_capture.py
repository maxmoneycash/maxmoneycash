"""Synthetic-only tests; no scanner, collector, credentials, or real ledger."""
import copy
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import frozen_native_capture as capture


def receipt():
    return {"protocol": "turbotokens-multisection-v1", "sourceID": "fixture-native",
            "scannerVersion": "turbotokens 1.1.4", "scannerSHA256": "a" * 64,
            "startedAt": "2026-09-03T00:00:00.000001Z", "endedAt": "2026-09-03T00:00:01.123456Z",
            "timezone": "UTC", "command": "monthly", "sections": ["daily", "monthly"],
            "allHistory": True, "offline": True, "byAgent": True, "processExitCode": 0}


def agent(name, tokens, *, residual=0, unallocated=0, cost=0):
    components = {"inputTokens": tokens - residual, "outputTokens": 0, "cacheReadTokens": 0, "cacheCreationTokens": 0}
    model = f"model/{name}"
    return {"agent": name, **components, "totalTokens": tokens, "totalCost": cost,
            "modelsUsed": [model],
            "modelBreakdowns": [{"modelName": model, **components, "inputTokens": tokens - residual - unallocated, "cost": cost}]}


def aggregate(rows, name="all"):
    models = {}
    for row in rows:
        for model in row["modelBreakdowns"]:
            if model["modelName"] not in models:
                models[model["modelName"]] = copy.deepcopy(model)
            else:
                for key in (*capture.COMPONENTS, "cost"):
                    models[model["modelName"]][key] += model[key]
    return {"agent": name, **{key: sum(row[key] for row in rows) for key in capture.COUNTERS},
            "totalCost": sum(row["totalCost"] for row in rows),
            "modelsUsed": sorted({name for row in rows for name in row["modelsUsed"]}),
            "modelBreakdowns": list(models.values())}


def period(day, agents):
    return {**aggregate(agents), "period": day, "metadata": {"agents": [row["agent"] for row in agents]}, "agents": copy.deepcopy(agents)}


def report(days=None):
    if days is None:
        days = [period("2026-08-31", [agent("claude", 100)]),
                period("2026-09-01", [agent("claude", 200), agent("new.provider", 300, residual=9, unallocated=20)]),
                period("2026-09-02", [agent("claude", 400)])]
    groups = {}
    for row in days:
        groups.setdefault(row["period"][:7], []).append(row)
    months = []
    for month, children in sorted(groups.items()):
        names = sorted({row["agent"] for day in children for row in day["agents"]})
        agents = [aggregate([row for day in children for row in day["agents"] if row["agent"] == name], name) for name in names]
        months.append(period(month, agents))
    return {"daily": days, "monthly": months,
            "totals": {**{key: sum(row[key] for row in months) for key in capture.COUNTERS},
                       "totalCost": sum(row["totalCost"] for row in months)}}


def encoded(value):
    return json.dumps(value, separators=(",", ":")).encode()


class FrozenNativeCaptureTests(unittest.TestCase):
    def split(self, value=None, **kwargs):
        return capture.split_native_capture(encoded(report() if value is None else value), receipt=receipt(), **kwargs).as_dict()

    def rejected(self, value, code=None, **kwargs):
        raw, declaration = encoded(value), receipt()
        before = (raw, copy.deepcopy(declaration), copy.deepcopy(kwargs))
        with self.assertRaises(capture.CaptureRejected) as error:
            capture.split_native_capture(raw, receipt=declaration, **kwargs)
        if code:
            self.assertEqual(error.exception.code, code)
        self.assertEqual((raw, declaration, kwargs), before)
        return error.exception

    def test_dynamic_provider_partition_preserves_seven_including_unknown_and_zero(self):
        names = ["claude", "codex", "grok", "hermes", "antigravity", "pi.custom", "never-seen-before"]
        agents = [agent(name, i * 17) for i, name in enumerate(names)]
        out = self.split(report([period("2026-09-01", agents)]))
        self.assertEqual([row["provider"] for row in out["providers"]], sorted(names))
        self.assertEqual(out["totals"]["totalTokens"], "357")
        self.assertEqual(sum(int(row["totals"]["totalTokens"]) for row in out["providers"]), 357)
        self.assertEqual(out["providers"][1]["provider"], "claude")
        self.assertEqual(out["providers"][1]["totals"]["totalTokens"], "0")

    def test_unknown_component_and_model_residuals_are_independent(self):
        out = self.split()
        self.assertEqual(out["totals"]["unclassifiedComponentTokens"], "9")
        self.assertEqual(out["totals"]["unallocatedModelTokens"], "29")
        unknown = next(row for row in out["providers"] if row["provider"] == "new.provider")
        self.assertEqual(unknown["monthly"][0]["inputTokens"], "291")
        self.assertEqual(unknown["monthly"][0]["modelBreakdowns"][0]["inputTokens"], "271")
        self.assertEqual(unknown["totals"]["totalTokens"], "300")
        self.assertEqual(out["costCoverage"], "unknown")

    def test_utc_month_fold_and_inclusive_cutoff_keep_full_history(self):
        out = self.split(daily_since="2026-09-01")
        self.assertEqual([(row["period"], row["totalTokens"]) for row in out["monthly"]], [("2026-08", "100"), ("2026-09", "900")])
        self.assertEqual(len(out["daily"]), 3)
        self.assertEqual([row["period"] for row in out["recentDaily"]], ["2026-09-01", "2026-09-02"])
        self.assertEqual(out["totals"]["totalTokens"], "1000")
        self.assertEqual(out["providers"][0]["totals"]["totalTokens"], "700")
        self.assertEqual(len(out["providers"][0]["recentDaily"]), 2)
        empty = self.split(daily_since="2026-09-03")
        self.assertEqual(empty["recentDaily"], [])
        self.assertEqual(empty["totals"], out["totals"])
        self.assertEqual(empty["captureID"], out["captureID"])

    def test_uint64_and_above_javascript_integer_limit_survive_exactly(self):
        for amount in [2**53 + 123, capture.MAX_COUNTER]:
            with self.subTest(amount=amount):
                out = self.split(report([period("2026-09-01", [agent("new-provider", amount)])]))
                self.assertEqual(out["totals"]["totalTokens"], str(amount))
                self.assertEqual(out["providers"][0]["monthly"][0]["modelBreakdowns"][0]["inputTokens"], str(amount))

    def test_overflow_is_rejected_without_rounding_or_truncating(self):
        self.rejected(report([period("2026-09-01", [agent("x", capture.MAX_COUNTER), agent("y", 1)])]), "invalid_counter")

    def test_exact_report_hash_receipt_identity_and_frozen_output(self):
        raw, declaration = encoded(report()), receipt()
        frozen = capture.split_native_capture(raw, receipt=declaration)
        view = frozen.as_dict()
        self.assertEqual(view["capture"]["reportSHA256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(view["capture"]["startedAt"], declaration["startedAt"])
        self.assertEqual(view["capture"]["endedAt"], declaration["endedAt"])
        self.assertEqual(view["capture"]["coverage"], "unknown")
        self.assertEqual(view["capture"]["receiptAttestation"], "caller-declared")
        self.assertEqual(frozen, capture.split_native_capture(raw, receipt=receipt()))
        declaration["sections"].append("session")
        view["monthly"].clear()
        self.assertEqual(len(frozen.as_dict()["monthly"]), 2)
        self.assertEqual(frozen.as_dict()["capture"]["sections"], ["daily", "monthly"])
        with self.assertRaises(FrozenInstanceError):
            frozen.encoded = b"{}"
        spaced = capture.split_native_capture(raw + b"\n", receipt=receipt()).as_dict()
        self.assertEqual(spaced["monthly"], frozen.as_dict()["monthly"])
        self.assertNotEqual(spaced["captureID"], frozen.as_dict()["captureID"])
        altered = receipt(); altered["scannerSHA256"] = "b" * 64
        self.assertNotEqual(capture.split_native_capture(raw, receipt=altered).as_dict()["captureID"], spaced["captureID"])

    def test_side_ownership_is_explicitly_unresolved_never_added_or_deduplicated(self):
        value = report([period("2026-09-01", [agent("grok", 100), agent("hermes", 100)])])
        sides = [{"sourceID": "legacy-grok", "provider": "grok"},
                 {"sourceID": "hermes-cloud", "provider": "hermes"},
                 {"sourceID": "legacy-only", "provider": "not-native"}]
        baseline = self.split(value)
        out = self.split(value, side_sources=sides)
        self.assertEqual(out["totals"], baseline["totals"])
        self.assertEqual(out["monthly"], baseline["monthly"])
        self.assertFalse(out["ownership"]["publicationAllowed"])
        rows = out["ownership"]["providers"]
        self.assertEqual([row["status"] for row in rows], ["unresolved-native-side-overlap", "unresolved-native-side-overlap", "unresolved-side-history"])
        self.assertTrue(all(row["additiveOwner"] is None for row in rows))
        self.assertIsNone(rows[2]["nativeSourceID"])
        self.assertEqual(rows[0]["sideSourceIDs"], ["legacy-grok"])
        self.assertEqual(baseline["ownership"]["inventoryCompleteness"], "unknown")

    def test_rejects_side_totals_duplicate_ids_and_private_fields(self):
        for sides in [[{"sourceID": "legacy", "provider": "grok", "totalTokens": 100}],
                      [{"sourceID": "fixture-native", "provider": "grok"}],
                      [{"sourceID": "same", "provider": "grok"}, {"sourceID": "same", "provider": "hermes"}],
                      [{"sourceID": "/private/raw/path", "provider": "grok"}]]:
            with self.subTest(sides=sides):
                error = self.rejected(report(), side_sources=sides)
                self.assertNotIn("/private/raw/path", str(error))

    def test_rejects_missing_or_partial_sections_before_any_output(self):
        for key in ["daily", "monthly", "totals"]:
            value = report(); del value[key]
            self.rejected(value, "unexpected_shape")
        value = report(); value["daily"].pop()
        self.rejected(value, "token_conservation")
        value = report(); value["monthly"].pop(0)
        self.rejected(value, "month_day_scope_mismatch")
        value = report(); value["totals"]["totalTokens"] += 1
        self.rejected(value, "root_conservation")

    def test_provider_omission_and_loss_cannot_hide_in_other_provider_growth(self):
        value = report()
        for key in ("inputTokens", "totalTokens"):
            value["monthly"][1]["agents"][0][key] -= 1
            value["monthly"][1]["agents"][1][key] += 1
        for key in ("inputTokens",):
            value["monthly"][1]["agents"][0]["modelBreakdowns"][0][key] -= 1
            value["monthly"][1]["agents"][1]["modelBreakdowns"][0][key] += 1
        self.rejected(value, "model_conservation")
        value = report(); value["monthly"][1]["agents"].pop()
        self.rejected(value, "provider_scope_mismatch")

    def test_model_attribution_cannot_move_between_providers_while_parent_stays_equal(self):
        value = report([period("2026-09-01", [agent("a", 100), agent("b", 100)])])
        a, b = value["monthly"][0]["agents"]
        a["modelsUsed"], b["modelsUsed"] = b["modelsUsed"], a["modelsUsed"]
        a["modelBreakdowns"], b["modelBreakdowns"] = b["modelBreakdowns"], a["modelBreakdowns"]
        self.rejected(value, "model_conservation")

    def test_provider_token_loss_cannot_hide_when_both_providers_share_one_model(self):
        agents = [agent("a", 100), agent("b", 100)]
        for row in agents:
            row["modelsUsed"] = ["shared-model"]
            row["modelBreakdowns"][0]["modelName"] = "shared-model"
        value = report([period("2026-09-01", agents)])
        for row, change in zip(value["monthly"][0]["agents"], [-1, 1]):
            row["inputTokens"] += change
            row["totalTokens"] += change
            row["modelBreakdowns"][0]["inputTokens"] += change
        self.rejected(value, "token_conservation")

    def test_duplicate_periods_providers_and_model_rows_are_rejected(self):
        value = report(); value["daily"].append(copy.deepcopy(value["daily"][0]))
        self.rejected(value, "future_or_duplicate_period")
        value = report(); value["monthly"][0]["agents"].append(copy.deepcopy(value["monthly"][0]["agents"][0]))
        self.rejected(value, "duplicate_provider")
        value = report(); value["monthly"][0]["modelBreakdowns"].append(copy.deepcopy(value["monthly"][0]["modelBreakdowns"][0]))
        self.rejected(value, "duplicate_or_undeclared_model")

    def test_malformed_counters_never_become_zero(self):
        for bad in [None, True, -1, "100", 100.0, 1.25, capture.MAX_COUNTER + 1]:
            with self.subTest(bad=bad):
                value = report(); value["monthly"][0]["inputTokens"] = bad
                self.rejected(value, "invalid_counter")
        value = report(); del value["monthly"][0]["outputTokens"]
        self.rejected(value, "unexpected_shape")

    def test_rejects_component_and_model_overallocation(self):
        value = report(); value["monthly"][0]["inputTokens"] = 101
        self.rejected(value, "component_overallocation")
        value = report(); value["monthly"][0]["modelBreakdowns"][0]["inputTokens"] = 101
        self.rejected(value, "model_overallocation")

    def test_reported_money_is_preserved_without_invented_cost_reconciliation(self):
        raw = encoded(report()).replace(b'"totalCost":0', b'"totalCost":0.12345678901234567890123456789')
        out = capture.split_native_capture(raw, receipt=receipt()).as_dict()
        self.assertEqual(out["totals"]["reportedCostUsd"], "0.12345678901234567890123456789")
        self.assertEqual(out["monthly"][0]["modelBreakdowns"][0]["reportedCostUsd"], "0")
        self.assertEqual(out["costConservation"], "not-attested")
        self.assertEqual(out["costCoverage"], "unknown")
        self.assertEqual(out["providers"][0]["totals"]["summedReportedCostUsd"], "0.24691357802469135780246913578")

    def test_invalid_money_and_exponent_bombs_are_rejected(self):
        for literal in [b'1e99999999', b'1e999999999999999999999999999999999',
                        b'0.' + b'1' * 257, b'-1', b'NaN', b'Infinity', b'null', b'true', b'"0"']:
            raw = encoded(report()).replace(b'"totalCost":0', b'"totalCost":' + literal, 1)
            with self.subTest(literal=literal), self.assertRaises(capture.CaptureRejected):
                capture.split_native_capture(raw, receipt=receipt())

    def test_exact_utc_scope_and_success_are_required_but_not_attested(self):
        for key, bad in [("timezone", "America/Los_Angeles"), ("allHistory", False), ("byAgent", False),
                         ("offline", False), ("processExitCode", 71), ("processExitCode", False),
                         ("sections", ["daily", "monthly", "session"]), ("sections", ["monthly", "monthly"]),
                         ("startedAt", "2026-09-04T00:00:00Z"), ("endedAt", "2026-09-03T00:00:00+00:00")]:
            declaration = receipt(); declaration[key] = bad
            with self.subTest(key=key, bad=bad), self.assertRaises(capture.CaptureRejected):
                capture.split_native_capture(encoded(report()), receipt=declaration)

    def test_gregorian_dates_and_future_data_are_rejected(self):
        for bad in ["2026-02-29", "2026-09-31", "0000-09-01", "2026-9-01", "2026-09-04"]:
            value = report(); value["daily"][0]["period"] = bad
            self.rejected(value)
        self.rejected(report(), "future_cutoff", daily_since="2026-09-04")
        leap = receipt(); leap.update(startedAt="2024-03-01T00:00:00Z", endedAt="2024-03-01T00:00:01Z")
        out = capture.split_native_capture(encoded(report([period("2024-02-29", [agent("a", 1)])])), receipt=leap).as_dict()
        self.assertEqual(out["monthly"][0]["period"], "2024-02")

    def test_duplicate_json_keys_invalid_utf8_truncation_and_unexpected_fields_fail(self):
        raw = encoded(report())
        bad_bodies = [raw[:-1], b'\xff', b'[]', b'{"monthly":[],"monthly":[]}',
                      raw.replace(b'"totalTokens":100', b'"totalTokens":100,"total\\u0054okens":100', 1)]
        for bad in bad_bodies:
            with self.subTest(body=bad[:30]), self.assertRaises(capture.CaptureRejected):
                capture.split_native_capture(bad, receipt=receipt())
        value = report(); value["private"] = "secret-not-in-error"
        error = self.rejected(value, "unexpected_shape")
        self.assertNotIn("secret-not-in-error", str(error))
        value = report(); value["monthly"][0]["metadata"]["degraded"] = True
        self.rejected(value, "unexpected_shape")

    def test_capacity_failure_is_explicit_and_never_truncates(self):
        with patch.object(capture, "MAX_MODEL_ROWS", 1):
            self.rejected(report(), "capacity")
        with patch.object(capture, "MAX_DAYS", 2):
            self.rejected(report(), "invalid_section_or_capacity")
        with patch.object(capture, "MAX_OUTPUT_BYTES", 100):
            self.rejected(report(), "capacity")
        with patch.object(capture, "MAX_BYTES", 100), self.assertRaises(capture.CaptureRejected):
            capture.split_native_capture(encoded(report()), receipt=receipt())

    def test_empty_report_remains_unknown_not_proof_of_zero_usage(self):
        out = self.split(report([]))
        self.assertEqual(out["providers"], [])
        self.assertEqual(out["totals"]["totalTokens"], "0")
        self.assertEqual(out["capture"]["coverage"], "unknown")
        self.assertFalse(out["ownership"]["publicationAllowed"])

    def test_success_and_failure_perform_no_io_and_preserve_last_good(self):
        raw, declaration, sides = encoded(report()), receipt(), [{"sourceID": "old", "provider": "grok"}]
        before = (raw, copy.deepcopy(declaration), copy.deepcopy(sides))
        with tempfile.TemporaryDirectory() as directory:
            last_good = Path(directory) / "synthetic-last-good.json"
            last_good.write_bytes(b'{"generated_at":"old","tokens":100}')
            original = (last_good.read_bytes(), last_good.stat().st_mtime_ns)
            with patch("builtins.open", side_effect=AssertionError("I/O prohibited")), patch("os.open", side_effect=AssertionError("I/O prohibited")), patch("subprocess.run", side_effect=AssertionError("subprocess prohibited")):
                capture.split_native_capture(raw, receipt=declaration, side_sources=sides)
                with self.assertRaises(capture.CaptureRejected):
                    capture.split_native_capture(raw[:-1], receipt=declaration, side_sources=sides)
            self.assertEqual((last_good.read_bytes(), last_good.stat().st_mtime_ns), original)
        self.assertEqual((raw, declaration, sides), before)

    def test_existing_sandboxed_scanner_fixture_conserves_all_sections(self):
        # Committed output of the earlier isolated synthetic scanner proof.
        # The scanner is not executed by this test.
        raw = (Path(__file__).parent / "fixtures/frozen-native-report-v1.json").read_bytes()
        declaration = receipt(); declaration.update(startedAt="2099-09-03T00:00:00Z", endedAt="2099-09-03T00:00:01Z")
        declaration["scannerSHA256"] = "b0ee8d1ed7961b851b664063705f17d47a55773969b54a4b6aa002e77f825911"
        out = capture.split_native_capture(raw, receipt=declaration, daily_since="2099-09-01").as_dict()
        self.assertEqual(out["totals"]["totalTokens"], "38863")
        self.assertEqual(out["totals"]["unclassifiedComponentTokens"], "109")
        self.assertEqual(out["totals"]["unallocatedModelTokens"], "109")
        self.assertEqual([row["totalTokens"] for row in out["monthly"]], ["175", "38688"])
        self.assertEqual([row["totalTokens"] for row in out["daily"]], ["175", "37108", "1580"])
        self.assertEqual(sum(int(row["totals"]["totalTokens"]) for row in out["providers"]), 38863)


if __name__ == "__main__":
    unittest.main()
