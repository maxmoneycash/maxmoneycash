"""Synthetic-only prevention tests. Never execute a collector or raw reader.

Builder subprocesses receive temporary synthetic inputs. Shell tests execute
only extracted pure guard/copy blocks, never the collection entrypoint.
"""
import copy
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

import token_publication_guards as guards

ROOT = pathlib.Path(__file__).resolve().parent


def counts(total):
    return {**dict.fromkeys(guards.COUNTERS, 0), "inputTokens": total, "totalTokens": total}


def agent_month(period, total):
    return {"month": period, **counts(total), "totalCost": 0, "models": {}}


def source(rows):
    return {"monthly": rows, "totals": {key: sum(row[key] for row in rows) for key in guards.COUNTERS}}


def inputs(periods=("2026-08", "2026-09")):
    agents = {name: source([]) for name in guards.NATIVE_AGENTS}
    for name, total in [("claude", 10), ("codex", 100), ("kimi", 20)]:
        agents[name] = source([agent_month(period, total) for period in periods])
    unified = source([
        {"period": period, **counts(130), "totalCost": 0, "modelBreakdowns": [], "modelsUsed": [],
         "metadata": {"agents": ["claude", "codex", "kimi"]}}
        for period in periods
    ])
    return unified, agents, {name: copy.deepcopy(agents[name]) for name in ("codex", "kimi")}


def artifact(amounts=(10000,), periods=("2026-09",)):
    months = [{"period": period, **counts(total)} for period, total in zip(periods, amounts)]
    native = source([agent_month(period, total) for period, total in zip(periods, amounts)])
    return {**source(months), "generated_at": "2026-09-27T12:00:00Z",
            "daily": [],
            "agents": {"claude": native}, "sources": [{"label": "local", "totals": counts(sum(amounts))}],
            "corrections": {"accountingRevision": "synthetic-v1", "codexCumulativeAdjusted": True}}


def write_inputs(directory, bundle):
    unified, agents, corrected = bundle
    documents = {"monthly.json": unified, "daily.json": {"daily": []},
                 "sources.json": [{"label": "local", "totals": unified["totals"]}]}
    documents.update({f"agent-{name}.json": value for name, value in agents.items()})
    documents.update({f"{name}-true.json": value for name, value in corrected.items()})
    for name, value in documents.items():
        (directory / name).write_text(json.dumps(value))


