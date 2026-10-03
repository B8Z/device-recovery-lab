# Behavior contract

Written before the implementation on October 3, 2026. These are acceptance
criteria, not conclusions inferred from a successful run.

Each experiment requests one release pulse on a fresh synthetic locker. A
command has an immutable ID and payload. Receiving that command is not evidence
that the actuator moved. Only a completed device journal entry confirms the
simulated action to the service.

| Case | Required observations | Final condition |
| --- | --- | --- |
| Healthy | Request persisted; receipt recorded; physical action performed; completion observed | COMPLETED; one actuator pulse |
| Duplicate | Two command deliveries using the same ID; second delivery suppressed by the device | COMPLETED; one actuator pulse |
| Lost completion acknowledgment | Physical action recorded; one completion response dropped; service enters UNCERTAIN; service queries journal | COMPLETED by reconciliation; one actuator pulse, one command delivery |
| Disconnected | Command cannot reach device; no actuator pulse while offline; bounded probes; reconnect; journal reports absent; same command ID retried | COMPLETED after reconnect; one actuator pulse |

Additional invariants:

- Retrying a client request with the same ID and same scenario returns the same
  operation. Reusing it with different parameters is a conflict (409).
- Reusing a device command ID with different action/locker data is a conflict.
- An accepted receipt cannot transition the service directly to COMPLETED.
- Ambiguous transport failures are UNCERTAIN, never proof of failure or success.
- Retry exhaustion is NEEDS_ATTENTION. It must not invent a final device outcome.
- Restarting the service or simulator preserves journaled operations. A service
  crash after dispatch is recovered by querying the same command ID first.
- An offline diagnostic view is available to the visitor as a test instrument.
  The recovery controller must never use that side channel as execution evidence.

The simulator commits its pulse count and completion record in one SQLite
transaction. Real motors cannot generally participate in that transaction.
Controller journal loss, actuator/journal crash gaps, sensor ambiguity and multiple
controllers are outside this guarantee; those can require human intervention.
This is not a claim of exactly-once physical execution.
