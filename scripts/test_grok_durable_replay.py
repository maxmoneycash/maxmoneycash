"""Synthetic-only tests; the real parser runs solely against task-owned paths."""
import contextlib
import copy
import io
import json
import os
import pathlib
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

import grok_true_usage as grok


def record(identity, tokens=1, month="2099-09", model="synthetic-model"):
    usage = dict.fromkeys(grok.COMPONENTS, 0)
    usage.update(inputTokens=tokens, totalTokens=tokens)
    return {"id": identity, "month": month, "model": model, "usage": usage}


def cache(tokens=77, version=2):
    month = grok.empty_month()
    month.update(inputTokens=tokens, totalTokens=tokens, calls=1)
    month["models"] = {"unknown": record("historical", tokens)["usage"]}
    return {"version": version, "monthly": {"2098-01": month}, "seen": ["cache-only-history"]}


def raw_event(index):
    return {"ts": "2099-09-30T00:00:00Z", "sid": "synthetic", "msg": "shell.turn.inference_done",
            "ctx": {"loop_index": index, "prompt_tokens": 1}}


class DurableReplayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="synthetic-grok-replay-")
        self.root = pathlib.Path(self.temporary.name)
        self.path = self.root / "cache.json"
        self.home = self.root / "source"
        (self.home / "logs").mkdir(parents=True)
        self.patches = [patch.object(grok, "CACHE", self.path), patch.object(grok, "GROK_HOME", self.home)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temporary.cleanup()

    def write(self, value):
        self.path.write_text(json.dumps(value))
        return self.path.read_bytes(), self.path.stat().st_mtime_ns

    def run_parser(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            grok.main()
        return json.loads(output.getvalue())

    def assert_held_unchanged(self, reason):
        before = self.path.read_bytes(), self.path.stat().st_mtime_ns
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaisesRegex(grok.CollectionHeld, reason):
            grok.main()
        self.assertEqual(out.getvalue(), "")
        self.assertEqual((self.path.read_bytes(), self.path.stat().st_mtime_ns), before)

    def test_more_than_100k_rotated_records_replay_adds_zero_and_preserves_cache_only_history(self):
        self.write(cache())
        log = self.home / "logs" / "unified.jsonl.1"
        with log.open("w") as output:
            for i in range(100_001):
                output.write(json.dumps(raw_event(i)) + "\n")
        first = self.run_parser()
        stored = json.loads(self.path.read_text())
        first_bytes, first_time = self.path.read_bytes(), self.path.stat().st_mtime_ns
        self.assertEqual(first["totals"]["totalTokens"], 100_078)
        self.assertEqual(len(stored["seen"]), 100_002)
        self.assertEqual(stored["version"], 3)
        self.assertEqual(stored["monthly"]["2098-01"], cache()["monthly"]["2098-01"])
        second = self.run_parser()
        self.assertEqual(second["totals"], first["totals"])
        self.assertEqual(second["monthly"], first["monthly"])
        self.assertEqual((self.path.read_bytes(), self.path.stat().st_mtime_ns), (first_bytes, first_time))
        # File naming/order is not identity: retained rotation remains a replay.
        log.rename(self.home / "logs" / "unified.jsonl.2")
        (self.home / "logs" / "unified.jsonl").write_text(json.dumps(raw_event(100_001)) + "\n")
        third = self.run_parser()
        self.assertEqual(third["totals"]["totalTokens"], first["totals"]["totalTokens"] + 1)
        self.assertEqual(third["monthly"][0], first["monthly"][0])

    def test_same_id_in_active_and_rotated_files_is_added_once(self):
        line = json.dumps(raw_event(1)) + "\n"
        for name in ["unified.jsonl", "unified.jsonl.1"]:
            (self.home / "logs" / name).write_text(line)
        self.assertEqual(self.run_parser()["totals"]["totalTokens"], 1)
        self.assertEqual(self.run_parser()["totals"]["totalTokens"], 1)

    def test_v1_complete_subcap_migration_keeps_unknown_rotated_history(self):
        old = cache(version=1)
        del old["monthly"]["2098-01"]["models"]
        before = copy.deepcopy(old)
        migrated = grok.accumulate_cache(old, [record("new", 3)])
        self.assertEqual(old, before)
        self.assertEqual(migrated["monthly"]["2098-01"]["totalTokens"], 77)
        self.assertEqual(migrated["monthly"]["2098-01"]["models"]["unknown"]["totalTokens"], 77)
        self.assertEqual(migrated["seen"], ["cache-only-history", "new"])

    def test_legacy_at_cap_and_evicted_cache_hold_before_source_read(self):
        for count in [100_000, 100_001]:
            old = cache(tokens=count)
            old["seen"] = [f"synthetic-{i}" for i in range(100_000)]
            old["monthly"]["2098-01"]["calls"] = count
            self.write(old)
            with patch.object(grok, "model_timelines", side_effect=AssertionError("must not read sources")):
                self.assert_held_unchanged("unknown_identity_coverage")

    def test_missing_or_inconsistent_legacy_identity_coverage_cannot_be_reset(self):
        cases = []
        old = cache(); old["monthly"]["2098-01"]["calls"] = 2; cases.append(old)
        old = cache(); del old["monthly"]["2098-01"]["calls"]; cases.append(old)
        old = cache(); old["monthly"]["2098-01"]["calls"] = 0; old["seen"] = []; cases.append(old)
        old = cache(); old["seen"] = ["same", "same"]; cases.append(old)
        old = cache(); old["monthly"] = []; cases.append(old)
        for old in cases:
            self.write(old)
            self.assert_held_unchanged("unknown_identity_coverage|duplicate_cached_identity|invalid_cache")

    def test_missing_cache_only_is_a_fresh_start(self):
        self.assertEqual(grok.load_cache(), {"version": 3, "monthly": {}, "seen": []})
        for raw in [b"", b"{broken", b'null', b'{"monthly":{},"monthly":{},"seen":[]}']:
            self.path.write_bytes(raw)
            self.assert_held_unchanged("invalid_cache|duplicate_cache_key")

    def test_exact_capacity_replay_allowed_new_identity_holds_without_eviction(self):
        old = cache(version=3)
        with patch.object(grok, "MAX_SEEN_IDS", 2):
            full = grok.accumulate_cache(old, [record("second")])
            self.write(full)
            self.assertEqual(grok.accumulate_cache(full, [record("second")]), full)
            before = copy.deepcopy(full)
            with self.assertRaisesRegex(grok.CollectionHeld, "identity_capacity"):
                grok.accumulate_cache(full, [record("third")])
            self.assertEqual(full, before)
            (self.home / "logs" / "unified.jsonl").write_text(json.dumps(raw_event(1)) + "\n")
            self.assert_held_unchanged("identity_capacity")

    def test_cache_bytes_capacity_and_oversized_identity_hold_unchanged(self):
        original = cache(version=3)
        self.write(original)
        before = self.path.read_bytes(), self.path.stat().st_mtime_ns
        with patch.object(grok, "MAX_CACHE_BYTES", 32):
            self.assert_held_unchanged("cache_byte_capacity")
            with self.assertRaisesRegex(grok.CollectionHeld, "cache_byte_capacity"):
                grok.save_cache(original)
            with self.assertRaisesRegex(grok.CollectionHeld, "cache_byte_capacity"):
                grok.accumulate_cache(original, [record("new")])
        with self.assertRaisesRegex(grok.CollectionHeld, "invalid_identity"):
            grok.accumulate_cache(original, [record("x" * 513)])
        self.assertEqual((self.path.read_bytes(), self.path.stat().st_mtime_ns), before)

    def test_input_identity_capacity_holds_before_any_cache_write(self):
        self.write(cache(version=3))
        log = self.home / "logs" / "unified.jsonl"
        log.write_text("".join(json.dumps(raw_event(i)) + "\n" for i in range(3)))
        with patch.object(grok, "MAX_SEEN_IDS", 2):
            self.assert_held_unchanged("input_identity_capacity")

    def test_atomic_replace_failure_keeps_counters_and_identities_together(self):
        old = cache(version=3)
        self.write(old)
        before = self.path.read_bytes(), self.path.stat().st_mtime_ns
        candidate = grok.accumulate_cache(old, [record("new")])
        with patch.object(grok.os, "replace", side_effect=OSError("synthetic disk failure")):
            with self.assertRaises(OSError):
                grok.save_cache(candidate)
        self.assertEqual((self.path.read_bytes(), self.path.stat().st_mtime_ns), before)
        self.assertEqual(list(self.root.glob(".grok-cache-*")), [])
        grok.save_cache(candidate)
        self.assertEqual(grok.load_cache(), candidate)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_serialization_failure_keeps_exact_cache_and_emits_no_partial_result(self):
        self.write(cache(version=3))
        with patch.object(grok.json, "dumps", side_effect=ValueError("synthetic-private-value")):
            self.assert_held_unchanged("cache_serialization_failed")

    def test_lock_contention_holds_without_reading_sources_or_mutating_cache(self):
        self.write(cache(version=3))
        with grok.cache_lock(), patch.object(grok, "model_timelines", side_effect=AssertionError("source read")):
            self.assert_held_unchanged("concurrent_cache_writer")
        self.assertEqual(self.run_parser()["totals"]["totalTokens"], 77)

    def test_invalid_counter_or_model_fold_does_not_rewrite_history(self):
        for value in [-1, True, 1.5, "1"]:
            old = cache(); old["monthly"]["2098-01"]["inputTokens"] = value
            self.write(old); self.assert_held_unchanged("invalid_counters")
        old = cache(); old["monthly"]["2098-01"]["models"]["unknown"]["inputTokens"] = 76
        self.write(old); self.assert_held_unchanged("inconsistent_counters")
        old = cache(); old["monthly"]["2098-01"]["models"] = {}
        self.write(old); self.assert_held_unchanged("inconsistent_models")

    def test_cli_unknown_history_exits_nonzero_without_partial_output_or_identifiers(self):
        scripts = self.root / "scripts"; scripts.mkdir()
        data = self.root / "data"; data.mkdir()
        entrypoint = scripts / "grok_true_usage.py"
        entrypoint.write_bytes(pathlib.Path(grok.__file__).read_bytes())
        old = cache(); old["seen"] = ["synthetic-private-identity"]
        old["monthly"]["2098-01"]["calls"] = 2
        destination = data / "grok-cache.json"
        destination.write_text(json.dumps(old))
        before = destination.read_bytes(), destination.stat().st_mtime_ns
        env = {"GROK_HOME": str(self.home), "PATH": os.defpath, "HOME": os.environ["HOME"]}
        result = subprocess.run([sys.executable, "-B", str(entrypoint)], env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "Grok collection held: unknown_identity_coverage; prior cache retained\n")
        self.assertEqual((destination.read_bytes(), destination.stat().st_mtime_ns), before)


if __name__ == "__main__":
    unittest.main()
