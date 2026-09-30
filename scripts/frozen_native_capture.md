# Frozen native capture v1

`frozen_native_capture.py` is a pure, unwired migration module. It validates and
splits one already supplied report into provider, monthly, daily and recent
daily views. It does not open files, run a scanner, read a clock, access a
credential, change a ledger, or publish anything. No existing collector or
publication guard imports it.

## Input

```python
result = split_native_capture(
    report_bytes,                 # immutable UTF-8 bytes, supplied by caller
    receipt=receipt,
    daily_since="2026-08-29",      # optional inclusive UTC date, after validation
    side_sources=[{"sourceID": "legacy-grok", "provider": "grok"}],
)
normalized_bytes = result.encoded  # immutable canonical JSON bytes
view = result.as_dict()            # a new mutable decoded copy
```

The report schema is the `monthly`, `daily`, `totals` output of the native
multi-section command with nested `agents` in every period. The intended
declaration is `monthly --sections daily,monthly --by-agent --json --offline
--timezone UTC`, with all history supplied. Do not request `session` (which
loads sources again), or use `--since` during the all-history scan. This module
does not execute that command. Scanner options and source acquisition remain a
separate future adapter.

The exact receipt fields are:

```json
{
  "protocol": "turbotokens-multisection-v1",
  "sourceID": "native-local",
  "scannerVersion": "turbotokens 1.1.4",
  "scannerSHA256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "startedAt": "2026-09-30T01:00:00.000001Z",
  "endedAt": "2026-09-30T01:00:01.123456Z",
  "timezone": "UTC",
  "command": "monthly",
  "sections": ["daily", "monthly"],
  "allHistory": true,
  "offline": true,
  "byAgent": true,
  "processExitCode": 0
}
```

This is a **caller-declared receipt**, not an attestation of a real process or
source completeness. The module validates the declaration and its time order,
then hashes it together with the exact report SHA-256 and byte length. It never
infers a scanner version from the payload. `captureID` identifies these bytes
and this declaration; it is not an approval token or a digest of the separately
selected daily cutoff or side-source manifest. Changed raw whitespace changes
the capture identity, even when its numeric views are identical.

Provider and source identities use `[A-Za-z0-9][A-Za-z0-9_.-]{0,95}`. Every
provider within that grammar is admitted dynamically; there is no fixed-five
list or default mapping. The reserved provider `all` is permitted only on
aggregate period rows. Model names retain their exact bounded printable ASCII
text, including namespace slashes and bracketed scanner labels; they are never
normalized or assigned a price. A future format outside these declared bounds
requires a new reviewed adapter. Unsupported keys, identity labels, section
shapes, metadata or model fields reject the whole capture; nothing unfamiliar
is silently dropped.

## Validation and exact representation

All five token counters must be JSON integers from zero through `2^64-1`, the
native scanner's range. Booleans, strings, fractions and exponent-form counters
are rejected. Every counter is emitted as a decimal **string** so values above
JavaScript's exact integer limit are preserved. A future publisher must enforce
its own lower transport/storage limit; this format is not a drop-in replacement
for the existing numeric ledger schema.

Before producing any result, the module checks:

- Required sections/fields, strict UTF-8/JSON, duplicate keys (including escaped
  aliases), Gregorian UTC periods and non-future dates relative to the declared
  capture end. Duplicate periods, providers and model rows are rejected.
- Each component and grand total partitions across nested providers, daily
  rows fold to the same monthly rows, and monthly rows equal root totals.
  Provider identity sets must also fold, including represented zero providers.
- Model component allocations cannot exceed their parent components. Each
  represented model's component vector and declared model-name set fold across
  providers and across daily/monthly views, including for each individual
  provider. Growth elsewhere cannot hide a provider or model allocation loss.
- The full history passes before the inclusive `daily_since` selection is
  applied. All monthly rows, full daily rows and provider totals remain intact;
  `recentDaily` is a separate view. Missing days are never fabricated as zero.

`unclassifiedComponentTokens = totalTokens - sum(four components)` preserves
native reasoning or other tokens without assigning them to output.
`unallocatedModelTokens = totalTokens - sum(serialized model components)`
preserves the separate model allocation remainder. The two residuals overlap;
they must not be added to each other or to total tokens. A model may be known
upstream while its reasoning component is absent from the serialized model row.
The remainder describes unallocated serialized tokens, not necessarily unknown
provider model identity.

Costs are parsed using decimal arithmetic and preserved as decimal strings in
`reportedCostUsd`; zero remains represented zero. These are scanner-reported
values with **`costCoverage: "unknown"`**. Missing upstream pricing is not
serialized by this scanner, so even a zero value cannot establish free usage.
**`costConservation: "not-attested"`** is intentional: the scanner aggregates
binary floating-point costs, and this module does not validate cross-provider,
cross-model, daily/monthly or root **cost** sums. It validates token sums only.
Each original row's cost is retained even when those cost sums differ. Provider
`summedReportedCostUsd` explicitly means the exact decimal sum of its supplied
monthly serialized values; it does not overwrite a reported source cost, prove
complete pricing, represent a bill, or establish a historical rate table.

Bounds: 16 MiB input, 64 MiB normalized output, 1,200 months, 40,000 days, 256
native providers, 4,096 models per row and 100,000 model rows across the capture.
Money has at most 128 significant digits and exponent magnitude 128, is finite,
nonnegative and at most `1e18` per reported value. Capacity failures reject the
whole input with a fixed structural diagnostic; there is no truncation.

## Ownership and coverage

The side-source input accepts only opaque `sourceID` and `provider` pairs. It
does not accept token totals, paths, identities of individual work records, or
an assertion that arithmetic proves overlap. Native plus side observations of
one provider produce `unresolved-native-side-overlap`; a side-only provider
produces `unresolved-side-history`. No side amount is added or subtracted.
Every `additiveOwner` is null, `publicationAllowed` is false, and the inventory's
completeness is unknown. Even a native-only row means only that this one capture
contains that provider, not that its records are unique across machines or
complete across all sources.

Successful structural validation cannot detect a reader that internally drops
the same records from every view. Empty success stays `coverage: "unknown"`;
it cannot replace retained history as proof of no usage. File rotations,
Grok's evicted-ID cache behavior, Hermes profile identity, cloud scanner
capabilities, source failure/retention receipts and legacy baseline provenance
remain outside this module. Those require a separately reviewed acquisition and
ownership migration before any publication.

The module's purity leaves supplied bytes and last-good files untouched on both
success and failure. This is **not wired publication protection**: preservation
of real last-good bytes/timestamps remains the responsibility of the reviewed
producer guards and a future caller. The existing guards still require their
whole `16528ac` → `31e003fe` chain; they have not been changed by this module.

## Verification

Run from `scripts`:

```sh
python3 -m unittest -v test_frozen_native_capture
```

Tests use synthetic fixtures only. `fixtures/frozen-native-report-v1.json` is
the preserved 9,011-byte output of an earlier isolated synthetic turbotokens
1.1.4 test, copied from the explicitly synthetic artifact
`/private/tmp/cm-frozen-scanner-proof-xe7cj7y6/synthetic-report.json`. It contains
three synthetic providers, two months, three days and 38,863 tokens, including
109 unclassified tokens. The binary SHA-256 recorded by that earlier test is
`b0ee8d1ed7961b851b664063705f17d47a55773969b54a4b6aa002e77f825911`.
Neither the scanner nor real source readers run in this suite. Additional
fixtures cover seven providers, unknown identities, full uint64 counts,
month boundaries, allocation loss, malformed inputs, ownership ambiguity and
absence of I/O on failure or success.
