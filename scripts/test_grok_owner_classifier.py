"""Small synthetic fixtures from the pinned native/side conformance matrix."""
import copy
import json
import unittest
from unittest.mock import patch

import grok_owner_classifier as owner
import grok_true_usage as grok


def scope():
    return {"sourceID": "synthetic-root", "legacySourceID": "synthetic-root",
            "nativeSourceIDs": ["synthetic-root"], "sideSourceIDs": ["synthetic-root"],
            "captureComplete": True, "legacyIdentityCoverage": "complete", "timezone": "UTC"}


def baseline():
    usage = {**owner.empty_usage(), "inputTokens": 77, "totalTokens": 77}
    return {"version": 2, "seen": ["synthetic-cache|2098-01-02T12:00:00Z|1|77"],
            "monthly": {"2098-01": {**usage, "calls": 1, "models": {"unknown": dict(usage)}}}}


def inference(session="synthetic-active", timestamp="2101-01-02T12:00:00Z", loop=1,
              prompt=100, completion=20, reasoning=5, origin="active"):
    ctx = {"loop_index": loop, "cached_prompt_tokens": 40,
           "completion_tokens": completion, "reasoning_tokens": reasoning}
    if prompt is not None:
        ctx["prompt_tokens"] = prompt
    return {"sourceID": "synthetic-root", "origin": origin, "nativeModel": "unknown", "ownerModel": "unknown",
            "record": {"sid": session, "ts": timestamp, "msg": "shell.turn.inference_done", "ctx": ctx}}


def union_records():
    return [inference(), inference(session="synthetic-rotated", timestamp="2104-01-02T12:00:00Z", origin="rotated"),
            inference(session="synthetic-native-only", timestamp="2109-01-02T12:00:00Z", prompt=None)]


