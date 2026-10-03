# Verification

The [behavior contract](behavior.md) defines expected outcomes independently of
the code. Tests count physical pulses and verify intermediate evidence, rather
than accepting only a final green status.

Run `python -m unittest -v`. These checks exercise real loopback HTTP connections
and temporary SQLite journals. Explicit worker ticks control ordering without
sleep-based timing assertions. Coverage includes all four workflows, client and
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

Restart tests reopen the persisted controller and service objects with the same
database files. They model restart at known boundaries; they are not power-loss
tests. A separate clean-checkout journey verifies the launcher starts two actual
processes. There is no hardware-in-the-loop test and no full accessibility audit.

Correctness checks are separate from `scripts/measure.py`. That script records
loopback end-to-end observation times and recovery counts; it does not establish
capacity, production latency or reliability probabilities.

## Captured evidence viewer

`demo/` is a static viewer of actual full API snapshots, captured from a local
run with `python scripts/capture_traces.py`. The script requires a clean checkout;
start fresh lab processes from that same checkout before capturing. It retains
changed snapshots at a 100 ms polling interval, restores the disconnected link
after one second, and checks completion with one pulse in each scenario.
One run per scenario is demonstration evidence, not a new performance sample.

The JSON retains the source revision, capture date, runtime and capture settings.
The viewer labels the data as recorded and defaults to the lost-acknowledgment
snapshot where the service is uncertain but the diagnostic device panel is open.
Playback advances snapshots every 700 ms; the displayed elapsed times remain the
original observations. It does not rerun the service in the browser.

Serve `demo/` on port 8879 with `python -m http.server 8879 --bind 127.0.0.1
--directory demo`, then run `npx playwright test --config playwright.demo.config.js`.
The check covers all four recorded outcomes, uncertainty, pulse counts, keyboard
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
