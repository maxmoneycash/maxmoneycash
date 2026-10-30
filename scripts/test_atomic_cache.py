import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import atomic_cache
import grok_true_usage


class AtomicUsageCacheTests(unittest.TestCase):
    def test_invalid_grok_history_is_never_replaced_by_a_fresh_empty_scan(self):
        with tempfile.TemporaryDirectory() as root:
            cache = pathlib.Path(root) / "grok-cache.json"
            env = {**os.environ, "TOKENSTATS_CACHE_DIR": root,
                   "GROK_HOME": str(pathlib.Path(root) / "empty-grok-home")}
            counts = {"inputTokens": 10, "outputTokens": 2, "cacheCreationTokens": 0,
                      "cacheReadTokens": 30, "totalTokens": 42}
            inconsistent = {"version": 2, "monthly": {"2026-08": {**counts,
                "models": {"old-model": {**counts, "inputTokens": 9, "totalTokens": 41}}}}, "seen": ["old"]}
            for invalid in (b'{"monthly":', b'{}', b'[]',
                            b'{"monthly":[],"seen":[]}',
                            b'{"version":3,"monthly":{},"seen":[]}',
                            b'{"monthly":{},"seen":[null]}',
                            json.dumps(inconsistent).encode()):
                cache.write_bytes(invalid)
                run = subprocess.run([sys.executable, grok_true_usage.__file__], env=env,
                                     capture_output=True, text=True, timeout=10)
                self.assertNotEqual(run.returncode, 0)
                self.assertIn("keeping the existing file", run.stderr)
                self.assertEqual(cache.read_bytes(), invalid)
                self.assertEqual(run.stdout, "")

    def test_missing_and_valid_legacy_grok_caches_keep_supported_startup_paths(self):
        with tempfile.TemporaryDirectory() as root:
            cache = pathlib.Path(root) / "grok-cache.json"
            env = {**os.environ, "TOKENSTATS_CACHE_DIR": root,
                   "GROK_HOME": str(pathlib.Path(root) / "empty-grok-home")}
            def run():
                return json.loads(subprocess.check_output(
                    [sys.executable, grok_true_usage.__file__], env=env, text=True, timeout=10))
            self.assertEqual(run()["totals"]["totalTokens"], 0)
            counts = {"inputTokens": 10, "outputTokens": 2, "cacheCreationTokens": 0,
                      "cacheReadTokens": 30, "totalTokens": 42}
            cache.write_text(json.dumps({"monthly": {"2026-08": {**counts, "calls": 1}}, "seen": ["old"]}))
            self.assertEqual(run()["totals"]["totalTokens"], 42)
            migrated = json.loads(cache.read_text())
            self.assertEqual(migrated["monthly"]["2026-08"]["models"]["unknown"], counts)
            self.assertEqual(migrated["seen"], ["old"])
            self.assertEqual(run()["totals"]["totalTokens"], 42)

    def test_unavailable_grok_cache_symlink_is_not_a_first_run(self):
        with tempfile.TemporaryDirectory() as root:
            cache = pathlib.Path(root) / "grok-cache.json"
            missing = pathlib.Path(root) / "unavailable-history.json"
            cache.symlink_to(missing)
            env = {**os.environ, "TOKENSTATS_CACHE_DIR": root,
                   "GROK_HOME": str(pathlib.Path(root) / "empty-grok-home")}
            result = subprocess.run([sys.executable, grok_true_usage.__file__], env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("keeping the existing file", result.stderr)
            self.assertTrue(cache.is_symlink())
            self.assertEqual(os.readlink(cache), str(missing))
            self.assertFalse(missing.exists())

    def test_failed_replace_preserves_grok_cache_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as root:
            path = pathlib.Path(root) / "grok-cache.json"
            original = b'{"monthly":{"2026-08":{"totalTokens":42}},"seen":["old"]}'
            path.write_bytes(original)
            with mock.patch.object(atomic_cache.os, "replace", side_effect=OSError("test failure")):
                with self.assertRaises(OSError):
                    atomic_cache.write_bytes(path, b'{"monthly":{},"seen":[]}')
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_cursor_copy_validates_before_replacing_prior_cache(self):
        with tempfile.TemporaryDirectory() as root:
            source = pathlib.Path(root) / "scan.json"
            cache = pathlib.Path(root) / "cursor-cache.json"
            def document(tokens):
                counts = {"inputTokens": tokens, "outputTokens": 0, "cacheReadTokens": 0,
                          "cacheCreationTokens": 0, "totalTokens": tokens}
                return json.dumps({"monthly": [{"month": "2026-08", **counts, "totalCost": 1,
                                                "models": {"model": {**counts, "cost": 1}}}],
                                   "totals": {**counts, "totalCost": 1}}).encode()
            original = document(42)
            cache.write_bytes(original)
            empty = json.dumps({"monthly": [], "totals": {"inputTokens": 0, "outputTokens": 0,
                "cacheReadTokens": 0, "cacheCreationTokens": 0, "totalTokens": 0, "totalCost": 0}}).encode()
            for invalid in (b'{"monthly":', b'{"monthly":{},"totals":{}}', b'[]',
                            b'{"monthly":[null],"totals":{}}', empty, document(41)):
                source.write_bytes(invalid)
                with self.assertRaises(ValueError):
                    atomic_cache.copy_cursor(source, cache)
                self.assertEqual(cache.read_bytes(), original)
            updated = document(43)
            source.write_bytes(updated)
            atomic_cache.copy_cursor(source, cache)
            self.assertEqual(cache.read_bytes(), updated)
            self.assertEqual(json.loads(cache.read_text())["totals"]["totalTokens"], 43)

            # A price-only month is real saved data, even with no tokens.
            price_only = document(0)
            cache.write_bytes(price_only)
            source.write_bytes(empty)
            with self.assertRaises(ValueError):
                atomic_cache.copy_cursor(source, cache)
            self.assertEqual(cache.read_bytes(), price_only)

            # Do not silently replace a corrupt history with a shorter scan.
            cache.write_bytes(b'{"monthly":')
            source.write_bytes(updated)
            with self.assertRaises(ValueError):
                atomic_cache.copy_cursor(source, cache)
            self.assertEqual(cache.read_bytes(), b'{"monthly":')

    def test_killed_writer_leaves_previous_cache_intact(self):
        with tempfile.TemporaryDirectory() as root:
            cache = pathlib.Path(root) / "grok-cache.json"
            marker = pathlib.Path(root) / "writing"
            original = b'{"monthly":{"2026-08":{"totalTokens":42}},"seen":["old"]}'
            cache.write_bytes(original)
            program = '''import pathlib,sys,time
import atomic_cache
def pause(fd):
    pathlib.Path(sys.argv[2]).write_text("ready")
    time.sleep(30)
atomic_cache.os.fsync = pause
atomic_cache.write_bytes(pathlib.Path(sys.argv[1]), b"{\\"new\\":true}")
'''
            env = {**os.environ, "PYTHONPATH": str(pathlib.Path(__file__).resolve().parent)}
            child = subprocess.Popen([sys.executable, "-c", program, str(cache), str(marker)], env=env)
            try:
                deadline = time.monotonic() + 5
                while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(marker.exists(), "writer did not reach staged write")
                child.kill()
                child.wait(timeout=5)
                self.assertEqual(cache.read_bytes(), original)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
