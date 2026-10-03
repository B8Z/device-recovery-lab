# Verification

The [behavior contract](behavior.md) defines expected outcomes independently of
the code. Tests count physical pulses and verify intermediate evidence, rather
than accepting only a final green status.

Run `python -m unittest -v`. These checks exercise real loopback HTTP connections
and temporary SQLite journals. The original checks use explicit worker ticks.
The crash checks launch subprocesses and wait for actual exits with bounded
deadlines; they do not assert a latency threshold. Coverage includes all six workflows, client and
device duplicate handling, concurrent requests, conflict handling, restart
persistence, bounded recovery and HTTP input/origin/path boundaries.

Run the lab in a separate terminal, then run optional browser checks:

```sh
npm ci
npx playwright install chromium
npm run test:e2e
```

Playwright checks every visitor workflow, pulse counts, diagnostic evidence,
history after reload, evidence download, keyboard scenario selection and a narrow
viewport. `CAPTURE_DEMO=1` enables screenshot capture to `docs/demo-lost-ack.png`
(PowerShell: `$env:CAPTURE_DEMO='1'`). This is a real rendered app screenshot.

The original restart tests reopen persisted controller and service objects.
`tests/test_crash_boundary.py` additionally kills the device process at explicit
injection boundaries using `os._exit`, checks its exit code and journal on disk,
then starts a new process against those files. Both pulse counts, duplicate
handling, blocked resume and unrelated queued work are checked. These are not
power-loss tests. The browser crash journeys also exercise automatic restart in
the launcher. There is no hardware-in-the-loop test and no full accessibility audit.

Correctness checks are separate from `scripts/measure.py`. That script records
loopback end-to-end observation times and recovery counts; it does not establish
capacity, production latency or reliability probabilities.

## Captured evidence viewer

`demo/` is a static viewer of actual full API snapshots, captured from a local
run with `python scripts/capture_traces.py`. The script requires a clean checkout;
start fresh lab processes from that same checkout before capturing. It retains
changed snapshots at a 100 ms polling interval, restores the disconnected link
after one second, and checks each terminal outcome against the contract:
completion with one pulse for the four messaging cases; inspection with zero
or one pulses for the before/after crash cases.
One run per scenario is demonstration evidence, not a new performance sample.

The JSON retains the source revision, capture date, runtime and capture settings.
The viewer labels the data as recorded and defaults to the lost-acknowledgment
snapshot where the service is uncertain but the diagnostic device panel is open.
Playback advances snapshots every 700 ms; the displayed elapsed times remain the
original observations. It does not rerun the service in the browser.

Serve `demo/` on port 8879:

```sh
python -m http.server 8879 --bind 127.0.0.1 --directory demo
npx playwright test --config playwright.demo.config.js
```

Run the second command in another terminal while the server is running.
The check covers all six recorded outcomes, uncertainty, pulse counts, keyboard
stepping, playback controls and a narrow viewport.

## First-release verification — October 3, 2026

At commit `bed2e3fe2487ef88596873b1fb57964033cc3d0a`, a fresh local clone and a
new Python 3.12.14 virtual environment with no third-party packages passed all
12 Python checks. `python run.py` started the real service and simulator processes
on two loopback ports. A clean `npm ci` followed by Playwright 1.63.0 / Chromium
153.0.8010.12 passed all six browser checks against that checkout. Ports were
changed to 8875/8876 using the documented options to avoid development instances.

An independent code review found command-conflict status, worker failure handling,
and stale-export issues; those were corrected before this candidate was tested.
Browser verification also exposed stale status text while creating a new run;
the UI now clears prior evidence immediately. One earlier browser run encountered
a transient Windows `ERR_NO_BUFFER_SPACE` during navigation. The complete final
suite passed, including the clean-checkout run, without test retries.

The committed screenshot was captured from the actual local interface. Secret
and disclosure pattern checks plus manual diff review found no credentials,
private career data or employer artifacts. These checks reduce publication risk;
they are not a third-party security certification.

## Crash-boundary extension verification — October 3, 2026

Runtime source `80571a42d337467f1c8e2ad5256411e04662bfef` passed all 16 Python
checks in a fresh local clone and a new Python 3.12.14 virtual environment without
third-party runtime packages. The documented launcher ran from that checkout on
ports 8880/8881. All eight live Playwright 1.63.0 / Chromium 153.0.8010.12 journeys
passed against it, including both actual process-crash cases and rejected resume.
The browser runner used the already installed test dependencies outside that
clone; running the application itself required no package installation.

Independent review found a startup edge case: a previously received crash
command could exit during readiness polling, before supervision began. The
launcher now handles the reserved injection exit during startup too. A focused
regression waits across the real process exit and verifies restart, persisted
uncertainty, one pulse, service readiness and normal child-process cleanup.

`demo/traces.json` records six fresh demonstrations at that runtime revision.
The static browser test checks every recorded terminal state, the zero/one pulse
comparison, keyboard stepping, playback and mobile layout. Screenshots were
captured from the rendered viewer. The mobile timeline reserves space for the
new `instrument` event source. These captures are correctness evidence; the
original four-scenario timing data remains attached to its original revision.

## Concurrent recovery and redesigned viewer — October 3, 2026

Runtime source `80215b81d2ae2ab61b67a8eb289692c09ead875b` passed all **23 Python
checks** in a fresh local clone and a new Python 3.12.14 virtual environment with
no third-party runtime packages. The documented launcher ran from that clean
checkout on ports 8870/8871. All **eight live Playwright journeys** passed against
it with four recovery workers. The browser runner used the existing Playwright
1.63.0 / Chromium 153.0.8010.12 installation outside the clone.

New checks cover competing claims, expired owners, stale candidate epochs,
existing-journal migration, an externally injected fault matrix, a service process
killed during an outstanding response, and rejection of a deliberately broken
worker that invents completion without a journal query. See
[the workload contract](workload-contract.md) and [experiment method](workload.md).

The full measurement ran from that same clean runtime source. A separate review
reconstructed the seeded inputs, paired identities, fault counts, completion
ordering and aggregate statistics from the retained raw data. All 36 measured
batches and both warmups are present. Correctness verification and performance
observations remain separate; passing these checks does not establish an
execution guarantee outside the tested model.

The redesigned static viewer has **three browser tests** covering all six
captured outcomes, keyboard stepping and playback, all 18 workload pairs,
the slower four-worker run, and layouts at 1440, 768, 720, 390 and 320 CSS pixels.
The 720-pixel case checks the reflow width corresponding to a 1440-pixel window
at 200% zoom; it does not control a browser's native zoom setting. Reduced-motion
preference is included. Charts use line patterns as well as color and expose
numeric results and accessible summaries.

Fresh screenshots were visually inspected. Review caught unreadably small mobile
evidence labels; the mobile layout now stacks scenarios and crash comparisons
and uses 12–14px core evidence text. The scope includes keyboard, layout and
visual checks, not a full screen-reader or WCAG certification audit.

`demo/traces.json` now contains six fresh captures at this runtime revision.
The device illustration follows those snapshots. The workload chart is derived
from the retained measurement file; its source hash uses normalized Git LF bytes.
