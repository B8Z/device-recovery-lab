"""Capture real local API snapshots for the static evidence viewer, not synthetic replay output."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.common import request, SCENARIOS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--output", default="demo/traces.json")
    args = parser.parse_args()
    # Restrict capture to a loopback lab, not an arbitrary remote endpoint.
    from urllib.parse import urlsplit
    target = urlsplit(args.url)
    if target.scheme != "http" or target.hostname not in ("127.0.0.1", "localhost") or target.username:
        parser.error("Use the loopback lab URL")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
    if dirty:
        parser.error("Commit source changes before capturing evidence")
    traces = []
    for scenario in SCENARIOS:
        command_id = str(uuid.uuid4())
        code, _ = request(args.url + "/api/runs", {"id": command_id, "scenario": scenario})
        if code != 202:
            raise RuntimeError("Run was not accepted")
        started = time.monotonic()
        frames = []
        reconnected = False
        while time.monotonic() - started < 20:
            status, value = request(args.url + "/api/runs/" + command_id)
            if status != 200:
                raise RuntimeError("Snapshot unavailable")
            elapsed = time.monotonic() - started
            frame = {"observed_seconds": round(elapsed, 6), "snapshot": value}
            if not frames or value != frames[-1]["snapshot"]:
                frames.append(frame)
            if scenario == "disconnected" and not reconnected and elapsed >= 1:
                code, _ = request(args.url + f"/api/runs/{command_id}/reconnect", {})
                if code != 200:
                    raise RuntimeError("Reconnect failed")
                reconnected = True
            if value["state"] in ("COMPLETED", "NEEDS_INSPECTION"):
                break
            time.sleep(.1)
        expected_state = "NEEDS_INSPECTION" if scenario.startswith("crash_") else "COMPLETED"
        expected_pulses = 0 if scenario == "crash_before" else 1
        if value["state"] != expected_state or not value["device"] or value["device"]["pulses"] != expected_pulses:
            raise RuntimeError("Capture did not reach the contract's expected outcome")
        traces.append({"scenario": scenario, "frames": frames})
    result = {"captured_at_utc": datetime.now(timezone.utc).isoformat(), "tested_commit": commit,
              "python": platform.python_version(), "os": platform.system(),
              "capture": {"poll_seconds": .1, "reconnect_after_seconds": 1,
                          "frame_rule": "retain changed full API snapshots", "runs_per_scenario": 1,
                          "purpose": "demonstration traces, not performance measurements"},
              "traces": traces}
    path = ROOT / args.output
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("Captured", len(traces), "scenarios at", commit)


if __name__ == "__main__":
    main()
