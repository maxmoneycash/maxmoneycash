import datetime
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest


SCRIPTS = pathlib.Path(__file__).resolve().parent
ARTIFACTS = ["tokens.json", "cursor-cache.json", "grok-cache.json", "hermes-cache.json"]


class PublisherGitStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.repo = self.root / "collector"
        self.remote = self.root / "origin.git"
        subprocess.run(["git", "init", "--bare", "-q", str(self.remote)], check=True)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        self.git("config", "user.name", "Publisher test")
        self.git("config", "user.email", "publisher@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.hooksPath", str(self.root / "no-hooks"))
        (self.repo / "scripts").mkdir()
        for name in ["collect_tokens.sh", "publish_tokens.sh", "publication_checkpoint.py"]:
            shutil.copyfile(SCRIPTS / name, self.repo / "scripts" / name)
        (self.repo / "data").mkdir()
        for name in ARTIFACTS:
            (self.repo / "data" / name).write_text("{}\n")
        self.write_total(1_000_000_000)
        (self.repo / "README.md").write_text("original user content\n")
        self.git("add", "data", "scripts", "README.md")
        self.git("commit", "-q", "-m", "published fixture")
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-q", "-u", "origin", "main")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        sleep = self.bin / "sleep"
        sleep.write_text("#!/bin/sh\nexit 0\n")
        sleep.chmod(0o755)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def write_total(self, total):
        value = {"totals": {"totalTokens": total},
                 "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        (self.repo / "data/tokens.json").write_text(json.dumps(value))

    def run_publisher(self, *extra):
        return subprocess.run(["bash", str(self.repo / "scripts/publish_tokens.sh"),
                               str(self.repo), "--lock-held", *extra], capture_output=True, text=True,
                              timeout=45, env={**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}"})

    def test_existing_git_operations_and_locks_are_untouched(self):
        before = self.git("rev-parse", "HEAD")
        self.write_total(1_030_000_000)
        for name in ["index.lock", "rebase-merge", "rebase-apply", "MERGE_HEAD", "SQUASH_MSG",
                     "CHERRY_PICK_HEAD", "REVERT_HEAD"]:
            with self.subTest(state=name):
                path = pathlib.Path(self.git("rev-parse", "--git-path", name))
                if not path.is_absolute():
                    path = self.repo / path
                if name.startswith("rebase-"):
                    path.mkdir()
                    sentinel = path / "user-state"
                else:
                    sentinel = path
                sentinel.write_text(before + "\n")
                result = self.run_publisher()
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(f"Git state {name} exists", result.stdout)
                self.assertEqual(sentinel.read_text(), before + "\n")
                self.assertEqual(self.git("rev-parse", "HEAD"), before)
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()

    def test_unrelated_staged_work_is_neither_committed_nor_unstaged(self):
        (self.repo / "README.md").write_text("user's staged edit\n")
        self.git("add", "README.md")
        index = self.repo / ".git/index"
        before_index = hashlib.sha256(index.read_bytes()).hexdigest()
        before_head = self.git("rev-parse", "HEAD")
        self.write_total(1_030_000_000)
        result = self.run_publisher()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("unrelated staged changes", result.stdout)
        self.assertEqual(hashlib.sha256(index.read_bytes()).hexdigest(), before_index)
        self.assertEqual(self.git("rev-parse", "HEAD"), before_head)
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "README.md")
        self.assertEqual((self.repo / "README.md").read_text(), "user's staged edit\n")

    def test_collector_stops_before_scanning_or_overwriting_a_merge(self):
        head = self.git("rev-parse", "HEAD")
        state = self.repo / ".git/MERGE_HEAD"
        state.write_text(head + "\n")
        ledger = self.repo / "data/tokens.json"
        ledger.write_text("user is resolving this file\n")
        scanner = self.bin / "scanner"
        marker = self.root / "scanner-ran"
        scanner.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 1\n')
        scanner.chmod(0o755)
        lockf = self.bin / "lockf"
        lockf.write_text("#!/bin/sh\nexit 0\n")
        lockf.chmod(0o755)
        result = subprocess.run(["bash", str(self.repo / "scripts/collect_tokens.sh")],
                                capture_output=True, text=True, timeout=20,
                                env={**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}",
                                     "CCUSAGE": str(scanner), "TMPDIR": str(self.root)})
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Git state MERGE_HEAD exists", result.stdout)
        self.assertFalse(marker.exists())
        self.assertEqual(ledger.read_text(), "user is resolving this file\n")
        self.assertEqual(state.read_text(), head + "\n")

    def test_stash_conflict_without_merge_head_is_left_untouched(self):
        self.write_total(1_010_000_000)
        self.git("stash", "push", "-q", "-m", "user's ledger work")
        self.write_total(1_020_000_000)
        self.git("add", "data/tokens.json")
        self.git("commit", "-q", "-m", "main changes ledger")
        conflict = subprocess.run(["git", "-C", str(self.repo), "stash", "pop"],
                                  capture_output=True, text=True)
        self.assertEqual(conflict.returncode, 1)
        self.assertFalse((self.repo / ".git/MERGE_HEAD").exists())
        self.assertFalse((self.repo / ".git/SQUASH_MSG").exists())
        self.assertTrue(self.git("ls-files", "--unmerged"))
        before = (self.repo / "data/tokens.json").read_bytes()
        index_before = (self.repo / ".git/index").read_bytes()
        result = self.run_publisher("--check-git-idle")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("unresolved index entries", result.stdout)
        self.assertEqual((self.repo / "data/tokens.json").read_bytes(), before)
        self.assertEqual((self.repo / ".git/index").read_bytes(), index_before)

    def test_resolved_staged_squash_merge_is_left_untouched(self):
        self.git("checkout", "-q", "-b", "other")
        self.write_total(1_010_000_000)
        self.git("add", "data/tokens.json")
        self.git("commit", "-q", "-m", "other changes ledger")
        self.git("checkout", "-q", "main")
        self.write_total(1_020_000_000)
        self.git("add", "data/tokens.json")
        self.git("commit", "-q", "-m", "main changes ledger")
        conflict = subprocess.run(["git", "-C", str(self.repo), "merge", "--squash", "other"],
                                  capture_output=True, text=True)
        self.assertEqual(conflict.returncode, 1)
        self.assertFalse((self.repo / ".git/MERGE_HEAD").exists())
        self.write_total(1_035_000_000)
        self.git("add", "data/tokens.json")
        self.assertFalse(self.git("ls-files", "--unmerged"))
        self.assertTrue((self.repo / ".git/SQUASH_MSG").exists())
        before = (self.repo / "data/tokens.json").read_bytes()
        index_before = (self.repo / ".git/index").read_bytes()
        result = self.run_publisher("--check-git-idle")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Git state SQUASH_MSG exists", result.stdout)
        self.assertEqual((self.repo / "data/tokens.json").read_bytes(), before)
        self.assertEqual((self.repo / ".git/index").read_bytes(), index_before)

    def test_normal_generated_changes_publish(self):
        self.write_total(1_030_000_000)
        result = self.run_publisher()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("pushed token stats", result.stdout)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.git("rev-parse", "origin/main"))
        self.assertEqual(self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"),
                         "data/tokens.json")

    def test_rejected_push_does_not_remove_unrelated_work(self):
        hook = self.remote / "hooks/pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        (self.repo / "README.md").write_text("user's unstaged edit\n")
        self.write_total(1_030_000_000)
        result = self.run_publisher()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("failed to push after 5 attempts", result.stdout)
        self.assertEqual((self.repo / "README.md").read_text(), "user's unstaged edit\n")
        self.assertFalse((self.repo / ".git/rebase-merge").exists())
        self.assertNotEqual(self.git("rev-parse", "HEAD"), self.git("rev-parse", "origin/main"))

    def test_only_collectors_failed_rebase_is_aborted(self):
        upstream = self.root / "upstream"
        subprocess.run(["git", "clone", "-q", "--branch", "main", str(self.remote), str(upstream)], check=True)
        subprocess.run(["git", "-C", str(upstream), "config", "user.name", "Upstream fixture"], check=True)
        subprocess.run(["git", "-C", str(upstream), "config", "user.email", "upstream@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(upstream), "config", "commit.gpgsign", "false"], check=True)
        subprocess.run(["git", "-C", str(upstream), "rm", "-q", "data/cursor-cache.json"], check=True)
        subprocess.run(["git", "-C", str(upstream), "commit", "-q", "-m", "upstream removes cache"], check=True)
        subprocess.run(["git", "-C", str(upstream), "push", "-q", "origin", "main"], check=True)
        (self.repo / "data/cursor-cache.json").write_text('{"fixture": "new data"}\n')
        self.write_total(1_030_000_000)
        result = self.run_publisher()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertFalse((self.repo / ".git/rebase-merge").exists())
        self.assertFalse((self.repo / ".git/rebase-apply").exists())
        self.assertEqual((self.repo / "data/cursor-cache.json").read_text(), '{"fixture": "new data"}\n')
        self.assertEqual(json.loads(self.git("show", "HEAD:data/tokens.json"))["totals"]["totalTokens"],
                         1_030_000_000)


if __name__ == "__main__":
    unittest.main()
