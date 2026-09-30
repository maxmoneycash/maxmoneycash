"""Opt-in, private aggregate diagnostics. Never a capture/ownership receipt.

Only the existing producer reads call this module. It does not discover usage,
run commands, read credentials, or change the public accounting result. All
acquisition/fallback statuses are unknown: parseable JSON does not prove either.
The build hash identifies flushed candidate JSON only, before the collector's
monotonic guard, local artifact replacement, Git commit or publication.
"""
import atexit
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid


FIELDS = ("inputTokens", "outputTokens", "cacheCreationTokens", "cacheReadTokens", "totalTokens")
PROVIDERS = ("claude", "codex", "droid", "kimi", "opencode", "cursor", "grok", "hermes")
ROLES = ("monthly.json", "daily.json", "sources.json", "baseline.json",
         *(f"agent-{p}.json" for p in PROVIDERS[:5]),
         "codex-true.json", "kimi-true.json", "grok-true.json", "cursor.json", "hermes-true.json")
STAGES = ("monthly.before-codex", "monthly.after-codex", "monthly.after-kimi",
          "monthly.after-correction-floor", "monthly.after-cursor", "monthly.after-grok",
          "monthly.after-hermes", "monthly.after-baseline", "monthly.after-final-floor",
          "providers.before-floor", "providers.after-floor", "providers.after-baseline",
          "providers.after-final-floor", "final")
MAX_BYTES = 1024 * 1024
MAX_RECORDS = 32
MAX_EVENTS = 512
MAX_ROWS = 512
RUN = re.compile(r"[0-9a-f]{32}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
MONTH = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])\Z")
FILE = re.compile(r"([0-9a-f]{32})-(merge|build)\.json\Z")


class DiagnosticError(Exception):
    pass


def vector(row):
    row = row if isinstance(row, dict) else {}
    # Bound diagnostic conversion only; the producer's original value survives.
    if any(type(row.get(k)) is int and row[k] >= 10**1024 for k in FIELDS):
        raise DiagnosticError("bounds")
    return {k: str(row[k]) if type(row.get(k)) is int and row[k] >= 0 else None
            for k in FIELDS}


def projection(value):
    """Allowlisted token coordinates, never arbitrary strings or identifiers."""
    if not isinstance(value, dict):
        return {"shape": "invalid"}
    rows = value.get("monthly")
    result = {"shape": "object", "totals": vector(value.get("totals")),
              "monthlyState": "absent" if "monthly" not in value else "array" if isinstance(rows, list) else "invalid",
              "monthly": []}
    if isinstance(rows, list):
        if len(rows) > MAX_ROWS:
            raise DiagnosticError("bounds")
        for ordinal, row in enumerate(rows):
            period = row.get("period", row.get("month")) if isinstance(row, dict) else None
            result["monthly"].append({"ordinal": ordinal,
                "period": period if isinstance(period, str) and MONTH.fullmatch(period) else None,
                "counters": vector(row)})
    agents = value.get("agents")
    if isinstance(agents, dict):
        if len(agents) > MAX_ROWS or sum(len(row.get("monthly", [])) for row in agents.values()
                if isinstance(row, dict) and isinstance(row.get("monthly"), list)) > MAX_ROWS:
            raise DiagnosticError("bounds")
        result["providers"] = [{"ordinal": i, "provider": name if name in PROVIDERS else "other",
                                "aggregate": projection({k: row[k] for k in ("totals", "monthly") if k in row})
                               if isinstance(row, dict) else {"shape": "invalid"}}
                               for i, (name, row) in enumerate(agents.items())]
    return result


def project_input(role, value):
    if role == "sources.json":
        if not isinstance(value, list):
            return {"shape": "invalid"}
        if len(value) > MAX_ROWS:
            raise DiagnosticError("bounds")
        return {"shape": "array", "sources": [{"ordinal": i, "totals": vector(row.get("totals"))
                if isinstance(row, dict) else vector(None)} for i, row in enumerate(value)]}
    return projection(value)


