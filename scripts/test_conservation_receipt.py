"""Synthetic inputs only. Never invoke collect_tokens or read repository data."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import conservation_receipt as receipt


SCRIPTS = Path(__file__).resolve().parent
RUN_ID = "c" * 32


def counters(n=0):
    return {"inputTokens": n, "outputTokens": 0, "cacheReadTokens": 0,
            "cacheCreationTokens": 0, "totalTokens": n}


def aggregate(n=0, period="2026-09", unified=False):
    row = {"period" if unified else "month": period, **counters(n), "totalCost": 0,
           "modelBreakdowns": [], "models": {}, "modelsUsed": []}
    return {"monthly": [row], "totals": {**counters(n), "totalCost": 0}}


def fixture(root, variant="correction"):
    root.mkdir()
    values = {"monthly.json": aggregate(10, unified=True), "daily.json": {"daily": []},
              "codex-true.json": aggregate(3), "kimi-true.json": aggregate(2)}
    for name in receipt.PROVIDERS[:5]:
        values[f"agent-{name}.json"] = aggregate(0)
    # Codex replacement clips 10 - 20 to zero then adds 3. Kimi then gives 4.
    values["agent-codex.json"] = aggregate(20)
    values["agent-kimi.json"] = aggregate(1)
    if variant == "sides":
        values.update({"cursor.json": aggregate(5), "grok-true.json": aggregate(7), "hermes-true.json": aggregate(11)})
    if variant == "empty":
        for name in values:
            if name != "daily.json":
                values[name] = {"totals": {}, "monthly": []}
    if variant == "duplicate":
        values["monthly.json"]["monthly"].append(copy.deepcopy(values["monthly.json"]["monthly"][0]))
    if variant == "large":
        values["monthly.json"] = aggregate(2**100, unified=True)
    if variant == "floor":
        values["monthly.json"]["monthly"][0]["totalTokens"] = 0
    if variant == "oversized":
        values["monthly.json"]["monthly"] = [aggregate(1, f"{2000+i//12:04d}-{i%12+1:02d}", True)["monthly"][0]
                                                for i in range(receipt.MAX_ROWS + 1)]
    # Arbitrary identifiers must never appear in private receipt projections.
    values["monthly.json"]["monthly"][0:1] = [dict(row, private="PRIVATE-PROMPT-SECRET", modelsUsed=["PRIVATE-MODEL"])
                                               for row in values["monthly.json"]["monthly"][0:1]]
    for name, value in values.items():
        (root / name).write_text(json.dumps(value))
    baseline = aggregate(6, unified=True)
    baseline.update({"daily": [], "agents": {"claude": aggregate(8)}})
    (root / "baseline.json").write_text(json.dumps(baseline))
    return root / "baseline.json"


def environment(directory=None, run_id=RUN_ID):
    env = dict(os.environ)
    for name in ("TOKENSTATS_RECEIPT_DIR", "TOKENSTATS_RECEIPT_RUN_ID"):
        env.pop(name, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if directory is not None:
        env.update(TOKENSTATS_RECEIPT_DIR=str(directory), TOKENSTATS_RECEIPT_RUN_ID=run_id)
    return env


def invoke(script, args, env):
    return subprocess.run([sys.executable, "-B", str(SCRIPTS / script), *map(str, args)],
                          capture_output=True, env=env, timeout=20)


def public_bytes(raw):
    # Retain exact serialized bytes, including field order and number spelling.
    return re.sub(rb'"generated_at": "[^"]+"', b'"generated_at": "CLOCK"', raw, count=1)


class ConservationReceiptTests(unittest.TestCase):
    def test_projection_unknown_zero_precision_privacy_and_nonmutation(self):
        value = {"totals": {**counters(2**100), "outputTokens": True, "cacheReadTokens": "2"},
                 "monthly": [{"month": "PRIVATE-PATH", **counters()}, {"month": "2026-09", **counters(4)}],
                 "agents": {"PRIVATE-ACCOUNT": {"totals": counters(), "monthly": []}}, "secret": "PRIVATE-PROMPT"}
        before = copy.deepcopy(value)
        projected = receipt.projection(value)
        self.assertEqual(value, before)
        self.assertEqual(projected["totals"]["inputTokens"], str(2**100))
        self.assertIsNone(projected["totals"]["outputTokens"])
        self.assertIsNone(projected["totals"]["cacheReadTokens"])
        self.assertIsNone(projected["monthly"][0]["period"])
        self.assertEqual(projected["monthly"][0]["counters"]["totalTokens"], "0")
        self.assertEqual(projected["providers"][0]["provider"], "other")
        self.assertNotIn("PRIVATE", json.dumps(projected))
        self.assertNotEqual(receipt.projection({}), receipt.projection({"monthly": [], "totals": counters()}))
        self.assertEqual(receipt.projection({})["monthlyState"], "absent")
        absent = receipt.projection({"agents": {"claude": {}}})["providers"][0]["aggregate"]
        invalid = receipt.projection({"agents": {"claude": {"monthly": None}}})["providers"][0]["aggregate"]
        self.assertEqual(absent["monthlyState"], "absent")
        self.assertEqual(invalid["monthlyState"], "invalid")
        for bad in (None, True, "0", 0.0, -1, [], {}, float("nan")):
            self.assertIsNone(receipt.vector({"totalTokens": bad})["totalTokens"])
        with self.assertRaises(receipt.DiagnosticError):
            receipt.vector({"totalTokens": 10**1024})

    def test_disabled_recorder_has_no_diagnostic_io(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(receipt, "PrivateStore", side_effect=AssertionError("I/O")), \
                patch.object(Path, "read_bytes", side_effect=AssertionError("I/O")):
            r = receipt.Recorder.from_environment("merge")
            self.assertFalse(r.enabled)
            r.snapshot("final", {})
            r.output("monthly.json", "{}", {})
            r.omitted("baseline.json")
            stream = io.StringIO()
            self.assertIs(r.stdout(stream), stream)
            r.finish(); r.close()

    def test_actual_merge_build_parity_and_stage_receipt(self):
        for variant in ("correction", "sides", "empty", "duplicate", "large", "floor"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory(prefix="receipt-fixture-") as temp:
                root = Path(temp); baseline = fixture(root / "source", variant)
                outputs = []
                for enabled in (False, True):
                    merged = root / ("on" if enabled else "off")
                    env = environment(root / "private" if enabled else None)
                    result = invoke("merge_token_sources.py", [merged, f"PRIVATE-HOST:{root / 'source'}"], env)
                    self.assertEqual(result.returncode, 0, result.stderr.decode())
                    result = invoke("build_tokens_json.py", [merged, baseline], env)
                    self.assertEqual(result.returncode, 0, result.stderr.decode())
                    self.assertEqual(result.stderr, b"")
                    outputs.append(result.stdout)
                self.assertEqual(public_bytes(outputs[0]), public_bytes(outputs[1]))
                self.assertEqual({p.name: p.read_bytes() for p in (root / "off").iterdir()},
                                 {p.name: p.read_bytes() for p in (root / "on").iterdir()})
                stored = json.loads((root / "private" / (RUN_ID + "-build.json")).read_text())
                self.assertEqual(stored["diagnosticStatus"], "recorded")
                self.assertEqual(stored["mergeBinding"], "matched")
                self.assertEqual(stored["candidateOutputSHA256"], hashlib.sha256(outputs[1]).hexdigest())
                self.assertEqual(stored["captureState"], "unknown")
                self.assertEqual(stored["fallbackState"], "unknown")
                self.assertNotIn("PRIVATE", json.dumps(stored))
                stages = {e["stage"]: e["projection"] for e in stored["events"] if e["kind"] == "stage"}
                if variant == "correction":
                    for stage, expected in (("monthly.before-codex", "10"), ("monthly.after-codex", "3"),
                                            ("monthly.after-kimi", "4"), ("monthly.after-baseline", "10")):
                        self.assertEqual(stages[stage]["monthly"][0]["counters"]["totalTokens"], expected)
                base_event = next(e for e in stored["events"] if e.get("role") == "baseline.json")
                self.assertEqual(base_event["contentSHA256"], hashlib.sha256(baseline.read_bytes()).hexdigest())
                self.assertEqual(stat.S_IMODE((root / "private").stat().st_mode), 0o700)
                for p in (root / "private").iterdir():
                    self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)

    def test_missing_merge_context_or_changed_input_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); baseline = fixture(root / "source")
            private = root / "private"; merged = root / "merged"
            env = environment(private)
            self.assertEqual(invoke("merge_token_sources.py", [merged, root / "source"], env).returncode, 0)
            original = (merged / "monthly.json").read_bytes()
            (merged / "monthly.json").write_bytes(original + b"\n")
            result = invoke("build_tokens_json.py", [merged, baseline], env)
            self.assertEqual(result.returncode, 0)
            stored = json.loads((private / (RUN_ID + "-build.json")).read_text())
            self.assertEqual(stored["mergeBinding"], "mismatch")
            self.assertEqual(stored["diagnosticStatus"], "incomplete")
            result2 = invoke("build_tokens_json.py", [merged, baseline], environment(private, "d" * 32))
            self.assertEqual(public_bytes(result.stdout), public_bytes(result2.stdout))
            stored = json.loads((private / ("d" * 32 + "-build.json")).read_text())
            self.assertEqual(stored["mergeBinding"], "unknown")
            self.assertEqual(stored["diagnosticStatus"], "incomplete")

    def test_missing_optional_empty_and_not_requested_are_distinct(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); fixture(root / "source")
            (root / "source" / "cursor.json").write_text(" \r\n")
            env = environment(root / "private")
            merged = root / "merged"
            self.assertEqual(invoke("merge_token_sources.py", [merged, root / "source"], env).returncode, 0)
            result = invoke("build_tokens_json.py", [merged], env)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            stored = json.loads((root / "private" / (RUN_ID + "-build.json")).read_text())
            self.assertEqual(stored["diagnosticStatus"], "recorded")
            merge_events = stored["merge"]["events"]
            self.assertEqual(next(e for e in merge_events if e.get("role") == "cursor.json")["readState"], "empty")
            events = {e["role"]: e for e in stored["events"] if e["kind"] == "input"}
            self.assertEqual(events["cursor.json"]["readState"], "missing")
            self.assertEqual(events["baseline.json"]["readState"], "not-requested")

    def test_input_decoding_errors_and_actual_byte_hash_preserved(self):
        for raw, expected in ((b"{", json.JSONDecodeError), (b" \r\n", FileNotFoundError), (b"\xff", UnicodeDecodeError)):
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "input.json"; path.write_bytes(raw)
                r = receipt.Recorder(); r.enabled = True
                r.document = {"events": [], "errors": []}
                with self.assertRaises(expected):
                    r.load(path, "monthly.json")
                self.assertEqual(r.document["events"][0]["contentSHA256"], hashlib.sha256(raw).hexdigest())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path = root / "input.json"; path.write_bytes(b'{\r\n"monthly":[]}')
            r = receipt.Recorder(); r.enabled = True; r.document = {"events": [], "errors": []}
            self.assertEqual(r.load(path, "monthly.json"), {"monthly": []})
            self.assertEqual(r.document["events"][0]["contentSHA256"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_failed_and_oversized_diagnostics_do_not_change_public_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); baseline = fixture(root / "source")
            merged = root / "merged"
            self.assertEqual(invoke("merge_token_sources.py", [merged, root / "source"], environment()).returncode, 0)
            before = invoke("build_tokens_json.py", [merged, baseline], environment())
            bad = root / "not-directory"; bad.write_text("sentinel")
            after = invoke("build_tokens_json.py", [merged, baseline], environment(bad))
            self.assertEqual(after.returncode, 0)
            self.assertEqual(public_bytes(before.stdout), public_bytes(after.stdout))
            self.assertEqual(after.stderr, b"conservation receipt unavailable: storage\n")
            self.assertEqual(bad.read_text(), "sentinel")
            # Oversize only the diagnostic provider projection; no real input.
            with patch.dict(os.environ, environment(root / "private"), clear=True), context_stderr():
                r = receipt.Recorder.from_environment("build")
                r.snapshot("final", {"monthly": [{}] * (receipt.MAX_ROWS + 1)})
                stream = io.StringIO(); r.stdout(stream).write("unchanged public bytes")
                r.finish(); r.close()
            stored = json.loads((root / "private" / (RUN_ID + "-build.json")).read_text())
            self.assertEqual(stream.getvalue(), "unchanged public bytes")
            self.assertEqual(stored["diagnosticStatus"], "error")
            self.assertIn("bounds", stored["errors"])

    def test_stdout_flush_failure_never_records_candidate_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); baseline = fixture(root / "source")
            merged = root / "merged"; private = root / "private"
            env = environment(private)
            self.assertEqual(invoke("merge_token_sources.py", [merged, root / "source"], env).returncode, 0)
            code = '''import runpy, sys
class FailedFlush:
    encoding = "utf-8"
    def write(self, text): return len(text)
    def flush(self): raise OSError("synthetic flush failure")
sys.path.insert(0, sys.argv[1])
sys.argv = [sys.argv[1] + "/build_tokens_json.py", *sys.argv[2:]]
sys.stdout = FailedFlush()
runpy.run_path(sys.argv[0], run_name="__main__")
'''
            result = subprocess.run([sys.executable, "-B", "-c", code, str(SCRIPTS), str(merged), str(baseline)],
                                    env=env, capture_output=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            stored = json.loads((private / (RUN_ID + "-build.json")).read_text())
            self.assertEqual(stored["diagnosticStatus"], "incomplete")
            self.assertNotIn("candidateOutputSHA256", stored)

    def test_actual_oversize_does_not_change_merge_or_build(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); baseline = fixture(root / "source", "oversized")
            outputs = []
            for enabled in (False, True):
                merged = root / ("on" if enabled else "off")
                env = environment(root / "private" if enabled else None)
                result = invoke("merge_token_sources.py", [merged, root / "source"], env)
                self.assertEqual(result.returncode, 0)
                result = invoke("build_tokens_json.py", [merged, baseline], env)
                self.assertEqual(result.returncode, 0)
                outputs.append(result.stdout)
            self.assertEqual(public_bytes(outputs[0]), public_bytes(outputs[1]))
            for phase in ("merge", "build"):
                stored = json.loads((root / "private" / (RUN_ID + "-" + phase + ".json")).read_text())
                self.assertEqual(stored["diagnosticStatus"], "error")
                self.assertLess((root / "private" / (RUN_ID + "-" + phase + ".json")).stat().st_size, receipt.MAX_BYTES)

    def test_postrename_sync_failure_marks_visible_receipt_error(self):
        with tempfile.TemporaryDirectory() as temp, context_stderr():
            private = Path(temp) / "private"
            with patch.dict(os.environ, environment(private), clear=True):
                r = receipt.Recorder.from_environment("merge")
                sync = os.fsync
                def fail_directory(fd):
                    if fd == r.store.fd:
                        raise OSError("synthetic sync failure")
                    sync(fd)
                with patch.object(os, "fsync", side_effect=fail_directory):
                    r.finish()
                r.close()
            stored = json.loads((private / (RUN_ID + "-merge.json")).read_text())
            self.assertEqual(stored["diagnosticStatus"], "error")
            self.assertEqual(stored["errors"], ["storage"])

    def test_actual_invalid_json_keeps_original_failure_and_partial_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); fixture(root / "source")
            (root / "source" / "monthly.json").write_bytes(b"{")
            disabled = invoke("merge_token_sources.py", [root / "off", root / "source"], environment())
            enabled = invoke("merge_token_sources.py", [root / "on", root / "source"], environment(root / "private"))
            self.assertEqual(disabled.returncode, enabled.returncode)
            self.assertNotEqual(enabled.returncode, 0)
            self.assertEqual(disabled.stdout, enabled.stdout)
            stored = json.loads((root / "private" / (RUN_ID + "-merge.json")).read_text())
            self.assertEqual(stored["diagnosticStatus"], "incomplete")
            self.assertEqual(stored["events"][0]["readState"], "invalid")

    def test_private_store_permissions_symlinks_retention_and_atomic_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); store = receipt.PrivateStore(root / "private")
            try:
                for i in range(receipt.MAX_RECORDS + 3):
                    store.write(f"{i:032x}-merge.json", b"{}")
                self.assertEqual(len(list((root / "private").iterdir())), receipt.MAX_RECORDS)
                name = "e" * 32 + "-merge.json"
                store.write(name, b"original")
                with patch.object(os, "replace", side_effect=OSError("PRIVATE exception")):
                    with self.assertRaises(OSError):
                        store.write(name, b"new")
                self.assertEqual(store.read(name), b"original")
                self.assertFalse(any(p.name.startswith(".receipt-") for p in (root / "private").iterdir()))
            finally:
                store.close()
            (root / "link").symlink_to(root / "private")
            with self.assertRaises(OSError):
                receipt.PrivateStore(root / "link")
            weak = root / "weak"; weak.mkdir(mode=0o755)
            with self.assertRaises(receipt.DiagnosticError):
                receipt.PrivateStore(weak)

    def test_untrusted_context_cannot_inject_private_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            private = Path(temp) / "private"
            with patch.dict(os.environ, environment(private), clear=True):
                r = receipt.Recorder.from_environment("merge"); r.finish(); r.close()
                file = private / (RUN_ID + "-merge.json")
                value = json.loads(file.read_text()); value["PRIVATE-KEY"] = "PRIVATE-VALUE"
                file.write_text(json.dumps(value))
                with context_stderr() as log:
                    r = receipt.Recorder.from_environment("build"); r.finish(); r.close()
                self.assertNotIn("PRIVATE", log.getvalue())
            result = json.loads((private / (RUN_ID + "-build.json")).read_text())
            self.assertEqual(result["diagnosticStatus"], "error")
            self.assertEqual(result["errors"], ["context"])
            self.assertNotIn("PRIVATE", json.dumps(result))


def context_stderr():
    from contextlib import redirect_stderr
    return redirect_stderr(io.StringIO())


if __name__ == "__main__":
    unittest.main()
