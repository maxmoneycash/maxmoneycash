# Unwired Grok owner proposal

`grok_owner_classifier.py` is a pure classifier. It does not read source paths,
discover files, modify a cache, call the scanner, change additive ownership, or
publish anything. It returns an unsigned **proposal**, never certified lifetime
totals. Both proposed and held results have `publicationAllowed=false` and
`lifetimeCertified=false`. No production caller is wired to this module.

## API

```python
result = classify_owner(legacy_cache, records, scope, continuation=None)
```

Inputs are explicit JSON-shaped objects:

An upstream decoder must reject duplicate JSON member names before constructing
these objects; this API cannot recover members that a decoder already discarded.

- `legacy_cache`: the unchanged supplied version 1/2/3 Grok cache. Admission first
  reuses the reviewed durable-cache validator. Complete legacy identity coverage
  is mandatory; old-cap or missing-call-count uncertainty holds.
- `scope`: `sourceID`, matching `legacySourceID`, `nativeSourceIDs=[sourceID]`,
  `sideSourceIDs=[sourceID]`, `captureComplete=true`,
  `legacyIdentityCoverage="complete"`, `timezone="UTC"`.
- Each record: `sourceID`, `origin` (`active` or `rotated`), `nativeModel`,
  `ownerModel`, and `record` containing `sid`, `ts`, `msg`, `ctx`, optional `src`.
  Only `shell.turn.inference_done` is admitted. `ctx` requires a canonical uint64
  `loop_index`; the four known token fields are optional uint64s. A missing
  prompt defaults to zero but its missing/present distinction is retained.
  Unknown fields, missing identity, zero-only usage or unsupported types hold.
- `nativeModel` is the caller's frozen native attribution used in its original
  key. `ownerModel` must match it or be `unknown`. This preserves a conservative
  unknown owner model when the native parser uses a future model event. Model
  statements are supplied evidence; this module does not discover/verify a model
  timeline. Old model allocations are never changed.
- Optional `continuation` is the previous proposal's continuation object. It
  contains admitted raw evidence bound to the exact canonical baseline digest
  and scope. Recompute keys and counters from that evidence on every call.

A successful result contains `baseline` (an independent exact object copy),
`baselineTotals`, separate `additionalMonthly` rows, `proposedTotals`, `newUsage`,
`retainedUsage`, event evidence and a continuation. Repeating the same inputs
with that continuation adds zero. Missing newly admitted raw files still retain
their evidence/tokens through the continuation. No continuation or baseline is
mutated. This is **not** a persistence or authenticity mechanism: the caller must
retain evidence, and unsigned caller input is not independently certified.

A held result contains only protocol/status, a fixed reason and the two false
publication/certification fields. It exposes no partial owner counters or
continuation. The caller must retain all original supplied evidence and the last
accepted history. No record is silently skipped to produce a partial candidate.

## Identity and accounting rules

- Structured identity is source, session, losslessly parsed UTC instant (up to
  nanoseconds) and loop index. Session strings containing the old delimiters,
  unknown timestamps/offsets, missing loops and unparseable old keys hold.
- Preserve both original key formats: native session/timestamp/fresh-input/
  completion/cache-read/reasoning/model and side session/timestamp/loop/prompt.
  Native-only missing-prompt records have no side key. Structured identity is a
  conservative matching device for this proposal, not a certified global ID.
- Duplicate active/rotated witnesses with the same identity, original timestamp,
  payload and attribution count once. A native key mapping to different loops
  holds. One structured identity with changed token payload holds. Equal instants
  within one source/session with different timestamp text hold regardless of
  loop index, including against continuation. Changing both timestamp text and
  loop cannot bypass native overlap checks. Missing-prompt versus explicit-zero
  aliases also hold.
- Preserve optional raw `src` as `sourceLabel` evidence; it is not an independent
  source identity. Different or missing-versus-present labels for the same
  structured event hold as `source_witness_conflict`. Two nonidentical raw
  envelopes for the same event and origin also hold, even when their normalized
  payloads match; neither witness silently replaces the other. Exact replay and
  matching active/rotated witnesses remain order independent.