def _validate_private(value):
    """Reject unrecognized stored context before incorporating it into a receipt.

    This is schema/privacy validation, not authentication of a local disk file.
    """
    keys = {"version", "runId", "phase", "diagnosticStatus", "captureState", "fallbackState",
            "sourceCoverage", "scopeOwnership", "sourceHashes", "producer", "accounting", "recorder",
            "events", "kind", "role", "sourceOrdinal", "readState", "contentSHA256", "projection",
            "shape", "totals", "monthlyState", "monthly", "ordinal", "period", "counters", "providers",
            "provider", "aggregate", "sources", "stage", "errors", "mergeBinding", "candidateOutputSHA256",
            "mergeReceiptSHA256", "merge", *FIELDS}
    words = {"merge", "build", "incomplete", "recorded", "error", "unknown", "input", "output", "stage",
             "parsed", "missing", "empty", "invalid", "unreadable", "object", "array", "absent", "other",
             "matched", "mismatch", "bounds", "configuration", "storage", "context", "observation",
             "encoding", "not-requested", *ROLES, *STAGES, *PROVIDERS}
    if value is None or type(value) is bool:
        return
    if type(value) is int and 0 <= value <= MAX_BYTES:
        return
    if isinstance(value, str) and (value in words or RUN.fullmatch(value) or HASH.fullmatch(value)
                                 or MONTH.fullmatch(value) or re.fullmatch(r"0|[1-9][0-9]{0,1023}", value)):
        return
    if isinstance(value, list) and len(value) <= MAX_EVENTS:
        for item in value:
            _validate_private(item)
        return
    if isinstance(value, dict) and value.keys() <= keys:
        for item in value.values():
            _validate_private(item)
        return
    raise DiagnosticError("context")


