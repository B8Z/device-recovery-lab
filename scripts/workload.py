"""Compare one/four recovery workers against an independent seeded HTTP fault proxy.

No runtime dependencies. Measurements require a clean source commit. Use --check
for a small correctness journey on a dirty candidate, without publishing timings.
"""
import argparse
from datetime import datetime, timezone
import http.client
import json
import os
from pathlib import Path
import platform
import random
import socket
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.common import database, request
from lab.fault_proxy import PROFILES
from lab.service import Service


def ports(count):
    sockets = [socket.socket() for _ in range(count)]
    try:
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def schedule(seed, count, workload):
    profiles = [PROFILES[i % len(PROFILES)] if workload == "mixed" else "clean" for i in range(count)]
    random.Random(seed).shuffle(profiles)
    return {str(uuid.uuid5(uuid.NAMESPACE_URL, f"recovery-lab/{seed}/{i}")): p for i, p in enumerate(profiles)}


def start(children, args, port, root):
    log = (root / f"process-{port}.log").open("w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, *args], cwd=ROOT, stdout=log, stderr=log)
    children.append((process, log))
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Process exited; inspect {log.name}")
        try:
            if request(f"http://127.0.0.1:{port}/health", timeout=.2)[0] == 200:
                return
        except (OSError, http.client.HTTPException):
            pass
        time.sleep(.02)
    raise RuntimeError("Readiness deadline expired")


def trial(root, workers, seed, workload, count=24, delay=.3):
    root.mkdir(parents=True)
    assigned = schedule(seed, count, workload)
    (root / "schedule.json").write_text(json.dumps(assigned), encoding="utf-8")
    device_port, proxy_port, service_port = ports(3)
    children = []
    try:
        start(children, ["-m", "lab.device", "--port", str(device_port), "--data", str(root / "device.db")], device_port, root)
        start(children, ["-m", "lab.fault_proxy", "--port", str(proxy_port), "--device-port", str(device_port),
                         "--schedule", str(root / "schedule.json"), "--delay", str(delay)], proxy_port, root)
        # Stage an identical queued batch before starting either worker strategy.
        # The measured boundary is queue eligibility, not HTTP admission/startup.
        queue = Service(root / "service.db", f"http://127.0.0.1:{proxy_port}")
        for run_id in assigned:
            queue.create({"id": run_id, "scenario": "healthy"})
        eligible_at = time.time() + 2
        with database(queue.path) as con:
            con.execute("UPDATE runs SET next_at=?", (eligible_at,))
        start(children, ["-m", "lab.service", "--port", str(service_port), "--device-port", str(proxy_port),
                         "--data", str(queue.path), "--workers", str(workers)], service_port, root)
        if time.time() >= eligible_at:
            raise RuntimeError("Startup missed the common queue gate; trial is invalid")
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if any(p.poll() is not None for p, _ in children):
                raise RuntimeError("A workload process exited")
            with database(queue.path) as con:
                states = [r[0] for r in con.execute("SELECT state FROM runs")]
            if all(s in ("COMPLETED", "NEEDS_ATTENTION", "NEEDS_INSPECTION") for s in states):
                break
            time.sleep(.02)
        observations = request(f"http://127.0.0.1:{proxy_port}/observations")[1]
        rows = []
        with database(queue.path) as service, database(root / "device.db") as device:
            for run_id, profile in assigned.items():
                row = dict(service.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
                effect = device.execute("SELECT state,pulses FROM commands WHERE id=?", (run_id,)).fetchone()
                events = [dict(e) for e in service.execute("SELECT at,kind FROM events WHERE run_id=? ORDER BY seq", (run_id,))]
                physical = [dict(e) for e in device.execute("SELECT at,kind FROM events WHERE run_id=? ORDER BY seq", (run_id,))]
                completions = [e["at"] for e in events if e["kind"] in ("COMPLETION_CONFIRMED", "RECONCILED")]
                pulses = effect["pulses"] if effect else 0
                classification = "completed" if row["state"] == "COMPLETED" else "timeout" if row["state"] in ("QUEUED", "ACCEPTED", "UNCERTAIN") else "needs_attention"
                pulse_events = [e["at"] for e in physical if e["kind"] == "PHYSICAL_ACTION_PERFORMED"]
                if classification == "completed" and (pulses != 1 or len(pulse_events) != 1 or len(completions) != 1
                        or effect["state"] != "COMPLETED" or completions[0] < pulse_events[0]
                        or not any(e["kind"] == "COMPLETION_REPORTED" and e["at"] <= completions[0] for e in physical)):
                    classification = "invariant_violation"
                if profile == "duplicate" and not any(e["kind"] == "DUPLICATE_SUPPRESSED" for e in physical):
                    classification = "invariant_violation"
                faults = [o["kind"] for o in observations if o["id"] == run_id]
                required = {"slow":"DELAY_REQUEST", "drop_request":"DROP_BEFORE_FORWARD",
                            "drop_receipt":"DROP_AFTER_FORWARD", "duplicate":"DUPLICATE_FORWARD",
                            "drop_completion":"DROP_COMPLETION_RESPONSE"}.get(profile)
                if required and faults.count(required) != 1:
                    classification = "fault_not_exercised"
                rows.append({"id":run_id, "profile":profile, "state":row["state"], "classification":classification,
                             "completion_seconds":round(completions[0]-eligible_at, 6) if completions else None,
                             "pulses":pulses, "sends":row["sends"], "queries":row["checks"], "ownership_epochs":row["epoch"],
                             "service_events":[dict(e, at=round(e["at"]-eligible_at,6)) for e in events],
                             "device_events":[dict(e, at=round(e["at"]-eligible_at,6)) for e in physical]})
        for observation in observations:
            observation["at"] = round(observation["at"]-eligible_at, 6)
        healthy = [r["completion_seconds"] for r in rows if r["profile"] == "clean" and r["classification"] == "completed"]
        return {"workers":workers, "seed":seed, "workload":workload, "queue_eligible_at":eligible_at,
                "batch_seconds":max((r["completion_seconds"] or 0 for r in rows)) if all(r["classification"] == "completed" for r in rows) else None,
                "unaffected_median_seconds":statistics.median(healthy) if healthy else None,
                "operations":rows, "proxy_observations":observations}
    finally:
        for process, _ in children:
            if process.poll() is None:
                process.terminate()
        for process, log in children:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
            log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", default="measurements/concurrency.json")
    parser.add_argument("--seeds", default="7,23,99")
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    seeds = [int(s) for s in args.seeds.split(",")]
    if not seeds or len(set(seeds)) != len(seeds) or args.repetitions < 1:
        parser.error("Use distinct seeds and at least one repetition")
    commit = subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    dirty = bool(subprocess.check_output(["git","status","--porcelain"],cwd=ROOT,text=True).strip())
    if dirty and not args.check:
        parser.error("Commit source before measuring; --check only verifies correctness")
    result = {"recorded_at_utc":datetime.now(timezone.utc).isoformat(), "tested_commit":commit,
              "environment":{"python":platform.python_version(), "sqlite":sqlite3.sqlite_version,
                             "os":platform.platform(), "processor":platform.processor(), "logical_cpus":os.cpu_count(),
                             "dependencies":"Python standard library"},
              "configuration":{"operations_per_batch":24, "seeds":seeds, "timing_repetitions":args.repetitions,
                               "worker_counts":[1,4], "workloads":["clean","mixed"], "delayed_request_seconds":.3,
                               "device_action_seconds":.35, "retry_interval_seconds":.6, "lease_seconds":5,
                               "observer_poll_seconds":.02, "deadline_seconds":40,
                               "gate":"pre-staged batch, eligible two seconds after staging; startup must finish before eligibility",
                               "measurement":"completion event wall time minus shared queue eligibility; excludes admission/startup",
                               "warmup":"one mixed batch per worker count at seed0; excluded",
                               "order":"rotate 1/4-worker order by seed index plus timing repetition; clean then mixed",
                               "limitations":"single host; controlled faults; wall-clock adjustments unmodeled; finite independent lockers; not fleet capacity"},
              "trials":[]}
    with tempfile.TemporaryDirectory(prefix="recovery-workload-") as temp:
        root = Path(temp)
        combinations = [(w,0,"mixed",True,0) for w in (1,4)] if not args.check else []
        for repetition in range(1 if args.check else args.repetitions):
            for index, seed in enumerate(seeds[:1] if args.check else seeds):
                for workload in (["mixed"] if args.check else ["clean","mixed"]):
                    order = (1,4) if (index+repetition)%2 == 0 else (4,1)
                    combinations.extend((w,seed,workload,False,repetition) for w in order)
        for index, (workers,seed,workload,warmup,repetition) in enumerate(combinations):
            try:
                row = trial(root / str(index), workers, seed, workload)
            except Exception as exc:
                if args.check:
                    raise
                # Retain failed trials in the published denominator. Do not export
                # local filesystem paths or replace a failed trial with a retry.
                row = {"workers":workers,"seed":seed,"workload":workload,
                       "exception_type":type(exc).__name__, "batch_seconds":None,
                       "unaffected_median_seconds":None,"proxy_observations":[],
                       "operations":[{"id":key,"profile":value,"classification":"process_error"}
                                     for key,value in schedule(seed,24,workload).items()]}
            row.update(warmup=warmup,repetition=repetition)
            result["trials"].append(row)
            failures = [r["classification"] for r in row["operations"] if r["classification"] != "completed"]
            print(workload, seed, workers, "workers", "correct" if not failures else failures, flush=True)
    if args.check:
        if any(r["classification"] != "completed" for t in result["trials"] for r in t["operations"]):
            raise SystemExit("Correctness workload failed")
        print("Correctness only: no timing artifact published")
        return
    result["summary"] = []
    for workload in ("clean","mixed"):
        for workers in (1,4):
            trials = [t for t in result["trials"] if not t["warmup"] and t["workload"] == workload and t["workers"] == workers]
            entry = {"workload":workload,"workers":workers,"batches":len(trials),"independent_seeds":len(seeds)}
            for metric in ("batch_seconds","unaffected_median_seconds"):
                values = [t[metric] for t in trials if t[metric] is not None]
                entry[metric] = {"sample_size":len(values),"median":statistics.median(values) if values else None,
                                 "min":min(values) if values else None,"max":max(values) if values else None}
            result["summary"].append(entry)
    output = ROOT / args.output
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    if any(r["classification"] != "completed" for t in result["trials"] for r in t["operations"]):
        raise SystemExit("Non-completion or invariant failure retained in raw data")
    print("Saved", output)


if __name__ == "__main__":
    main()
