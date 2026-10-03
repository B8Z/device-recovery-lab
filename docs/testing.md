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
