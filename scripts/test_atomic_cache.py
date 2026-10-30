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


class AtomicUsageCacheTests(unittest.TestCase):
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
