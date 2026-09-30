# Durable Grok identity retention

This change prevents replay caused by the side collector's 100,000-ID eviction.
It does not choose native/side additive ownership, repair historical inflation,
change the event key, or certify unique work across sources/installations.

## Reproduced failure

The previous script reads `logs/*.jsonl*`, including retained rotated files, but
keeps only the last 100,000 accepted IDs. With 100,001 synthetic inferences plus
77 previously cached tokens whose raw event is gone, the first run reports
100,078 tokens; the identical second run reports 100,079. One still-readable ID
was evicted and accepted again. File age, file rotation or calendar boundaries
cannot prove that an evicted inference will not reappear.

## Version 3 behavior

- Retain every accepted event ID alongside its accumulated monthly counters.
  Event identity remains `session|timestamp|loop_index|prompt_tokens`; provider
  field mapping and model-timeline behavior remain unchanged.
- Bound storage at **1,000,000 IDs**, **64 MiB encoded cache** and **512 UTF-8
  bytes per ID**. These are resource limits, never eviction windows. At capacity,
  replay of existing IDs is still allowed; a new ID or oversized candidate holds
  collection before any cache replacement. No hidden probabilistic filter,
  digest collision assumption, timestamp cutoff or approximate dedup is used.
- Retain cache-only monthly/model amounts and their IDs even after logs vanish.
  Once saved in canonical version 3 format, a no-op replay retains the cache's
  exact bytes and mtime.
- Save the full counters/ID state together using a private temporary file,
  flush/fsync and atomic replacement. A stable advisory lock serializes new
  direct callers as well as normal collector runs. Old writers do not honor
  this new lock; release must quiesce old writers before adopting version 3.
- Missing cache is a fresh start. Unreadable, malformed, duplicate-key,
  inconsistent or unsupported cache data is an error, never a fresh empty cache.
  Errors exit nonzero with a fixed reason code and no partial JSON output;
  the reviewed producer's required-source gate then retains publication.

A collection can still fail for malformed source data or IO. Existing raw-reader
coverage limitations are not repaired here. Resource ceilings bound identity
storage; input file/line size and source-completeness hardening are separate work.

## Conservative legacy migration

The old version 1/version 2 writers appended one unique ID for each increment of
`calls`, then truncated only when the list exceeded 100,000. Once truncated, the
list stayed at that cap on every later successful update. Thus migration is
allowed only when:

1. the retained list is **strictly below** the old cap;
2. every retained ID is valid and unique;
3. each month has a nonnegative integer call count and valid component totals,
   and the total calls exactly equals the number of retained IDs;
4. version 2 model allocations conserve their monthly components/totals.

This uses the old writer's retention invariant, not aggregate token arithmetic
to guess which unseen event was counted. It assumes the cache was produced by
that writer; it is not an authenticity claim about externally edited data.
Version 1 model attribution follows the existing migration, preserving totals
and leaving rotated records under unknown. Version 2 model rows are preserved.

At exactly 100,000 legacy IDs, even a potentially complete cache is held
conservatively. Above-cap, mismatching/missing call counts or malformed legacy
shapes are also held **without source reads, changed cache bytes or timestamp**.
A historical one-time decision to discard malformed June data cannot justify
repeating that deletion on future malformed files.

## Unresolved old eviction

If identities have already been evicted, existing aggregates and a current set
of retained logs cannot distinguish a new event from an already-counted event.
Neither unioning current IDs into the cache nor subtracting current native totals
repairs that ambiguity. This patch preserves the existing total and stops new
unproven additions; it does not guess a migration or subtract past duplicates.

A future migration needs a separately reviewed identity-backed baseline plus an
explicit source boundary. If complete historical identity cannot be recovered,
keep the old aggregate as unverified nonadditive evidence; do not silently label
newly seen historical files as fresh work. At the new resource cap, a future
exact store may expand capacity or move to transactional storage, but must
preserve all existing identities and totals atomically. There is no automatic
pruning or capacity override flag in this patch.

## Focused verification

From `scripts/`:

```sh
python3 -B -W error::ResourceWarning -m unittest -v \
  test_grok_durable_replay \
  test_token_publication_guards.CollectorIsolationTests.test_required_scan_wrapper_rejects_failure_and_empty_output
```

All source/cache records are synthetic temporary fixtures. The parser regression
uses more than 100,000 actual JSONL records, a retained rotated filename, an exact
second replay, cache-only history, and one newly appended inference. Other cases
cover duplicate active/rotated records, complete legacy migration, conservative
legacy hold, capacity, failed serialization/atomic replace, concurrent writer lock and CLI
nonzero/privacy behavior. No scanner, real home, cloud command, provider, live
ledger, cache, publisher or account is touched.
