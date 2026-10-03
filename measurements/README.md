# Recovery observations

Question: **Do duplicates and missing responses multiply actuator pulses, and
what recovery work is visible compared with healthy delivery?**

## Recorded run — October 3, 2026

[Raw JSON](2026-10-03-windows.json) · tested commit
[`bed2e3f`](https://github.com/B8Z/device-recovery-lab/commit/bed2e3fe2487ef88596873b1fb57964033cc3d0a).
Windows 11 (10.0.26200), AMD64, 32 logical CPUs, Python 3.12.14, SQLite 3.53.1.
The exact processor description and every setting are in the JSON. Runtime had
no third-party packages, in a fresh virtual environment and clean checkout.

All 32 measured trials completed with one actuator pulse each. Four additional
warmup trials also completed and are retained in the file but excluded below.

| Scenario | Completed / measured | Sends per trial | Journal queries per trial | Pulses per trial | Median observation time | Min–max | Sample SD |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Healthy | 8 / 8 | 1 | 1 | 1 | 0.776 s | 0.724–0.815 s | 0.038 s |
| Duplicate | 8 / 8 | 2 | 1 | 1 | 0.773 s | 0.695–0.800 s | 0.037 s |
| Lost acknowledgment | 8 / 8 | 1 | 2 | 1 | 1.436 s | 1.398–1.466 s | 0.023 s |
| Disconnected, then restored | 8 / 8 | 2 | 3 | 1 | 2.736 s | 2.669–2.844 s | 0.059 s |

The useful observation is the extra recovery work: duplicate delivery did not
add a pulse, and lost acknowledgment added a journal query without another
command send. Reconnection required confirmation of an absent journal entry
before redispatch. `Sends` counts transport attempts, including the blocked
offline attempt. Tiny timing differences between healthy and duplicate cases
are within this sample's variability, not evidence of a faster implementation.

## Reproduce

Run the correctness checks first. Then start `python run.py` from a clean committed
checkout, with a fresh data directory and no other visitors. In another terminal:

```sh
python scripts/measure.py --output measurements/run.json
```

The script uses the standard demo configuration and one operation at a time.
It excludes process startup, warms each scenario once, then records eight
repetitions per scenario in round-robin order. The disconnected case restores
the link at the first observation at or after 0.75 seconds. Other faults are
deterministic. UUIDs are identifiers, not randomized workload parameters; there
is no random seed. All cases use the same workers, storage and poll settings.

Timing starts immediately before the client POST and ends at the first GET that
observes a terminal service state. It includes HTTP, SQLite, operating-system
scheduling, the synthetic action delay, recovery backoff and observer polling.
Reported timing summaries exclude warmups and failed trials; every trial,
including failures, remains in the raw file. Sample size and completion count
are reported together. Median, range and sample standard deviation describe
this small local sample; no tail-latency or capacity claim is made.

Classifications are `completed`, `needs_attention`, `timeout` (20 seconds), or
`invariant_violation` (terminal success with an unexpected pulse/send count or
missing required evidence). Transport/script failures abort rather than fabricate
a successful row. This is one implementation under different injected faults,
not a comparative implementation benchmark.

The raw result records the tested commit, Python and SQLite versions, operating
system, CPU description, workload and settings. It omits machine names, usernames,
local paths and personal data. Published results are added after the code commit
they measure, avoiding a circular self-referencing commit claim.

## Limits

These are loopback simulated observations on one developer machine. Intentional
delays dominate results. Scheduler load and filesystem behavior vary. There is
no real network, hardware, multi-client load, broker, or production extrapolation.
Passing this finite sample does not prove universal correctness. The independent
acceptance contract and focused tests remain the correctness evidence.
