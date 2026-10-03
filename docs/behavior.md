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
| Crash before pulse | Execution intent is durable; controller process exits before actuation; restarted controller reports IN_DOUBT | NEEDS_INSPECTION; zero pulses; no automatic resend |
| Crash after pulse | Execution intent is durable; independent instrument records actuation; controller process exits before completion is journaled | NEEDS_INSPECTION; one pulse; no automatic resend |

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

## Crash boundary extension — October 3, 2026

Acceptance for the extension, specified before its implementation:

1. Both crash cases terminate the actual device process, after persisting execution
   intent and before persisting completion. Only the after-pulse case applies a pulse.
2. A separate test instrument records pulses outside the controller transaction.
   Neither journal lookup nor the recovery decision may consult that instrument.
3. After restart, unfinished execution intent becomes IN_DOUBT. This is the same
   protocol evidence in both cases even though their physical outcomes differ.
4. The service enters NEEDS_INSPECTION, never COMPLETED or a fresh dispatch.
   Repeated ticks, duplicate delivery, and process restart must not apply another pulse.
5. Resume is rejected for this state. A new UUID would bypass deduplication, so it is
   not a recovery operation. Each UI request deliberately represents a different locker.
6. A crash in one experiment must not discard other queued experiments. Only the
   deliberate injection exit code is restarted by the local launcher; unexpected
   process failure still stops the lab.

The original four cases retain atomic simulated pulse/journal recording, which
isolates messaging faults. The crash cases deliberately remove that assumption.
They stop at the need for independent physical evidence; there is no invented
operator confirmation, sensor, or automated resolution. Journal loss, ambiguous
sensors, concurrent controllers, and real hardware remain outside this model.
This is not a claim of exactly-once physical execution.
