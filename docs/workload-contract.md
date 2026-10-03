# Concurrent recovery and external faults: acceptance contract

Specified October 3, 2026, before implementation of this extension.

The question is whether a slow device blocks unrelated queued operations, and
what correctness protections concurrent recovery needs. Each operation still
represents a separate synthetic locker. This is not a shared-actuator scheduler.

1. Multiple workers may advance different operations. Only one unexpired durable
   lease owns a given operation at a time. Every worker update must check its lease.
2. An expired/replaced owner cannot regress an operation, append stale evidence,
   or release a newer owner's lease. Claiming work increments its ownership epoch.
3. A service process crash may abandon leases. Once they expire, another process
   queries previously dispatched commands before considering a resend.
4. Leases fence service-journal writes, not external physical actions. Duplicate
   commands remain protected by the device's immutable command journal.
5. A separate HTTP fault proxy controls delay, dropped request, dropped response,
   and duplicated delivery without selecting a service or device fault scenario.
   Both applications receive ordinary healthy commands in this workload.
6. Every submitted operation must reach a classified outcome within a bounded
   experiment deadline. No timeout or unobserved outcome is silently discarded.
7. Completed operations require controller completion evidence, exactly one
   simulated pulse in this atomic-journal workload, and no state regression.
8. Compare one and four workers using the same finite queued batch, operation
   identities, seeded fault assignments, device delay, retry settings and database
   configuration. Keep warmups and timing repetitions separate from independent
   seeds. Save per-operation observations, proxy events and source/environment.

Measure batch completion time and completion delay for unaffected operations:
does bounded concurrency reduce head-of-line waiting in this particular workload?
Record uncertainty/retries too. Do not extrapolate to fleet capacity, production
latency, real hardware reliability, or universal throughput improvements.