class OwnerClassifierTests(unittest.TestCase):
    def proposed(self, records, legacy=None, declaration=None, continuation=None):
        result = owner.classify_owner(baseline() if legacy is None else legacy, records,
                                      scope() if declaration is None else declaration, continuation)
        self.assertEqual(result["status"], "proposed", result)
        self.assertIs(result["publicationAllowed"], False)
        self.assertIs(result["lifetimeCertified"], False)
        return result

    def held(self, reason, records=None, legacy=None, declaration=None, continuation=None):
        args = [baseline() if legacy is None else legacy, [] if records is None else records,
                scope() if declaration is None else declaration, continuation]
        before = copy.deepcopy(args)
        result = owner.classify_owner(*args)
        self.assertEqual(result["status"], "held", result)
        self.assertEqual(result["reason"], reason)
        self.assertEqual(set(result), {"protocol", "status", "reason", "publicationAllowed", "lifetimeCertified"})
        self.assertIs(result["publicationAllowed"], False)
        self.assertEqual(args, before)
        return result

    def test_measured_352_union_preserves_exact_legacy_and_separate_reasoning(self):
        old = baseline()
        before = json.dumps(old, sort_keys=True)
        result = self.proposed(union_records(), legacy=old)
        self.assertEqual(result["proposedTotals"]["totalTokens"], 352)
        self.assertEqual(result["newUsage"]["totalTokens"], 275)
        self.assertEqual(result["proposedTotals"], {"inputTokens": 197, "outputTokens": 75,
                         "cacheCreationTokens": 0, "cacheReadTokens": 80, "totalTokens": 352})
        self.assertEqual(result["baseline"], old)
        self.assertEqual(json.dumps(old, sort_keys=True), before)
        native_only = next(e for e in result["events"] if e["identity"]["sessionID"] == "synthetic-native-only")
        self.assertEqual(native_only["payload"]["completionTokens"], 20)
        self.assertEqual(native_only["payload"]["reasoningTokens"], 5)
        self.assertIsNone(native_only["sideKey"])
        # Proposal output is independent of the caller's subsequently edited copy.
        result["baseline"]["monthly"]["2098-01"]["models"]["unknown"]["inputTokens"] = 0
        self.assertEqual(json.dumps(old, sort_keys=True), before)

    def test_exact_keys_and_structured_identity_are_retained(self):
        event = self.proposed([inference()])["events"][0]
        self.assertEqual(event["nativeKey"], "synthetic-active:2101-01-02T12:00:00Z:60:20:40:5:unknown")
        self.assertEqual(event["sideKey"], "synthetic-active|2101-01-02T12:00:00Z|1|100")
        self.assertEqual(event["identity"], {"sourceID": "synthetic-root", "sessionID": "synthetic-active",
                         "instantUTC": "2101-01-02T12:00:00.000000000Z", "loopIndex": 1})

    def test_replay_adds_zero_and_continuation_preserves_now_missing_raw_history(self):
        first = self.proposed(union_records())
        again = self.proposed(union_records(), continuation=first["continuation"])
        missing = self.proposed([], continuation=again["continuation"])
        for result in [again, missing]:
            self.assertEqual(result["proposedTotals"], first["proposedTotals"])
            self.assertEqual(result["additionalMonthly"], first["additionalMonthly"])
            self.assertEqual(result["newUsage"], owner.empty_usage())
            self.assertEqual(result["retainedUsage"]["totalTokens"], 275)
        self.assertEqual(missing["continuation"], first["continuation"])

    def test_real_new_event_after_replay_is_admitted_once(self):
        first = self.proposed(union_records())
        added = self.proposed([inference(session="synthetic-new")], continuation=first["continuation"])
        self.assertEqual(added["proposedTotals"]["totalTokens"], 477)
        self.assertEqual(added["newUsage"]["totalTokens"], 125)
        replay = self.proposed([inference(session="synthetic-new")], continuation=added["continuation"])
        self.assertEqual(replay["proposedTotals"]["totalTokens"], 477)
        self.assertEqual(replay["newUsage"]["totalTokens"], 0)

    def test_active_rotated_duplicates_count_once_and_order_is_deterministic(self):
        active = inference()
        rotated = inference(origin="rotated")
        one = self.proposed([active, rotated, active])
        two = self.proposed([rotated, active])
        self.assertEqual(one, two)
        self.assertEqual(one["proposedTotals"]["totalTokens"], 202)
        self.assertEqual(one["events"][0]["origins"], ["active", "rotated"])

    def test_same_side_key_changed_completion_holds_whole_proposal(self):
        self.held("changed_payload", [inference(), inference(completion=30)])

    def test_different_loops_same_native_key_hold_whole_proposal(self):
        self.held("native_key_collision", [inference(loop=1), inference(loop=2)])

    def test_changed_payload_against_continuation_holds_without_partial_admission(self):
        previous = self.proposed([inference()])["continuation"]
        self.held("changed_payload", [inference(session="unrelated-new"), inference(completion=30)], continuation=previous)

    def test_continuation_rejects_native_loop_collision_and_missing_prompt_alias(self):
        previous = self.proposed([inference(loop=1)])["continuation"]
        self.held("native_key_collision", [inference(loop=2)], continuation=previous)
        previous = self.proposed([inference(prompt=None)])["continuation"]
        self.held("changed_payload", [inference(prompt=0)], continuation=previous)

    def test_alias_timestamps_hold_even_with_identical_usage(self):
        for timestamp in ["2101-01-02T14:00:00+02:00", "2101-01-02T12:00:00.000Z"]:
            self.held("timestamp_alias", [inference(), inference(timestamp=timestamp)])

    def test_timestamp_alias_cannot_evade_native_collision_by_changing_loop(self):
        first = inference(loop=1)
        alias = inference(loop=2, timestamp="2101-01-02T14:00:00+02:00")
        for rows in [[first, alias], [alias, first]]:
            self.held("timestamp_alias", rows)
        previous = self.proposed([first])["continuation"]
        self.held("timestamp_alias", [alias], continuation=previous)

    def test_different_raw_source_witnesses_hold_in_every_order_and_origin(self):
        for origin in ["active", "rotated"]:
            for label in [None, "source-a"]:
                first, other = inference(), inference(origin=origin)
                if label is not None:
                    first["record"]["src"] = label
                other["record"]["src"] = "source-b"
                for rows in [[first, other], [other, first]]:
                    self.held("source_witness_conflict", rows)
                previous = self.proposed([first])["continuation"]
                self.held("source_witness_conflict", [other], continuation=previous)

    def test_same_origin_witness_cannot_silently_replace_equivalent_raw_evidence(self):
        explicit = inference(reasoning=0)
        omitted = copy.deepcopy(explicit)
        del omitted["record"]["ctx"]["reasoning_tokens"]
        for rows in [[explicit, omitted], [omitted, explicit]]:
            self.held("source_witness_conflict", rows)
        previous = self.proposed([explicit])["continuation"]
        self.held("source_witness_conflict", [omitted], continuation=previous)

    def test_matching_raw_source_is_preserved_without_order_dependence(self):
        first, rotated = inference(), inference(origin="rotated")
        for row in [first, rotated]:
            row["record"]["src"] = "source-a"
        one = self.proposed([first, rotated])
        self.assertEqual(one, self.proposed([rotated, first]))
        self.assertEqual(one["events"][0]["sourceLabel"], "source-a")
        self.assertEqual(one["newUsage"]["totalTokens"], 125)

    def test_deep_baseline_metadata_returns_fixed_hold_without_mutation(self):
        old = baseline()
        nested = []
        for _ in range(1500):
            nested = [nested]
        old["monthly"]["2098-01"]["metadata"] = nested
        result = owner.classify_owner(old, [], scope())
        self.assertEqual(result, {"protocol": owner.PROTOCOL, "status": "held", "reason": "invalid_json_value",
                                 "publicationAllowed": False, "lifetimeCertified": False})
        self.assertEqual(old["seen"], baseline()["seen"])
        month = old["monthly"]["2098-01"]
        self.assertEqual({k: v for k, v in month.items() if k != "metadata"}, baseline()["monthly"]["2098-01"])
        self.assertIs(month["metadata"], nested)
        for _ in range(1500):
            self.assertEqual(len(nested), 1)
            nested = nested[0]
        self.assertEqual(nested, [])

    def test_nanosecond_distinct_timestamps_do_not_collapse_to_native_message_milliseconds(self):
        rows = [inference(timestamp="2101-01-02T12:00:00.000000001Z"),
                inference(timestamp="2101-01-02T12:00:00.000000002Z")]
        result = self.proposed(rows)
        self.assertEqual(result["proposedTotals"]["totalTokens"], 327)
        self.assertEqual(len(result["events"]), 2)

    def test_new_utc_period_does_not_rebase_legacy_month_or_model(self):
        old = baseline()
        old["seen"] = ["synthetic-cache|2098-01-01T00:30:00+02:00|1|77"]
        result = self.proposed([inference(timestamp="2112-01-01T00:30:00+02:00")], legacy=old)
        self.assertEqual(set(result["baseline"]["monthly"]), {"2098-01"})
        self.assertEqual(result["baseline"], old)
        self.assertEqual(set(result["additionalMonthly"]), {"2111-12"})

    def test_known_legacy_key_is_covered_without_readding_or_reattributing(self):
        row = inference(session="synthetic-cache", timestamp="2098-01-02T12:00:00Z", prompt=77,
                        completion=0, reasoning=0)
        row["nativeModel"], row["ownerModel"] = "future-model", "unknown"
        result = self.proposed([row])
        self.assertEqual(result["proposedTotals"]["totalTokens"], 77)
        self.assertEqual(result["additionalMonthly"], {})
        self.assertEqual(result["events"][0]["disposition"], "covered")
        self.assertEqual(result["baseline"], baseline())

    def test_zero_rows_and_unknown_cached_components_are_preserved_exactly(self):
        old = baseline()
        month = old["monthly"]["2098-01"]
        for row in [month, month["models"]["unknown"]]:
            row["cacheCreationTokens"] = 5
            row["totalTokens"] += 5
        old["monthly"]["2097-12"] = {**owner.empty_usage(), "calls": 0, "models": {}}
        result = self.proposed([], legacy=old)
        self.assertEqual(result["baseline"], old)
        self.assertEqual(result["proposedTotals"]["totalTokens"], 82)
        self.assertEqual(result["proposedTotals"]["cacheCreationTokens"], 5)

    def test_unknown_owner_model_remains_unknown_even_if_native_used_future_model(self):
        row = inference()
        row["nativeModel"] = "synthetic-future-model"
        result = self.proposed([row])
        self.assertEqual(set(result["additionalMonthly"]["2101-01"]["models"]), {"unknown"})

    def test_legacy_prompt_or_timestamp_alias_is_not_new_work(self):
        self.held("legacy_record_alias", [inference(session="synthetic-cache", timestamp="2098-01-02T12:00:00Z")])
        self.held("legacy_record_alias", [inference(session="synthetic-cache", timestamp="2098-01-02T14:00:00+02:00", prompt=77)])
        self.held("legacy_record_alias", [inference(session="synthetic-cache", timestamp="2098-01-02T12:00:00Z", prompt=None)])

    def test_missing_legacy_raw_cannot_prove_new_loop_disjoint(self):
        old = baseline()
        usage = {"inputTokens": 60, "outputTokens": 25, "cacheCreationTokens": 0,
                 "cacheReadTokens": 40, "totalTokens": 125}
        old["seen"] = ["synthetic-collision|2101-01-02T12:00:00Z|1|100"]
        old["monthly"] = {"2101-01": {**usage, "calls": 1, "models": {"unknown": dict(usage)}}}
        current = inference(session="synthetic-collision", loop=2)
        self.held("legacy_loop_overlap_unknown", [current], legacy=old)

    def test_legacy_new_loop_guard_covers_timezone_and_precision_aliases(self):
        for timestamp in ["2098-01-02T12:00:00Z", "2098-01-02T14:00:00+02:00",
                          "2098-01-02T12:00:00.000000000Z"]:
            self.held("legacy_loop_overlap_unknown", [inference(session="synthetic-cache", timestamp=timestamp,
                                                                 loop=2, prompt=77)])

    def test_current_legacy_witness_does_not_certify_the_missing_historical_payload(self):
        old_witness = inference(session="synthetic-cache", timestamp="2098-01-02T12:00:00Z", prompt=77,
                                completion=0, reasoning=0)
        # Different current payload means native keys differ, but the archived
        # event's true per-event payload is unavailable. Neither input order
        # may silently turn that uncertainty into fresh work.
        candidate = inference(session="synthetic-cache", timestamp="2098-01-02T12:00:00Z", loop=2, prompt=77)
        for rows in [[old_witness, candidate], [candidate, old_witness]]:
            self.held("legacy_loop_overlap_unknown", rows)

    def test_legacy_loop_guard_applies_to_untrusted_continuation_too(self):
        previous = self.proposed([])["continuation"]
        previous["admittedRecords"] = [inference(session="synthetic-cache", timestamp="2098-01-02T12:00:00Z",
                                                  loop=2, prompt=77)]
        self.held("legacy_loop_overlap_unknown", continuation=previous)

    def test_distinct_instant_or_session_after_legacy_still_admits_known_new_work(self):
        for row in [inference(session="synthetic-cache", timestamp="2098-01-02T12:00:01Z", loop=2, prompt=77),
                    inference(session="synthetic-other", timestamp="2098-01-02T12:00:00Z", loop=2, prompt=77)]:
            result = self.proposed([row])
            self.assertEqual(result["newUsage"]["totalTokens"], 102)
            self.assertEqual(result["proposedTotals"]["totalTokens"], 179)

    def test_unknown_legacy_ids_and_missing_loop_hold_without_guessing(self):
        for key in ["unknown", "synthetic-cache|2098-01-02T12:00:00Z||77",
                    "synthetic-cache|2098-01-02T12:00:00Z|1|None"]:
            old = baseline(); old["seen"] = [key]
            self.held("unknown_legacy_identity", legacy=old)
        row = inference(); del row["record"]["ctx"]["loop_index"]
        self.held("unsupported_shape", [row])

    def test_legacy_alias_and_per_month_coverage_mismatch_hold(self):
        old = baseline()
        old["seen"].append("synthetic-cache|2098-01-02T14:00:00+02:00|1|77")
        old["monthly"]["2098-01"]["calls"] = 2
        self.held("legacy_identity_alias", legacy=old)
        old = baseline(); old["seen"] = ["synthetic-cache|2098-02-02T12:00:00Z|1|77"]
        self.held("legacy_period_coverage", legacy=old)
        old = baseline(); old["seen"] = ["synthetic-cache|2098-01-02T12:00:00Z|1|78"]
        self.held("legacy_period_coverage", legacy=old)

    def test_reviewed_legacy_identity_coverage_gate_is_required(self):
        old = baseline(); old["monthly"]["2098-01"]["calls"] = 2
        self.held("unknown_identity_coverage", legacy=old)
        with patch.object(grok, "LEGACY_SEEN_CAP", 1):
            self.held("unknown_identity_coverage")

    def test_declared_scope_must_be_single_complete_common_source(self):
        for key, value, reason in [
            ("nativeSourceIDs", ["synthetic-root", "other"], "uncertain_source_scope"),
            ("sideSourceIDs", [], "uncertain_source_scope"),
            ("legacySourceID", "other", "uncertain_source_scope"),
            ("captureComplete", False, "incomplete_declared_coverage"),
            ("captureComplete", 1, "incomplete_declared_coverage"),
            ("legacyIdentityCoverage", "unknown", "incomplete_declared_coverage"),
            ("timezone", "local", "incomplete_declared_coverage"),
        ]:
            declaration = scope(); declaration[key] = value
            self.held(reason, declaration=declaration)
        row = inference(); row["sourceID"] = "other"
        self.held("uncertain_record_scope", [row])

    def test_event_file_is_not_a_usage_source(self):
        row = inference(); row["origin"] = "events"
        self.held("uncertain_record_scope", [row])

    def test_continuation_cannot_cross_baseline_or_scope(self):
        previous = self.proposed([inference()])["continuation"]
        tampered = copy.deepcopy(previous); tampered["baselineSHA256"] = "0" * 64
        self.held("continuation_boundary_changed", continuation=tampered)
        old = baseline(); old["version"] = 3
        self.held("continuation_boundary_changed", legacy=old, continuation=previous)
        tampered = copy.deepcopy(previous); tampered["scope"]["sourceID"] = "other"
        self.held("continuation_boundary_changed", continuation=tampered)

    def test_continuation_cannot_claim_baseline_events_again(self):
        previous = self.proposed([])["continuation"]
        previous["admittedRecords"] = [inference(session="synthetic-cache", timestamp="2098-01-02T12:00:00Z", prompt=77)]
        self.held("continuation_overlaps_baseline", continuation=previous)

    def test_malformed_values_and_counter_overflow_hold(self):
        for value in [-1, True, 1.25, "100", None, float("inf")]:
            row = inference(); row["record"]["ctx"]["prompt_tokens"] = value
            reason = "invalid_json_value" if value == float("inf") else "invalid_counter"
            self.held(reason, [row])
        self.held("invalid_counter", [inference(prompt=owner.U64)])
        self.held("invalid_counter", [inference(prompt=owner.U64 - 25)])

    def test_unknown_shapes_models_and_timestamp_offsets_hold(self):
        row = inference(); row["record"]["ctx"]["new_field"] = 1
        self.held("unsupported_shape", [row])
        row = inference(); row["ownerModel"] = "unverified-other"
        self.held("conflicting_model_evidence", [row])
        self.held("unknown_timestamp_offset", [inference(timestamp="2101-01-02T12:00:00-00:00")])
        self.held("unsupported_timestamp", [inference(timestamp="2101-02-30T12:00:00Z")])

    def test_resource_exhaustion_holds_instead_of_truncating(self):
        with patch.object(owner, "MAX_RECORDS", 1):
            self.held("record_capacity", union_records())
        with patch.object(owner, "MAX_BYTES", 32):
            self.held("byte_capacity", [inference()])
        row = inference(); row["record"]["sid"] = "x" * 513
        self.held("invalid_text", [row])

    def test_no_discovery_or_persistence_functions_are_called(self):
        with patch.object(grok, "load_cache", side_effect=AssertionError("read")), \
             patch.object(grok, "save_cache", side_effect=AssertionError("write")), \
             patch.object(grok, "usage_records", side_effect=AssertionError("discover")), \
             patch.object(grok, "model_timelines", side_effect=AssertionError("discover")):
            self.assertEqual(self.proposed(union_records())["proposedTotals"]["totalTokens"], 352)


if __name__ == "__main__":
    unittest.main()
