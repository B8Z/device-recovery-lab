"""Measure recovery observations against two running, freshly started lab processes.

Run from repository root: python scripts/measure.py --output measurements/run.json
Timing includes polling and synthetic fault delays, excludes startup. Not a load test.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import sqlite3
import statistics
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.common import SCENARIOS, request


def trial(base, scenario, warmup, repetition):
    run_id = str(uuid.uuid4())
    started = time.perf_counter()
    status, _ = request(base + "/api/runs", {"id":run_id,"scenario":scenario})
    if status != 202:
        raise RuntimeError("Experiment request was not accepted")
    reconnected = False
    classification = "timeout"
    result = None
    while time.perf_counter() - started < 20:
        _, result = request(base + "/api/runs/" + run_id)
        elapsed = time.perf_counter() - started
        if scenario == "disconnected" and not reconnected and elapsed >= 0.75:
            code, _ = request(base + f"/api/runs/{run_id}/reconnect", {})
            if code != 200:
                raise RuntimeError("Reconnect failed")
            reconnected = True
        if result["state"] in ("COMPLETED", "NEEDS_ATTENTION"):
            classification = "completed" if result["state"] == "COMPLETED" else "needs_attention"
            break
        time.sleep(0.05)
    elapsed = time.perf_counter() - started
    kinds = [e["kind"] for e in result["events"]]
    pulses = result["device"]["pulses"] if result["device"] else None
    expected_sends = 2 if scenario in ("duplicate","disconnected") else 1
    required = {"healthy":"COMPLETION_CONFIRMED", "duplicate":"DUPLICATE_SUPPRESSED",
                "lost_ack":"RECONCILED", "disconnected":"JOURNAL_ABSENT"}[scenario]
    if classification == "completed" and (pulses != 1 or result["sends"] != expected_sends or required not in kinds):
        classification = "invariant_violation"
    return {"scenario":scenario,"warmup":warmup,"repetition":repetition,
            "observation_seconds":round(elapsed,6),"classification":classification,
            "command_sends":result["sends"],"journal_queries":result["checks"],
            "actuator_pulses":pulses,"events":[{"source":e["source"],"kind":e["kind"],
             "elapsed_seconds":round(e["at"]-result["created"],6)} for e in result["events"]]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--repetitions", type=int, default=8)
    parser.add_argument("--output", default="measurements/run.json")
    args = parser.parse_args()
    if args.repetitions < 2:
        parser.error("At least two repetitions are required")
    commit = subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
    dirty = subprocess.check_output(["git","status","--porcelain","--untracked-files=no"],text=True).strip()
    if dirty:
        parser.error("Commit tracked changes before recording measurements")
    data = {"recorded_at_utc":datetime.now(timezone.utc).isoformat(),"tested_commit":commit,
            "environment":{"os":platform.system(),"release":platform.release(),"version":platform.version(),
              "machine":platform.machine(),"processor":platform.processor(),"logical_cpus":os.cpu_count(),
              "python":platform.python_version(),"sqlite":sqlite3.sqlite_version,"runtime_dependencies":"Python standard library only"},
            "configuration":{"service_interval_seconds":0.6,"device_action_delay_seconds":0.35,
              "device_tick_seconds":0.025,"service_tick_seconds":0.05,"max_consecutive_failures":6,
              "max_backoff_seconds":2.4,"http_timeout_seconds":1,"observer_poll_seconds":0.05,
              "disconnect_reconnect_after_seconds":0.75,"trial_timeout_seconds":20,
              "concurrent_operations":1,"warmups_per_scenario":1,"repetitions_per_scenario":args.repetitions,
              "seed":None,"seed_note":"No randomized fault schedule or workload; UUIDs identify operations only.",
              "order":"One warmup per scenario, then round-robin scenario order each repetition."},
            "timing_boundary":"Client before POST intent to first GET observing terminal service state; process startup excluded.",
            "trials":[]}
    for repetition in range(args.repetitions + 1):
        for scenario in SCENARIOS:
            row = trial(args.url, scenario, repetition == 0, repetition)
            data["trials"].append(row)
            print(scenario, repetition, row["classification"], row["observation_seconds"], flush=True)
    data["summary"] = {}
    for scenario in SCENARIOS:
        rows = [r for r in data["trials"] if r["scenario"] == scenario and not r["warmup"]]
        times = [r["observation_seconds"] for r in rows if r["classification"] == "completed"]
        data["summary"][scenario] = {"sample_size":len(rows),"completed":len(times),
             "median_seconds":statistics.median(times) if times else None,
             "min_seconds":min(times) if times else None,"max_seconds":max(times) if times else None,
             "sample_stdev_seconds":statistics.stdev(times) if len(times)>1 else None}
    output = Path(args.output); output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")
    if any(r["classification"] != "completed" for r in data["trials"]):
        raise SystemExit("Non-completing or incorrect trial recorded; inspect raw data")


if __name__ == "__main__":
    main()
