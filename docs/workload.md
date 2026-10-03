# Does one delayed device hold up unrelated work?

I compare one recovery worker with four because blocking network calls can delay
other queued operations even when their devices are healthy. More workers can
reduce that delay, but they also introduce competing claims and stale results.
The experiment checks both the timing question and the ownership rules needed
to make concurrent recovery safe.

**[Inspect every measured pair](https://b8z.github.io/device-recovery-lab/#workload)**
· [Raw observations](../measurements/concurrency.json)
· [Acceptance contract](workload-contract.md)
· [Reproduction script](../scripts/workload.py)

## What runs

```text
Durable queue → 1 or 4 recovery workers → independent HTTP fault proxy → controller
      ↑                  ↓                         ↓                       ↓
 ownership + events   journal queries          fault log             execution journal
      └──────────────────── independent experiment observer ────────────────┘
```

These are three actual processes on one machine. Each batch has 24 operations
for independent synthetic lockers served by one controller. The proxy introduces
faults without asking the service or controller to select a fault scenario.
The service can query `/commands`; the proxy does not expose the controller's
diagnostic `/lab` endpoints.

The clean workload has no injected network faults. The mixed workload has four
operations in each profile: unaffected, first request delayed by 300 ms, first
request dropped before forwarding, receipt dropped after forwarding, first
command delivered twice, and first completed-journal response dropped. A seeded
shuffle changes their order. Paired worker configurations receive identical
operation IDs, order, and fault assignments.

## What concurrent ownership guarantees

Each claim is a conditional SQLite update with an owner token, expiry, and
incremented epoch. The epoch prevents a stale queue snapshot from claiming an
operation after another worker has processed and released it. Updates and event
writes check the current unexpired owner in the same transaction. Releasing an
old claim cannot clear a successor's claim.

If the service process dies, its lease expires. A new worker then queries the
controller before considering a resend. The process test kills the service while
a proxy holds the receipt response, starts another service against the same
journal, and checks that recovery does not produce another pulse.

**This fences service-journal writes, not physical effects.** A paused worker
could still deliver a network request after losing ownership. The immutable
command ID and the controller's durable duplicate suppression remain necessary.
This is single-host coordination, not multi-host consensus or a distributed lock.
The controller crash boundary still requires inspection when execution evidence
is incomplete.

## Correctness before timing

For each accepted completion, the observer requires one pulse, one physical-action
event, one service-completion event, and a controller completion report before
the service claims success. It also checks that each assigned fault occurred;
the duplicate profile must include suppression evidence. Timeouts, attention
states, invariant violations, unexercised faults, and process errors are retained
as failures, rather than removed from the result.

During review, a deliberately broken worker exposed a weakness in the original
oracle: it sent a command and declared success without querying completion, yet
the weaker checks accepted it because the device had eventually acted. I added
the completion-report requirement and retained that broken implementation as a
[negative test fixture](../tests/fixtures/no_evidence_service.py). The acceptance
test must reject all six of its fabricated completions. A green final state is
not enough evidence.

The ownership, service-kill, and negative-oracle checks are in
[the tests](../tests/test_external_faults.py) and
[ownership checks](../tests/test_ownership.py). They test correctness;
they do not assert a performance threshold.

## Recorded observations — October 3, 2026

Tested clean source: `80215b81d2ae2ab61b67a8eb289692c09ead875b`.
Python 3.12.14, SQLite 3.53.1, Windows 11 build 26200, 32 logical CPUs,
AMD64 Family 25 Model 33 Stepping 0. Runtime dependencies: Python standard library.
The raw file retains the environment and an ISO timestamp with its UTC offset.

All **864 measured operations** across **36 batches** completed and passed the
recorded invariants. Two separate warmup batches contained another 48 operations;
their observations are retained but excluded from these summaries.

Times below are seconds, shown as **median [minimum, maximum]** across nine
batches per row. The unaffected column first takes the median of unaffected
operations within each batch, then summarizes those nine medians. It is not a
pooled per-operation percentile.

| Workload | Workers | Entire batch complete | Unaffected operations |
| --- | ---: | ---: | ---: |
| Clean | 1 | 3.804 [3.521, 4.135] | 2.957 [2.499, 3.096] |
| Clean | 4 | 1.648 [1.611, 2.021] | 1.268 [1.227, 1.629] |
| Mixed faults | 1 | 5.916 [5.579, 6.152] | 4.727 [3.779, 5.017] |
| Mixed faults | 4 | 2.775 [2.560, 8.009] | 1.853 [1.377, 6.897] |

Four workers reduced the median delay in this finite workload. However, the
slowest four-worker mixed batch (seed 7, displayed repetition 3; raw index 2) took 8.009 seconds against
5.857 seconds for its one-worker pair. Four workers finished faster in nine of
nine clean pairs and eight of nine mixed pairs. I retain the exception rather
than claiming a consistent speedup. The data
shows completion and ownership events, but it does not isolate the cause of
that timing variation. Host scheduling, storage contention, and observation
overhead are possible explanations, not measured conclusions.

## Measurement method

1. I use seeds 7, 23, and 99, with three timing repetitions per seed, workload,
   and worker count. There are three independent mixed-fault assignments;
   repeated timings are not nine independent fault configurations.
2. Each trial starts fresh controller and proxy processes and new databases.
   I stage the same queue before starting the service. All 24 entries become
   eligible at one common timestamp two seconds later. Startup must finish
   before eligibility, otherwise the attempted trial is classified as a process
   error. Admission and startup are outside the timed interval.
3. One preliminary mixed batch at seed 0 per worker count serves as warmup.
   Every measured batch still starts fresh processes. This is not a steady-state
   or warm-cache throughput benchmark.
4. Timing is the service's durable completion-event wall time minus queue
   eligibility. Batch completion is the last completion in that batch. It
   includes queue waiting, recovery polling, intentional faults, and journal I/O;
   it is not client end-to-end latency. The observer checks the service database
   every 20 ms and imposes a 40-second deadline.
5. Device action delay is 350 ms, retry interval 600 ms, and lease duration five
   seconds. Worker order alternates by seed index plus repetition. Each pair
   runs sequentially; clean workloads precede mixed workloads.
6. I retain every attempted trial, including failure classifications and the
   safe exception type for process failures. Failed batches contribute no
   successful timing sample. No measured operations failed in this run.

The machine was not isolated from all other activity. The observer adds database
reads, SQLite serializes writes, and Windows scheduling affects these small
durations. Wall-clock adjustments are unmodeled. Twenty-four independent lockers
behind one simulated controller do not establish fleet capacity, production
latency, hardware safety, or behavior under sustained admission.

## Reproduce

From a clean checkout with Python 3.11+:

```sh
python -m unittest -v
python scripts/workload.py --check
python scripts/workload.py --output .verify/my-workload.json
```

The first two commands are correctness checks. `--check` runs two mixed batches
without writing a performance artifact and permits a dirty working tree. The
last command requires a clean checkout, records its actual source revision, and
runs the full measurement; allow several minutes. To reproduce this recorded
source specifically, use a separate checkout at the commit above. Later source
revisions produce new results, not a replacement for the retained observations.

`python scripts/build_workload_view.py` derives the compact browser data from the
committed raw file. It records its SHA-256 with LF line endings (the Git source
blob; Windows working copies can use CRLF), preserves all 36 measured
batches, and excludes only the explicitly labeled warmups. The browser displays
those observations; it does not generate timings or execute the backend.
