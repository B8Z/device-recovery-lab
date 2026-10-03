# Device Recovery Lab

**A message arrived. Did the locker open?**

A working local laboratory for the gap between message delivery and a physical
effect. Request a simulated parcel-locker release, break the communication, and
inspect what the service knows versus what the device actually did.

| Inject a failure | What to inspect |
| --- | --- |
| **Duplicate command** | Two deliveries share one command ID. The controller suppresses the duplicate and records one pulse. |
| **Lost acknowledgment** | The device acts, then its completion response is dropped. The service enters UNCERTAIN and reconciles from the journal without resending. |
| **Disconnected device** | The service backs off while the device remains closed. Restore the link and watch it query the journal before retrying the same command. |

![Actual local run: lost completion acknowledgment, one actuator pulse, and successful journal reconciliation](docs/demo-lost-ack.png)

The screenshot is captured by the browser tests, not a mockup. The timeline shows
the completed lost-ack experiment. During recovery, the service can be uncertain
while the test instrument already shows an open locker.

## Run it

Requires **Python 3.11+ with SQLite** and a browser. No runtime package install,
Docker, broker, cloud account, API key or paid service.

```sh
git clone https://github.com/B8Z/device-recovery-lab.git
cd device-recovery-lab
python run.py
```

Open **http://127.0.0.1:8765**. If your system calls Python `python3`, use that
command instead; Windows also supports `py -3 run.py`.

1. Start **Healthy delivery** and select **Request release**. Inspect the receipt,
   later physical pulse, and completed journal evidence.
2. Select **Lost acknowledgment**, request another release, and inspect the
   `ACK DROPPED → OUTCOME UNCERTAIN → RECONCILED` sequence. The pulse count stays one.
3. Select **Disconnected device**, request release, then **Reconnect device**.
   Leaving it disconnected eventually pauses automatic recovery; reconnect also
   resumes reconciliation.
4. Use **Export evidence JSON** or **Recent run** to inspect and compare runs.

Stop both processes with Ctrl+C. Journals persist in `.lab/` (ignored by Git).
For a fresh session use `python run.py --data-dir .lab/fresh`. Busy ports can be
changed with `--port 8875 --device-port 8876`. Only loopback connections are served.

## What to inspect in the code

- [Behavior contract](docs/behavior.md): expected outcomes written before implementation.
- [Recovery controller](lab/service.py): durable intent before I/O, bounded backoff,
  ambiguous outcomes, journal-first retries and explicit attention state.
- [Device journal](lab/device.py): asynchronous receipt versus execution, durable
  duplicate suppression, and an actual dropped HTTP response.
- [Acceptance tests](tests/test_recovery.py): pulse-count invariants, restarts,
  conflicts, concurrent requests, failure budgets and HTTP boundaries.
- [Architecture and alternatives](docs/architecture.md): why this slice uses two
  Python processes, HTTP and SQLite instead of requiring Spring/Kafka.
- [Verification guide](docs/testing.md) and [reproducible observations](measurements/README.md).

```text
Browser → service + durable intent journal → HTTP → simulated device + execution journal
               ↓ recovery queries                          ↓ delayed release pulse
            event timeline ← labeled diagnostic view ← receipt / completion / faults
```

The service has one recovery worker; the device has a separate execution worker
and database. The browser's diagnostic view is test instrumentation. Recovery
never uses it as authoritative completion evidence.

## Tests and measurements

```sh
python -m unittest -v
```

Optional Playwright checks exercise the real interface; instructions and coverage
are in [docs/testing.md](docs/testing.md). The measurement script records command
sends, journal queries, actuator pulses and local end-to-end observation times
under the same settings for all four scenarios. Raw data includes the tested
commit and environment; timings include polling and intentional fault delays.
They are not a production latency benchmark.

## Limits and next questions

**Receiving a message is not completing a physical action.** The simulator makes
its pulse counter and completion record atomic in SQLite. Real hardware usually
cannot join that transaction. Controller journal loss, a crash between motor
movement and durable recording, and ambiguous sensor readings need additional
device-specific safeguards or human intervention. There is no exactly-once claim.

Completed here: three injected failures, healthy baseline, restartable journals,
bounded recovery, visible evidence, automated acceptance and browser checks.
Future experiments, **not implemented**: controller storage loss, actuator/journal
crash gaps, multiple devices/controllers, and alternative broker transports.

This is an independent personal demonstration using synthetic data, created in
October 2026. It contains no employer code, interfaces, incident reconstructions,
or deployment claims. AI tools assisted development; behavior is backed by the
published contract, executable checks and recorded observations.

MIT licensed. Runtime uses the Python standard library; optional browser tests
use Playwright (Apache-2.0). See [LICENSE](LICENSE).
