# Checkpointed run lifecycle

T04 provides the durable coordinator behind `matchvet run`, `matchvet status`, and
`matchvet resume`. It does not acquire fixtures or evidence, construct Matchweek membership,
evaluate preferences, run models, or publish a Matchweek Report. Every T04 run stays
`RESEARCH_ONLY` and exposes `NO_DECISION`.

An explicit run date is the Friday Matchweek boundary in Africa/Lagos. Human `run` and `resume`
output appends preflight and checkpoint progress lines; JSON output returns one schema-versioned
final object. No-argument invocation remains read-only and prioritizes an incomplete run's exact
resume command.

## Run and work-unit state

A run is `INCOMPLETE` until one safe checkpoint exists for each configured phase and its
operational completion artifact is referenced in the same SQLite transaction that changes the
run to `COMPLETE`. The seven phase names follow the product CLI contract. At T04 they are
operational coordinator boundaries that later tickets fill with bounded work; the completion
publication is explicitly not a Matchweek Report or Matchweek Audit.

Each work unit records its stable key, phase, mode, exact input digest, attempt count, latest
attempt state, elapsed execution time, checkpoint time, output digest, and referenced artifact
digests. Attempts preserve `RUNNING`, `COMPLETED`, `INTERRUPTED`, and `FAILED` history. Safe
checkpoints and completion publications are immutable.

## Inputs and resume

The run input contract records separate SHA-256 values for source input, cutoff, Preference Set,
Selection Policy, model, feature rules, research rules, canonical contract, schema, environment,
software, artifacts, and predecessor inputs. A work-unit digest also includes its stable key and
the prior checkpoint output digest.

Resume verifies the full contract, every required immutable artifact, every completed checkpoint
input, every checkpoint artifact, and the predecessor chain. Any difference refuses reuse and
leaves the prior run `INCOMPLETE`. `matchvet run` never silently reuses a compatible unfinished
run; it returns the exact `matchvet resume RUN_ID` command.

The T04 CLI uses explicit `UNCONFIGURED` identities for components owned by later tickets. This
makes their absence part of the digest instead of inventing fixture, evidence, model, or policy
data. Those tickets must replace the identities when they supply real inputs, which will prevent
old T04-only checkpoints from being reused.

## Resource policy

Preflight applies the settled normal Matchweek budgets:

- 1.5 GiB managed storage and a 3 GiB post-growth free-space floor
- 1 GiB target memory, 1.5 GiB absolute process memory, and 1.5 GiB available-memory start floor
- two-hour target and four-hour hard limit per foreground execution
- at most two CPU-heavy operations while reserving one available CPU for Android
- one CPU-heavy operation under memory or thermal pressure
- 250 MiB routine network limit

The budget contract also retains the explicit 2 GiB historical-transfer ceiling for later
historical operations. T04 does not implement those transfers.

The foreground coordinator arms a wall-clock watchdog with the remaining four-hour allowance
around each work unit. A watchdog stop records the attempt as failed without advancing its safe
checkpoint.

The coordinator holds the existing private-store writer lock for its foreground execution.
Readers can use `matchvet status` without taking that writer lock. A `RUNNING` attempt stores the
process ID plus Linux process-start token. Status labels an attempt stale only when that exact
process identity no longer exists. The next writer safely records it as `INTERRUPTED` before
resuming and discards private `.partial` artifact staging files left by the interrupted writer.

## Failure output

Run failures return nonzero and print `INCOMPLETE` or `REFUSED`, a stable `MV-AREA-CONDITION`
code, explanation, last checkpoint and UTC time, reuse state, and one exact recovery command. A
failed work unit or four-hour stop does not advance its checkpoint. Incomplete state has no
completed report location and cannot expose PLAY or AVOID MATCH.
