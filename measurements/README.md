# Recovery observations

Question: **Do duplicates and missing responses multiply actuator pulses, and
what recovery work is visible compared with healthy delivery?**

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
