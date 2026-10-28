import datetime
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from publication_checkpoint import decide


class PublicationCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.repo = self.root / "collector"
        self.remote = self.root / "origin.git"
        self.now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        subprocess.run(["git", "init", "--bare", "-q", str(self.remote)], check=True)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        self.git("config", "user.name", "Publication test")
        self.git("config", "user.email", "publication@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.hooksPath", str(self.root / "no-hooks"))
        (self.repo / "data").mkdir()
        self.write(1_000_000_000, self.now)
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-q", "-u", "origin", "main")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def write(self, total, at):
        self.ledger = {"generated_at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "totals": {"totalTokens": total}}
        (self.repo / "data/tokens.json").write_text(json.dumps(self.ledger))
        self.git("add", "data/tokens.json")
        self.git("commit", "-q", "-m", "collected snapshot")

    def test_small_scans_accumulate_against_published_total(self):
        for minutes, delta in [(10, 10_000_000), (20, 20_000_000), (30, 30_000_000)]:
            at = self.now + datetime.timedelta(minutes=minutes)
            self.write(1_000_000_000 + delta, at)
            publish, reason = decide(self.repo, now=at)
            self.assertEqual(publish, delta >= 25_000_000, reason)
        self.assertIn("30000000", reason)
        published = json.loads(self.git("show", "origin/main:data/tokens.json"))
        self.assertEqual(published["totals"]["totalTokens"], 1_000_000_000)

    def test_recent_local_commits_do_not_reset_hourly_deadline(self):
        for minutes in [20, 40, 59]:
            self.write(1_000_000_000 + minutes, self.now + datetime.timedelta(minutes=minutes))
        publish, reason = decide(self.repo, now=self.now + datetime.timedelta(hours=1))
        self.assertTrue(publish, reason)
        self.assertIn("age 3600s", reason)

    def test_successful_push_resets_both_counter_and_age(self):
        at = self.now + datetime.timedelta(minutes=10)
        self.write(1_030_000_000, at)
        self.assertTrue(decide(self.repo, now=at)[0])
        self.git("push", "-q", "origin", "main")
        at += datetime.timedelta(minutes=10)
        self.write(1_031_000_000, at)
        publish, reason = decide(self.repo, now=at)
        self.assertFalse(publish, reason)
        self.assertIn("delta 1000000", reason)
        self.assertIn("age 600s", reason)

    def test_failed_or_deferred_push_remains_due_on_next_small_scan(self):
        at = self.now + datetime.timedelta(minutes=10)
        self.write(1_030_000_000, at)
        self.assertTrue(decide(self.repo, now=at)[0])
        # No push occurs. A subsequent 1M scan must still publish the 31M backlog.
        at += datetime.timedelta(minutes=1)
        self.write(1_031_000_000, at)
        self.assertTrue(decide(self.repo, now=at)[0])

    def test_backlog_can_publish_without_another_scan(self):
        at = self.now + datetime.timedelta(minutes=10)
        self.write(1_001_000_000, at)
        self.assertFalse(decide(self.repo, now=at)[0])
        self.assertTrue(decide(self.repo, now=self.now + datetime.timedelta(hours=1))[0])

    def test_no_unpublished_commits_does_not_repeat_pushes(self):
        publish, reason = decide(self.repo, now=self.now + datetime.timedelta(days=1))
        self.assertFalse(publish, reason)
        self.assertIn("no unpublished", reason)

    def test_missing_remote_checkpoint_forces_a_publication_attempt(self):
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        publish, reason = decide(self.repo, now=self.now)
        self.assertTrue(publish, reason)
        self.assertIn("no confirmed", reason)

    def test_unreadable_published_ledger_does_not_defer_forever(self):
        (self.repo / "data/tokens.json").write_text("invalid fixture")
        self.git("add", "data/tokens.json")
        self.git("commit", "-q", "-m", "unreadable published fixture")
        self.git("push", "-q", "origin", "main")
        self.write(1_000_000_001, self.now + datetime.timedelta(minutes=1))
        publish, reason = decide(self.repo, now=self.now + datetime.timedelta(minutes=1))
        self.assertTrue(publish, reason)
        self.assertIn("unreadable", reason)

    def test_cli_reports_hold_and_errors_without_mutating_git(self):
        command = [sys.executable, str(pathlib.Path(__file__).with_name("publication_checkpoint.py")),
                   "--repo", str(self.repo)]
        before = self.git("rev-parse", "HEAD")
        held = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(held.returncode, 3, held.stdout)
        invalid = subprocess.run(command + ["--threshold", "-1"], capture_output=True, text=True)
        self.assertEqual(invalid.returncode, 1, invalid.stdout)
        self.assertEqual(self.git("rev-parse", "HEAD"), before)


if __name__ == "__main__":
    unittest.main()
