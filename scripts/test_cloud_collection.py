import os
import importlib.util
import json
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock

SCRIPTS = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('hermes_cache_for_test', SCRIPTS / 'hermes_true_usage.py')
HERMES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HERMES)


class CloudCollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.scripts = self.root / 'scripts'
        self.scripts.mkdir()
        self.out = self.root / 'output'
        self.log = self.root / 'cloud.log'
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.trace = self.root / 'trace'
        for name in ('run_cloud_collection.sh', 'collect_cloud_tokens.sh'):
            shutil.copyfile(SCRIPTS / name, self.scripts / name)
        self.env = {**os.environ, 'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
                    'CLOUD_TEST_TRACE': str(self.trace)}

    def run_runner(self, seconds='1', env=None):
        return subprocess.run(['/bin/bash', str(self.scripts / 'run_cloud_collection.sh'),
                               str(self.out), str(self.log), seconds], env=env or self.env,
                              capture_output=True, text=True, timeout=8)

    def command(self, name, content):
        path = self.bin / name
        path.write_text('#!/bin/bash\n' + content + '\n')
        path.chmod(0o755)

    def test_timeout_keeps_diagnostics_and_returns_within_deadline(self):
        (self.scripts / 'collect_cloud_tokens.sh').write_text(
            '#!/bin/bash\necho "remote started"\necho "reason" >&2\nexec sleep 30\n')
        started = time.monotonic()
        result = self.run_runner()
        self.assertEqual(result.returncode, 124)
        self.assertLess(time.monotonic() - started, 6)
        self.assertIn('remote started', self.log.read_text())
        self.assertIn('reason', self.log.read_text())
        self.assertIn('timed out after 1s', self.log.read_text())

    def test_failed_and_successful_attempts_replace_the_previous_log(self):
        script = self.scripts / 'collect_cloud_tokens.sh'
        script.write_text('#!/bin/bash\necho "connection refused" >&2\nexit 23\n')
        result = self.run_runner()
        self.assertEqual(result.returncode, 23)
        self.assertIn('connection refused', self.log.read_text())
        self.assertIn('status 23', self.log.read_text())
        script.write_text('#!/bin/bash\necho "collection complete"\n')
        result = self.run_runner()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.log.read_text().strip(), 'collection complete')

    def test_ignoring_termination_still_has_a_hard_deadline(self):
        (self.scripts / 'collect_cloud_tokens.sh').write_text(
            '#!/bin/bash\ntrap "" TERM\necho "stubborn remote"\nwhile :; do /bin/sleep 1; done\n')
        started = time.monotonic()
        result = self.run_runner()
        self.assertEqual(result.returncode, 137)
        self.assertLess(time.monotonic() - started, 8)
        self.assertIn('stubborn remote', self.log.read_text())
        self.assertIn('was killed', self.log.read_text())

    def test_without_timeout_command_cloud_scan_is_not_started(self):
        script = self.scripts / 'collect_cloud_tokens.sh'
        script.write_text('#!/bin/bash\ntouch "$CLOUD_TEST_TRACE"\n')
        (self.bin / 'dirname').symlink_to(shutil.which('dirname'))
        env = {**self.env, 'PATH': str(self.bin)}
        result = self.run_runner(env=env)
        self.assertEqual(result.returncode, 127)
        self.assertIn('no timeout command', self.log.read_text())
        self.assertFalse(self.trace.exists())

    def test_connection_failure_records_ssh_error_and_noninteractive_options(self):
        self.command('ssh', 'printf "%s\\n" "$@" > "$CLOUD_TEST_TRACE"\necho "connection refused" >&2\nexit 255')
        result = self.run_runner(seconds='5')
        self.assertEqual(result.returncode, 1)
        self.assertIn('connection refused', self.log.read_text())
        args = self.trace.read_text().splitlines()
        for expected in ('BatchMode=yes', 'ConnectTimeout=10', 'ServerAliveInterval=15', 'ServerAliveCountMax=3', 'agent-host'):
            self.assertIn(expected, args)

    def test_script_transfer_has_same_noninteractive_options(self):
        self.command('ssh', 'exit 0')
        self.command('scp', 'printf "%s\\n" "$@" > "$CLOUD_TEST_TRACE"\necho "transfer failed" >&2\nexit 255')
        result = self.run_runner(seconds='5')
        self.assertEqual(result.returncode, 1)
        self.assertIn('transfer failed', self.log.read_text())
        args = self.trace.read_text().splitlines()
        for expected in ('BatchMode=yes', 'ConnectTimeout=10', 'ServerAliveInterval=15', 'ServerAliveCountMax=3'):
            self.assertIn(expected, args)


class HermesAtomicCacheTests(unittest.TestCase):
    def test_replace_failure_keeps_old_cache_and_cleans_staging_file(self):
        with tempfile.TemporaryDirectory() as root:
            cache = pathlib.Path(root) / 'hermes-cache.json'
            original = '{"sessions":{"old":{"input_tokens":10}}}'
            cache.write_text(original)
            with mock.patch.object(HERMES, 'CACHE', cache), mock.patch.object(HERMES.os, 'replace', side_effect=OSError('fixture failure')):
                with self.assertRaises(OSError):
                    HERMES.save_cache({'sessions': {'new': {'input_tokens': 20}}})
            self.assertEqual(cache.read_text(), original)
            self.assertEqual(list(pathlib.Path(root).iterdir()), [cache])

    def test_killed_partial_write_leaves_previous_cache_intact(self):
        with tempfile.TemporaryDirectory() as root:
            cache = pathlib.Path(root) / 'hermes-cache.json'
            marker = pathlib.Path(root) / 'writing'
            original = '{"sessions":{"old":{"input_tokens":10}}}'
            cache.write_text(original)
            program = '''import importlib.util,pathlib,sys,time
spec=importlib.util.spec_from_file_location("h",sys.argv[1]); h=importlib.util.module_from_spec(spec); spec.loader.exec_module(h)
h.CACHE=pathlib.Path(sys.argv[2])
def partial(data,out,**kwargs):
    out.write('{"sessions":'); out.flush(); pathlib.Path(sys.argv[3]).write_text('ready'); time.sleep(30)
h.json.dump=partial
h.save_cache({"sessions":{}})
'''
            child = subprocess.Popen([os.sys.executable, '-c', program, str(SCRIPTS / 'hermes_true_usage.py'), str(cache), str(marker)])
            try:
                deadline = time.monotonic() + 5
                while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(marker.exists(), 'fixture did not begin writing')
                child.kill()
                child.wait(timeout=5)
                self.assertEqual(cache.read_text(), original)
                self.assertEqual(json.loads(cache.read_text())['sessions']['old']['input_tokens'], 10)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