class CorrectionCoverageTests(unittest.TestCase):
    def blocked(self, bundle, code):
        before = copy.deepcopy(bundle)
        with self.assertRaises(guards.PublicationBlocked) as raised:
            guards.validate_correction_coverage(*bundle)
        self.assertEqual(raised.exception.code, code)
        self.assertIn("inconsistent snapshot/coverage; retry", str(raised.exception))
        self.assertEqual(bundle, before)

    def test_complete_snapshot_passes_without_mutation(self):
        bundle = inputs()
        before = copy.deepcopy(bundle)
        reported, corrected = guards.validate_correction_coverage(*bundle)
        self.assertEqual(set(reported["codex"]), {"2026-08", "2026-09"})
        self.assertEqual(corrected["kimi"]["2026-09"]["totalTokens"], 20)
        self.assertEqual(bundle, before)

    def test_missing_true_month_cannot_silently_replace_reported_usage_with_zero(self):
        bundle = inputs()
        bundle[2]["codex"] = source(bundle[2]["codex"]["monthly"][1:])
        self.blocked(bundle, "correction_month_coverage_mismatch")

    def test_true_only_kimi_month_is_unknown_reported_coverage_not_an_addition(self):
        bundle = inputs()
        bundle[1]["kimi"] = source(bundle[1]["kimi"]["monthly"][1:])
        self.blocked(bundle, "correction_month_coverage_mismatch")

    def test_correction_month_outside_backbone_is_rejected_not_dropped(self):
        bundle = inputs()
        bundle[0].update(source(bundle[0]["monthly"][:1]))
        self.blocked(bundle, "provider_month_outside_backbone")

    def test_both_provider_operands_missing_cannot_hide_inside_backbone(self):
        bundle = inputs()
        bundle[1]["codex"] = source([])
        bundle[2]["codex"] = source([])
        self.blocked(bundle, "provider_month_coverage_mismatch")

    def test_sequential_scan_growth_is_a_retryable_partition_mismatch(self):
        bundle = inputs()
        bundle[1]["claude"] = source([agent_month("2026-08", 10), agent_month("2026-09", 11)])
        self.blocked(bundle, "backbone_partition_mismatch")

    def test_invalid_totals_duplicate_months_and_unknown_source_scope_reject(self):
        bundle = inputs(); bundle[2]["codex"]["totals"]["totalTokens"] += 1
        self.blocked(bundle, "source_totals_mismatch")
        bundle = inputs(); bundle[1]["codex"]["monthly"].append(copy.deepcopy(bundle[1]["codex"]["monthly"][0]))
        self.blocked(bundle, "duplicate_month")
        for scope in [None, [], ["claude", "codex", "kimi", "unreviewed-provider"], ["claude", "codex", "kimi", "kimi"]]:
            bundle = inputs(); bundle[0]["monthly"][0]["metadata"]["agents"] = scope
            self.blocked(bundle, "provider_month_coverage_mismatch" if scope == [] else "unproven_backbone_scope")

    def test_missing_counter_is_unknown_not_zero(self):
        bundle = inputs(); del bundle[1]["codex"]["monthly"][0]["cacheReadTokens"]
        self.blocked(bundle, "invalid_counter")
        for bad in [True, 1.5, -1, "1", 9_007_199_254_740_992]:
            bundle = inputs(); bundle[2]["kimi"]["monthly"][0]["totalTokens"] = bad
            self.blocked(bundle, "invalid_counter")

    def test_builder_reports_incomplete_corrections_before_emitting_json(self):
        for transform in [
            lambda b: b[2].update(codex=source(b[2]["codex"]["monthly"][1:])),
            lambda b: b[1].update(kimi=source(b[1]["kimi"]["monthly"][1:])),
            lambda b: b[0].update(source(b[0]["monthly"][:1])),
        ]:
            bundle = inputs(); transform(bundle)
            with tempfile.TemporaryDirectory(prefix="synthetic-token-build-") as temporary:
                directory = pathlib.Path(temporary); write_inputs(directory, bundle)
                result = subprocess.run([sys.executable, "-B", str(ROOT / "build_tokens_json.py"), str(directory)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertIn("inconsistent snapshot/coverage; retry", result.stderr)

    def test_builder_success_keeps_corrections_and_frozen_baseline_separate(self):
        bundle = inputs(("2026-09",))
        # Explicit zero is evidenced in the reported/backbone partition; it
        # differs from the omitted true-only Kimi month rejected above.
        bundle[1]["kimi"] = source([agent_month("2026-09", 0)])
        bundle[0].update(source([{**bundle[0]["monthly"][0], **counts(110)}]))
        baseline = {**source([{"period": "2026-08", **counts(7), "totalCost": 0, "modelBreakdowns": []}]), "agents": {}, "daily": []}
        with tempfile.TemporaryDirectory(prefix="synthetic-token-build-") as temporary:
            directory = pathlib.Path(temporary); write_inputs(directory, bundle)
            baseline_path = directory / "baseline.json"; baseline_path.write_text(json.dumps(baseline))
            baseline_before = baseline_path.read_bytes()
            result = subprocess.run([sys.executable, "-B", str(ROOT / "build_tokens_json.py"), str(directory), str(baseline_path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(baseline_path.read_bytes(), baseline_before)
            built = json.loads(result.stdout)
        self.assertEqual(built["totals"]["totalTokens"], 137)
        self.assertEqual([row["totalTokens"] for row in built["monthly"]], [7, 130])
        self.assertEqual(built["agents"]["kimi"]["totals"]["totalTokens"], 20)
        self.assertEqual(built["corrections"]["accountingRevision"], "turbotokens-counter-v4")


class OrdinaryPublicationTests(unittest.TestCase):
    def test_every_small_decrease_is_blocked_without_revision_or_flag_bypass(self):
        previous = artifact()
        for total in [9999, 9900, 9800, 9700]:
            candidate = artifact((total,)); candidate["corrections"]["accountingRevision"] = "new-label"
            previous["corrections"]["codexCumulativeAdjusted"] = False
            with self.assertRaisesRegex(guards.PublicationBlocked, "ordinary_decrease"):
                guards.validate_publication(previous, candidate)
        self.assertEqual(previous["totals"]["totalTokens"], 10000)

    def test_missing_or_decreasing_month_rejects_even_when_other_month_grows(self):
        previous = artifact((100, 100), ("2026-08", "2026-09"))
        for candidate in [artifact((500,), ("2026-09",)), artifact((99, 500), ("2026-08", "2026-09"))]:
            with self.assertRaises(guards.PublicationBlocked):
                guards.validate_publication(previous, candidate)

    def test_provider_loss_rejects_even_when_headline_and_months_grow(self):
        previous = artifact()
        candidate = artifact((11000,))
        candidate["agents"]["claude"] = source([agent_month("2026-09", 9999)])
        with self.assertRaisesRegex(guards.PublicationBlocked, "ordinary_decrease at agents"):
            guards.validate_publication(previous, candidate)
        del candidate["agents"]["claude"]
        with self.assertRaisesRegex(guards.PublicationBlocked, "missing_provider_coverage"):
            guards.validate_publication(previous, candidate)

    def test_source_loss_below_two_percent_cannot_be_hidden_by_local_growth(self):
        previous = artifact()
        previous["sources"] = [{"label": "local", "totals": counts(9900)}, {"label": "cloud", "totals": counts(100)}]
        candidate = artifact((11000,))
        with self.assertRaisesRegex(guards.PublicationBlocked, "missing_previous_source"):
            guards.validate_publication(previous, candidate)
        candidate["sources"].append({"label": "cloud", "totals": counts(99)})
        with self.assertRaisesRegex(guards.PublicationBlocked, "ordinary_decrease at sources"):
            guards.validate_publication(previous, candidate)

    def test_component_loss_does_not_get_rescaled_into_another_component(self):
        previous = artifact()
        candidate = artifact((11000,))
        candidate["totals"]["inputTokens"] = candidate["monthly"][0]["inputTokens"] = 9999
        candidate["totals"]["cacheReadTokens"] = candidate["monthly"][0]["cacheReadTokens"] = 1001
        with self.assertRaisesRegex(guards.PublicationBlocked, "ordinary_decrease at totals.inputTokens"):
            guards.validate_publication(previous, candidate)

    def test_initial_equal_and_growing_snapshots_pass_without_mutation(self):
        previous, candidate = artifact(), artifact((11000,))
        before = copy.deepcopy((previous, candidate))
        guards.validate_publication(None, previous)
        guards.validate_publication(previous, previous)
        guards.validate_publication(previous, candidate)
        self.assertEqual((previous, candidate), before)

    def gate(self, directory, candidate, previous):
        repo = directory / "repo"; (repo / "data").mkdir(parents=True, exist_ok=True)
        (repo / "scripts").mkdir(exist_ok=True)
        for name in ["token_publication_guards.py", "token_accounting.py"]:
            shutil.copyfile(ROOT / name, repo / "scripts" / name)
        previous_path = repo / "data" / "tokens.json"
        if previous is not None:
            previous_path.write_text(json.dumps(previous))
        staging = directory / "staging"; staging.mkdir(exist_ok=True)
        (staging / "tokens.out").write_text(json.dumps(candidate))
        script = (ROOT / "collect_tokens.sh").read_text()
        gate = script.split("# BEGIN ordinary publication gate\n", 1)[1].split("# END ordinary publication gate", 1)[0]
        result = subprocess.run(["/bin/bash", "-c", "set -euo pipefail\n" + gate], cwd=repo,
                                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "REPO_DIR": str(repo), "TMP": str(staging)}, capture_output=True, text=True)
        return result, previous_path

    def test_exact_shell_gate_preserves_last_good_bytes_and_freshness_on_two_losses(self):
        old = artifact(); old["generated_at"] = "2026-09-01T00:00:00Z"
        for total in [9900, 9801]:
            with tempfile.TemporaryDirectory(prefix="synthetic-publication-") as temporary:
                result, previous = self.gate(pathlib.Path(temporary), artifact((total,)), old)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(previous.read_bytes(), json.dumps(old).encode())
                self.assertIn("last-good ledger", result.stderr)
                self.assertNotIn("audited correction", result.stdout)

    def test_exact_shell_gate_still_atomically_publishes_valid_growth(self):
        new = artifact((11000,))
        with tempfile.TemporaryDirectory(prefix="synthetic-publication-") as temporary:
            result, previous = self.gate(pathlib.Path(temporary), new, artifact())
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(previous.read_text()), new)
            self.assertFalse((pathlib.Path(temporary) / "staging" / "tokens.out").exists())


class CollectorIsolationTests(unittest.TestCase):
    def test_ordinary_script_has_no_authoritative_reconciliation_entrypoint(self):
        script = (ROOT / "collect_tokens.sh").read_text()
        self.assertNotIn("reconcile_server.py", script)
        self.assertNotIn("RECONCILE_LOG", script)
        self.assertNotIn("audited correction: removing", script)
        self.assertNotIn("98 / 100", script)
        # A stale last-good snapshot can never trigger a pre-scan authority call
        # because ordinary collection contains no reconciliation invocation.
        self.assertNotIn("reconcile", script.split('TMP=$(mktemp -d)', 1)[0].lower())

    def test_required_scan_wrapper_rejects_failure_and_empty_output(self):
        script = (ROOT / "collect_tokens.sh").read_text()
        wrapper = script.split("collect_required() {", 1)[1].split('\n}\n', 1)[0]
        for command, succeeds in [("false", False), ("true", False), ("printf synthetic", True)]:
            with tempfile.TemporaryDirectory(prefix="synthetic-scan-guard-") as temporary:
                body = 'set -euo pipefail\nlog() { printf "%s\\n" "$*"; }\ncollect_required() {' + wrapper + '\n}\ncollect_required synthetic "$OUT" ' + command
                result = subprocess.run(["/bin/bash", "-c", body], env={**os.environ, "OUT": temporary + "/output", "SCAN_LOG": temporary + "/log"}, capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, succeeds)
                if not succeeds:
                    self.assertIn("keeping previous tokens.json", result.stdout)

    def test_turbotokens_operands_reuse_identical_frozen_bytes_and_provider_timezone(self):
        script = (ROOT / "collect_tokens.sh").read_text()
        branch = script.split('if [ "$COUNTER_IS_TURBOTOKENS" = "1" ]; then\n', 1)[1].split('\nelse\n', 1)[0]
        self.assertNotIn("$CCUSAGE", branch)
        self.assertIn('"$agent" monthly --json --offline --breakdown --timezone UTC', script)
        with tempfile.TemporaryDirectory(prefix="synthetic-frozen-operands-") as temporary:
            local = pathlib.Path(temporary)
            for name in ["codex", "kimi"]:
                (local / f"agent-{name}.json").write_bytes(b'{"synthetic": "snapshot bytes"}\n')
            result = subprocess.run(["/bin/bash", "-c", "set -euo pipefail\n" + branch], env={**os.environ, "LOCAL": str(local)}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in ["codex", "kimi"]:
                self.assertEqual((local / f"{name}-true.json").read_bytes(), (local / f"agent-{name}.json").read_bytes())


class DailyCoverageTests(unittest.TestCase):
    def coverage(self, since="2026-08-23"):
        return {"since": since, "timezone": "UTC", "basis": "scanner-request-v1"}

    def test_actual_remote_block_stops_on_each_required_stub_failure(self):
        script = (ROOT / "collect_cloud_tokens.sh").read_text()
        remote = script.split("<<'REMOTE'\n", 1)[1].split("\nREMOTE\n", 1)[0]
        # Run the actual remote shell block locally with shell functions that
        # replace every scanner. The heredoc Python is inert stdin, never run.
        stubs = '''
date() { printf 2026-08-23; }
npx() {
  case "$3" in monthly|daily) label="$3" ;; *) label="agent-$3" ;; esac
  if [ "$FAIL_SOURCE" = "$label" ]; then return 71; fi
  if [ "$label" = daily ]; then printf '{"daily":[]}'; else printf '{"monthly":[],"totals":{}}'; fi
}
python3() {
  case "$1" in */codex_true_usage.py) label=codex-true ;; */kimi_true_usage.py) label=kimi-true ;; -) label=hermes-dump ;; *) return 99 ;; esac
  if [ "$FAIL_SOURCE" = "$label" ]; then return 71; fi
  if [ "$label" = hermes-dump ]; then cat >/dev/null; printf '[]'; else printf '{"monthly":[],"totals":{}}'; fi
}
ssh() { return 99; }
scp() { return 99; }
'''
        failures = ["monthly", "daily", *(f"agent-{name}" for name in guards.NATIVE_AGENTS), "codex-true", "kimi-true", "hermes-dump"]
        for failure in [*failures, "none"]:
            with tempfile.TemporaryDirectory(prefix="synthetic-remote-block-") as temporary:
                result = subprocess.run(["/bin/bash", "-c", stubs + remote + '\nprintf completed', "synthetic", temporary],
                                        env={**os.environ, "FAIL_SOURCE": failure}, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0 if failure == "none" else 71, failure)
                self.assertEqual(result.stdout == "completed", failure == "none", failure)
                if failure == "daily":
                    self.assertEqual((pathlib.Path(temporary) / "daily.json").read_bytes(), b"")
                    self.assertFalse((pathlib.Path(temporary) / "daily-coverage.json").exists())

    def test_each_required_cloud_command_propagates_failure_instead_of_empty_json(self):
        script = (ROOT / "collect_cloud_tokens.sh").read_text()
        lines = script.splitlines()
        prefixes = ["$CCUSAGE monthly ", "$CCUSAGE daily ", '  $CCUSAGE "$agent" monthly ',
                    'python3 "$REMOTE_DIR/codex_true_usage.py" ', 'python3 "$REMOTE_DIR/kimi_true_usage.py" ']
        for prefix in prefixes:
            line = next(line for line in lines if line.startswith(prefix))
            with tempfile.TemporaryDirectory(prefix="synthetic-cloud-command-") as temporary:
                shell = 'set -euo pipefail\nsynthetic_failure() { return 71; }\npython3() { return 71; }\nCCUSAGE=synthetic_failure\nREMOTE_DIR=/synthetic\nDAILY_SINCE=2026-08-23\nagent=claude\n' + line
                result = subprocess.run(["/bin/bash", "-c", shell], cwd=temporary, capture_output=True, text=True)
                self.assertEqual(result.returncode, 71, prefix)
                for output in pathlib.Path(temporary).glob("*.json"):
                    self.assertEqual(output.read_bytes(), b"")
        # Exercise only the real dump command line with a synthetic process
        # and synthetic stdin; no Python dump or sqlite reader runs.
        line = next(line for line in lines if line.startswith("python3 - > hermes-sessions.json"))
        with tempfile.TemporaryDirectory(prefix="synthetic-cloud-dump-") as temporary:
            shell = "set -euo pipefail\npython3() { return 72; }\n" + line + "\nsynthetic stdin\nPYEOF\n"
            result = subprocess.run(["/bin/bash", "-c", shell], cwd=temporary, capture_output=True, text=True)
            self.assertEqual(result.returncode, 72)
            self.assertEqual((pathlib.Path(temporary) / "hermes-sessions.json").read_bytes(), b"")
        self.assertNotIn("except Exception:\n        pass", script)

    def test_input_and_builder_reject_missing_malformed_or_duplicate_daily_rows(self):
        for daily in [None, {}, {"daily": None}, {"daily": [{"period": "2026-02-30", **counts(1)}]},
                      {"daily": [{"period": "2026-09-01", **counts(1)}, {"period": "2026-09-01", **counts(1)}]},
                      {"daily": [{"period": "2026-09-01", "totalTokens": 1}]}]:
            with tempfile.TemporaryDirectory(prefix="synthetic-daily-input-") as temporary:
                directory = pathlib.Path(temporary); write_inputs(directory, inputs())
                (directory / "daily.json").write_text(json.dumps(daily))
                with self.assertRaises(guards.PublicationBlocked):
                    guards.validate_input_directory(directory)
                built = subprocess.run([sys.executable, "-B", str(ROOT / "build_tokens_json.py"), str(directory)], capture_output=True, text=True)
                self.assertNotEqual(built.returncode, 0)
                self.assertEqual(built.stdout, "")
        guards.validate_daily({"daily": []})

    def test_actual_builder_empty_daily_cannot_pass_final_gate_over_previous_evidence(self):
        with tempfile.TemporaryDirectory(prefix="synthetic-daily-build-") as temporary:
            directory = pathlib.Path(temporary); write_inputs(directory, inputs())
            built = subprocess.run([sys.executable, "-B", str(ROOT / "build_tokens_json.py"), str(directory)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            candidate = json.loads(built.stdout)
            previous = copy.deepcopy(candidate)
            previous["generated_at"] = "2026-09-01T00:00:00Z"
            previous["daily"] = [{"period": "2026-09-01", **counts(100)}]
            with tempfile.TemporaryDirectory(prefix="synthetic-daily-publication-") as target:
                gate, published = OrdinaryPublicationTests().gate(pathlib.Path(target), candidate, previous)
                self.assertNotEqual(gate.returncode, 0)
                self.assertIn("missing_previous_day", gate.stderr)
                self.assertEqual(published.read_bytes(), json.dumps(previous).encode())

    def test_daily_loss_cannot_be_hidden_by_monthly_or_other_day_growth(self):
        previous = artifact(); previous["daily"] = [{"period": "2026-09-01", **counts(100)}]
        for daily in [[], [{"period": "2026-09-01", **counts(99)}, {"period": "2026-09-27", **counts(1000)}]]:
            candidate = artifact((11000,)); candidate["daily"] = daily
            candidate["dailyCoverage"] = self.coverage()
            with self.assertRaises(guards.PublicationBlocked):
                guards.validate_publication(previous, candidate)

    def test_rolloff_requires_explicit_window_and_preserves_its_inclusive_boundary(self):
        previous = artifact(); previous["daily"] = [{"period": "2026-08-22", **counts(100)}]
        candidate = artifact((11000,))
        with self.assertRaisesRegex(guards.PublicationBlocked, "missing_previous_day"):
            guards.validate_publication(previous, candidate)
        candidate["dailyCoverage"] = self.coverage()
        guards.validate_publication(previous, candidate)
        previous["daily"][0]["period"] = "2026-08-23"
        with self.assertRaisesRegex(guards.PublicationBlocked, "missing_previous_day"):
            guards.validate_publication(previous, candidate)
        candidate["daily"] = copy.deepcopy(previous["daily"])
        guards.validate_publication(previous, candidate)
        # A declared cutoff cannot shorten the existing 35-day scanner scope.
        candidate["dailyCoverage"] = self.coverage("2026-09-01")
        with self.assertRaisesRegex(guards.PublicationBlocked, "unproven_daily_window"):
            guards.validate_publication(previous, candidate)

    def test_only_matching_explicit_source_windows_reach_the_builder(self):
        receipt = self.coverage()
        self.assertEqual(guards.matching_daily_coverage([receipt, receipt]), receipt)
        with self.assertRaisesRegex(guards.PublicationBlocked, "daily_window_mismatch"):
            guards.matching_daily_coverage([receipt, self.coverage("2026-08-24")])
        for bad in [{}, {**receipt, "timezone": "local"}, {**receipt, "since": "2026-02-30"}, {**receipt, "basis": "guessed"}]:
            with self.assertRaises(guards.PublicationBlocked):
                guards.validate_daily_coverage(bad)
        with tempfile.TemporaryDirectory(prefix="synthetic-daily-coverage-") as temporary:
            directory = pathlib.Path(temporary); write_inputs(directory, inputs())
            (directory / "daily-coverage.json").write_text(json.dumps(receipt))
            built = subprocess.run([sys.executable, "-B", str(ROOT / "build_tokens_json.py"), str(directory)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            self.assertEqual(json.loads(built.stdout)["dailyCoverage"], receipt)

    def test_cloud_successful_empty_daily_keeps_explicit_request_receipt(self):
        script = (ROOT / "collect_cloud_tokens.sh").read_text()
        block = script.split("DAILY_SINCE=$(", 1)[1].split("\nfor agent", 1)[0]
        block = "DAILY_SINCE=$(" + block
        with tempfile.TemporaryDirectory(prefix="synthetic-daily-success-") as temporary:
            shell = 'set -euo pipefail\ndate() { printf 2026-08-23; }\nsynthetic_success() { printf \'{"daily":[]}\'; }\nCCUSAGE=synthetic_success\n' + block
            result = subprocess.run(["/bin/bash", "-c", shell], cwd=temporary, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((pathlib.Path(temporary) / "daily.json").read_text()), {"daily": []})
            self.assertEqual(json.loads((pathlib.Path(temporary) / "daily-coverage.json").read_text()), self.coverage())


if __name__ == "__main__":
    unittest.main()