class PrivateStore:
    """Owned private directory, no-follow files, bounded atomic receipts."""
    def __init__(self, directory):
        directory = Path(directory)
        if not directory.is_absolute():
            raise DiagnosticError("configuration")
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
        self.directory = directory
        self.fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(self.fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            os.close(self.fd)
            self.fd = None
            raise DiagnosticError("storage")

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _directory_path(self):
        # Python 3.8 on macOS lacks dir_fd/listdir(fd). Use an owned private
        # directory and verify its identity before path operations. This is not
        # authentication against a hostile process running as the same user.
        actual = os.lstat(self.directory)
        opened = os.fstat(self.fd)
        if (not stat.S_ISDIR(actual.st_mode) or (actual.st_dev, actual.st_ino) != (opened.st_dev, opened.st_ino)
                or actual.st_uid != os.getuid() or stat.S_IMODE(actual.st_mode) != 0o700):
            raise DiagnosticError("storage")
        return self.directory

    def read(self, name):
        if not FILE.fullmatch(name):
            raise DiagnosticError("context")
        fd = os.open(self._directory_path() / name, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise DiagnosticError("storage")
            if info.st_size > MAX_BYTES:
                raise DiagnosticError("bounds")
            with os.fdopen(fd, "rb", closefd=False) as f:
                raw = f.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise DiagnosticError("bounds")
            return raw
        finally:
            os.close(fd)

    def write(self, name, raw):
        if len(raw) > MAX_BYTES or not FILE.fullmatch(name):
            raise DiagnosticError("bounds")
        # Only owned regular receipts in this namespace count toward retention.
        retained = []
        directory = self._directory_path()
        for entry in os.listdir(directory):
            if FILE.fullmatch(entry):
                info = os.lstat(directory / entry)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                    raise DiagnosticError("storage")
                if entry != name:
                    retained.append((info.st_mtime_ns, entry))
        for _, entry in sorted(retained)[:max(0, len(retained) - MAX_RECORDS + 1)]:
            os.unlink(directory / entry)
        temporary = ".receipt-" + uuid.uuid4().hex
        fd = os.open(self._directory_path() / temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=False) as f:
                f.write(raw)
                f.flush()
                os.fsync(fd)
            os.replace(self._directory_path() / temporary, directory / name)
            os.fsync(self.fd)
        finally:
            os.close(fd)
            try:
                os.unlink(directory / temporary)
            except FileNotFoundError:
                pass


class Recorder:
    def __init__(self):
        self.enabled = False
        self.store = None
        self.document = None
        self.finished = False
        self.output_hash = hashlib.sha256()
        self.event_bytes = 0

    @classmethod
    def from_environment(cls, phase):
        obj = cls()
        directory = os.environ.get("TOKENSTATS_RECEIPT_DIR")
        if not directory:
            return obj
        obj.enabled = True
        run_id = os.environ.get("TOKENSTATS_RECEIPT_RUN_ID", "")
        obj.document = {"version": 1, "runId": run_id if RUN.fullmatch(run_id) else None,
                        "phase": phase, "diagnosticStatus": "incomplete", "captureState": "unknown",
                        "fallbackState": "unknown", "sourceCoverage": "unknown", "scopeOwnership": "unknown",
                        "sourceHashes": {}, "events": [], "errors": []}
        try:
            if not RUN.fullmatch(run_id) or phase not in ("merge", "build"):
                raise DiagnosticError("configuration")
            obj.store = PrivateStore(directory)
            root = Path(__file__).resolve().parent
            for role, filename in (("producer", f"{'merge_token_sources' if phase == 'merge' else 'build_tokens_json'}.py"),
                                   ("accounting", "token_accounting.py"), ("recorder", "conservation_receipt.py")):
                obj.document["sourceHashes"][role] = hashlib.sha256((root / filename).read_bytes()).hexdigest()
            if phase == "build":
                obj._load_merge()
            obj._persist()
        except Exception as error:
            obj.fail(error)
        atexit.register(obj.close)
        return obj

    def fail(self, error):
        code = str(error) if isinstance(error, DiagnosticError) else "storage"
        if code not in ("bounds", "configuration", "storage", "context", "observation", "encoding"):
            code = "observation"
        if self.document is not None and code not in self.document["errors"]:
            self.document["errors"].append(code)
            self.document["diagnosticStatus"] = "error"
            # Never log exception text, filenames, payloads or labels.
            try:
                print(f"conservation receipt unavailable: {code}", file=sys.stderr)
            except Exception:
                pass  # Diagnostic reporting must not change the public result.

    def _event(self, value):
        if not self.enabled or self.document["errors"]:
            return
        try:
            _validate_private(value)
            size = len(json.dumps(value).encode("utf-8"))
            if len(self.document["events"]) >= MAX_EVENTS or self.event_bytes + size > MAX_BYTES // 2:
                raise DiagnosticError("bounds")
            self.document["events"].append(value)
            self.event_bytes += size
        except Exception as error:
            self.fail(error if isinstance(error, DiagnosticError) else DiagnosticError("observation"))

    def load(self, path, role, source=None, empty_missing=True):
        """The enabled path parses exactly the bytes it hashes; no second read.

        TextIOWrapper preserves the original open(...).read() locale/newline
        behavior. Input errors still propagate as in the original producer.
        """
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except Exception as error:
            self._event({"kind": "input", "role": role, "sourceOrdinal": source,
                         "readState": "missing" if isinstance(error, FileNotFoundError) else "unreadable",
                         "contentSHA256": None})
            raise
        state = "invalid"
        value = None
        try:
            with io.TextIOWrapper(io.BytesIO(raw)) as f:
                text = f.read()
            if empty_missing and not text.strip():
                state = "empty"
                raise FileNotFoundError(path)
            value = json.loads(text)
            state = "parsed"
            return value
        finally:
            try:
                event = {"kind": "input", "role": role, "sourceOrdinal": source,
                         "readState": state, "contentSHA256": hashlib.sha256(raw).hexdigest()}
                if state == "parsed":
                    event["projection"] = project_input(role, value)
                self._event(event)
            except Exception as error:
                self.fail(error if isinstance(error, DiagnosticError) else DiagnosticError("observation"))

    def output(self, role, text, value):
        if not self.enabled:
            return
        try:
            self._event({"kind": "output", "role": role, "contentSHA256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                         "readState": "parsed", "projection": project_input(role, value)})
        except Exception as error:
            self.fail(error if isinstance(error, DiagnosticError) else DiagnosticError("observation"))

    def omitted(self, role):
        self._event({"kind": "input", "role": role, "sourceOrdinal": None,
                     "readState": "not-requested", "contentSHA256": None})

    def snapshot(self, stage, value):
        if not self.enabled:
            return
        try:
            self._event({"kind": "stage", "stage": stage, "projection": projection(value)})
        except Exception as error:
            self.fail(error if isinstance(error, DiagnosticError) else DiagnosticError("observation"))

    def _load_merge(self):
        try:
            raw = self.store.read(self.document["runId"] + "-merge.json")
        except FileNotFoundError:
            self.document["mergeBinding"] = "unknown"
            return
        merge = json.loads(raw)
        _validate_private(merge)
        if (merge.get("version") != 1 or merge.get("runId") != self.document["runId"]
                or merge.get("phase") != "merge" or merge.get("diagnosticStatus") != "recorded"
                or merge.get("errors") != [] or not isinstance(merge.get("events"), list)):
            raise DiagnosticError("context")
        self.document["merge"] = merge
        self.document["mergeReceiptSHA256"] = hashlib.sha256(raw).hexdigest()

    def stdout(self, stream):
        if not self.enabled:
            return stream
        recorder = self
        class HashingStream:
            def write(self, text):
                result = stream.write(text)
                try:
                    encoding = getattr(stream, "encoding", "utf-8") or "utf-8"
                    if encoding.lower().replace("_", "-") not in ("utf-8", "utf8", "ascii", "us-ascii"):
                        raise DiagnosticError("encoding")
                    recorder.output_hash.update(text.encode(encoding))
                except Exception as error:
                    recorder.fail(error if isinstance(error, DiagnosticError) else DiagnosticError("observation"))
                return result
        return HashingStream()

    def finish(self):
        if not self.enabled:
            return
        try:
            if self.document["phase"] == "build":
                self.document["candidateOutputSHA256"] = self.output_hash.hexdigest()
                merge = self.document.get("merge")
                binding = "unknown"
                if merge:
                    outputs = {e["role"]: e["contentSHA256"] for e in merge["events"] if e.get("kind") == "output"}
                    inputs = [e for e in self.document["events"] if e.get("kind") == "input" and e["role"] != "baseline.json"]
                    binding = "matched" if inputs and all(
                        (e["readState"] == "parsed" and outputs.get(e["role"]) == e["contentSHA256"])
                        or (e["readState"] == "missing" and e["role"] not in outputs)
                        for e in inputs) else "mismatch"
                self.document["mergeBinding"] = binding
            if not self.document["errors"]:
                self.document["diagnosticStatus"] = ("incomplete" if self.document.get("mergeBinding") in ("unknown", "mismatch")
                                                       else "recorded")
            self._persist()
            self.finished = True
        except Exception as error:
            self.fail(error)
            self._persist()

    def _persist(self):
        if self.store is None:
            return
        try:
            raw = json.dumps(self.document, sort_keys=True, separators=(",", ":")).encode("utf-8")
            if len(raw) > MAX_BYTES:
                self.fail(DiagnosticError("bounds"))
                self.document.pop("merge", None)
                self.document["events"] = []
                raw = json.dumps(self.document, sort_keys=True).encode("utf-8")
            self.store.write(self.document["runId"] + "-" + self.document["phase"] + ".json", raw)
        except Exception as error:
            self.fail(error)
            # A rename may have succeeded before a directory-sync failure.
            # Best effort replace any visible "recorded" marker with an error;
            # unavailable storage is also reported by the fixed stderr code.
            try:
                raw = json.dumps(self.document, sort_keys=True, separators=(",", ":")).encode("utf-8")
                self.store.write(self.document["runId"] + "-" + self.document["phase"] + ".json", raw)
            except Exception:
                pass

    def close(self):
        if self.enabled and not self.finished:
            self._persist()
        if self.store is not None:
            self.store.close()
            self.store = None