- Parse every old side ID. Distinct old keys mapping to the same structured
  identity hold. Verify per-month calls and input+cache-read against the parsed
  IDs' original text month and prompt counts. This strengthens the global calls
  check without moving old periods. A baseline alias is never fresh work.
- Native identity omits loop index. If an otherwise new loop shares a retained
  legacy source/session/UTC instant, hold with `legacy_loop_overlap_unknown`:
  the old cache lacks the per-event payload needed to disprove native overlap.
  Current old-loop raw witnesses do not certify the missing historical payload,
  even if their current native keys differ. Timestamp-text aliases are included
  in this guard. The rule also applies to supplied continuation evidence.
- An exact old accepted key is covered and adds zero; preserve its existing
  counters/model allocation. The cache does not contain a historical payload for
  each ID, so a changed payload whose original record is absent cannot be
  retrospectively identified or corrected. Such baseline amounts remain
  unverified. Conflicting available witnesses always hold the proposal.
- Only absent, unambiguous structured identities become additional events.
  Completion and reasoning stay separate in their payloads; the compatibility
  additional-month output folds them into outputTokens. New months use UTC.
  Legacy month/model/counter values, zero rows and cache-only mass are untouched.
- All counter arithmetic must fit uint64. Bound combined current/continuation
  records at 100,000 and encoded input/output at 64 MiB, with bounded ASCII
  identity/model text. Capacity exhaustion holds; no truncation or eviction.
  Excessively nested JSON-shaped input returns `invalid_json_value`, including
  when the shared legacy-cache encoder reaches its recursion limit.

These are deliberately narrower admission rules than all variants accepted by
the native/side parsers. Caller scope/completeness declarations are necessary but
not proof of actual source completeness. Baseline hashing detects a changed
boundary; it does not authenticate data. No actual deployed cache or logs were
read to validate this new classifier's narrower compatibility rules.

## Measured fixture and verification

The prior pinned scanner conformance proof used installed turbotokens 1.1.4,
SHA-256 `b0ee8d1ed7961b851b664063705f17d47a55773969b54a4b6aa002e77f825911`,
and side parser `fbc61a87`. The inspected scanner source is 1.1.3, so source/binary
attestation is unavailable; runtime fixture results are limited to tested shapes.

Four distinct synthetic contributions yield the known **352-token** union:
active 125 + rotated 125 + cache-only 77 + missing-prompt native-only 25. Actual
native output for this subset is 150; actual side output is 327. Adding them
would give 477. The union follows from declared distinct fixture identities,
never aggregate subtraction. The classifier reproduces 352, preserves 77, adds
zero on replay and retains 352 when current raw records disappear.

From `scripts/`:

```sh
python3 -B -W error::ResourceWarning -m unittest -v \
  test_grok_owner_classifier test_grok_durable_replay \
  test_token_publication_guards.CollectorIsolationTests.test_required_scan_wrapper_rejects_failure_and_empty_output
```

Tests cover that union, raw rotation/replay, both collision directions, changed
payloads against continuation, timestamp aliases and submillisecond precision,
UTC/month/model preservation, unknown legacy identities, complete coverage,
scope boundaries, malformed/nonfinite/negative/overflow values and boundedness.
Separate local evidence directly bridges the frozen synthetic scanner/side output
to this actual classifier: `/tmp/cm-grok-owner-actual-conformance-proof-sep30.py`.
The earlier scanner harness/report are `/tmp/cm-grok-native-side-conformance-sep30.*`.

## Future integration boundary

After independent review and a separately reviewed ownership migration, derive
the non-Grok native partition from other agents in the **same** frozen report
and include exactly one complete durable Grok owner receipt. Retain native Grok
as comparison evidence. A held classifier result must prevent that switch.
This module cannot establish the missing real native-only amount, repair old
double counting, authenticate a legacy cache or authorize a lifetime correction.
Actual source acquisition, storage transactions, source receipts and production
wiring remain separate work.
