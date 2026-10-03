"""Contract checks using actual abrupt process exits, not simulated exceptions."""
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

from lab.common import INJECTED_CRASH_EXIT, Problem, database, request
from lab.service import Service
from lab.device import Device
import run

ROOT = Path(__file__).resolve().parents[1]


class CrashBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        with socket.socket() as port:
            port.bind(("127.0.0.1", 0))
            self.port = port.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.child = None
        self.start_device()
        self.service = Service(self.root / "service.db", self.url, interval=0)

    def start_device(self):
        self.child = subprocess.Popen(
            [sys.executable, "-m", "lab.device", "--port", str(self.port),
             "--data", str(self.root / "device.db")], cwd=ROOT,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            self.assertIsNone(self.child.poll(), "Controller exited during startup")
            try:
                if request(self.url + "/health", timeout=.2)[0] == 200:
                    return
            except OSError:
                pass
            time.sleep(.02)
        self.fail("Controller did not start")

    def stop_device(self):
        if self.child and self.child.poll() is None:
            self.child.terminate()
            self.child.wait(timeout=5)

    def tearDown(self):
        self.stop_device()
        self.temp.cleanup()

    def check_boundary(self, scenario, expected_pulses):
        run_id = str(uuid.uuid4())
        self.service.create({"id": run_id, "scenario": scenario})
        self.service.tick()
        self.assertEqual(INJECTED_CRASH_EXIT, self.child.wait(timeout=10))
        # The process died with intent committed and completion absent.
        with database(self.root / "device.db") as con:
            self.assertEqual("EXECUTING", con.execute("SELECT state FROM commands WHERE id=?", (run_id,)).fetchone()[0])
        self.start_device()
        status, evidence = request(self.url + "/commands/" + run_id)
        self.assertEqual(200, status)
        self.assertEqual({"id": run_id, "state": "IN_DOUBT"}, evidence)
        self.service.tick()
        snap = self.service.snapshot(run_id)
        self.assertEqual("NEEDS_INSPECTION", snap["state"])
        self.assertEqual(expected_pulses, snap["device"]["pulses"])
        self.assertEqual(1, snap["sends"])
        self.assertEqual(expected_pulses, sum(e["kind"] == "PHYSICAL_ACTION_PERFORMED" for e in snap["events"]))
        with self.assertRaises(Problem) as rejected:
            self.service.resume(run_id)
        self.assertEqual(409, rejected.exception.status)
        # A duplicate, controller restart and service restart cannot turn missing
        # completion evidence into either a new action or an invented success.
        body = {"id": run_id, "locker": run_id, "action": "release", "scenario": scenario}
        self.assertEqual((202, evidence), request(self.url + "/commands", body))
        self.stop_device()
        self.start_device()
        restarted = Service(self.service.path, self.url, interval=0)
        for _ in range(5):
            restarted.tick()
        final = restarted.snapshot(run_id)
        self.assertEqual("NEEDS_INSPECTION", final["state"])
        self.assertEqual(expected_pulses, final["device"]["pulses"])
        self.assertEqual(1, final["sends"])
        # Delete only the test instrument's data. Journal lookup and decisions
        # remain identical, proving that physical diagnostics are not an oracle.
        with database(self.root / "device.db.instrument") as con:
            con.execute("DELETE FROM pulses")
            con.execute("DELETE FROM events")
        self.assertEqual((200, evidence), request(self.url + "/commands/" + run_id))
        restarted.record(run_id, "TEST_REQUERY", "Exercise decision without instrument evidence", state="UNCERTAIN")
        restarted.tick()
        with database(restarted.path) as con:
            row = con.execute("SELECT state,sends FROM runs WHERE id=?", (run_id,)).fetchone()
        self.assertEqual(("NEEDS_INSPECTION", 1), tuple(row))

    def test_crash_before_pulse_stops_with_zero_actions(self):
        self.check_boundary("crash_before", 0)

    def test_crash_after_pulse_stops_with_one_action(self):
        self.check_boundary("crash_after", 1)

    def test_other_received_commands_survive_an_injected_crash(self):
        crash, healthy = str(uuid.uuid4()), str(uuid.uuid4())
        for run_id, scenario in ((crash, "crash_after"), (healthy, "healthy")):
            self.service.create({"id": run_id, "scenario": scenario})
        self.service.tick()
        self.assertEqual(INJECTED_CRASH_EXIT, self.child.wait(timeout=10))
        self.start_device()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.service.tick()
            if self.service.snapshot(healthy)["state"] == "COMPLETED":
                break
            time.sleep(.02)
        self.assertEqual("NEEDS_INSPECTION", self.service.snapshot(crash)["state"])
        final = self.service.snapshot(healthy)
        self.assertEqual("COMPLETED", final["state"])
        self.assertEqual(1, final["device"]["pulses"])


class LauncherStartupTest(unittest.TestCase):
    def test_due_crash_command_restarts_during_startup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with socket.socket() as first, socket.socket() as second:
                first.bind(("127.0.0.1", 0))
                second.bind(("127.0.0.1", 0))
                service_port, device_port = first.getsockname()[1], second.getsockname()[1]
            run_id = str(uuid.uuid4())
            device_path = root / "device.sqlite3"
            Device(device_path, action_delay=0).accept({"id": run_id, "locker": run_id,
                                                       "action": "release", "scenario": "crash_after"})
            delayed = False
            healthy = False

            def probe(url, **kwargs):
                nonlocal delayed, healthy
                if url == f"http://127.0.0.1:{device_port}/health" and not delayed:
                    delayed = True
                    # Force the first readiness observation to occur after the
                    # actual injected exit, independent of machine startup speed.
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        with database(device_path) as con:
                            state = con.execute("SELECT state FROM commands WHERE id=?", (run_id,)).fetchone()[0]
                        if state == "EXECUTING":
                            time.sleep(.1)
                            raise OSError("Readiness probe delayed across real process exit")
                        time.sleep(.02)
                    self.fail("Queued crash did not execute")
                result = request(url, **kwargs)
                if url == f"http://127.0.0.1:{service_port}/health" and result[0] == 200:
                    healthy = True
                    # Exercise the launcher's normal cleanup path after readiness.
                    raise KeyboardInterrupt
                return result

            args = ["run.py", "--port", str(service_port), "--device-port", str(device_port), "--data-dir", temp]
            with patch.object(sys, "argv", args), patch.object(run, "request", probe):
                run.main()
            self.assertTrue(healthy)
            with database(device_path) as con:
                self.assertEqual("IN_DOUBT", con.execute("SELECT state FROM commands WHERE id=?", (run_id,)).fetchone()[0])
            with database(str(device_path) + ".instrument") as con:
                self.assertEqual(1, con.execute("SELECT count FROM pulses WHERE id=?", (run_id,)).fetchone()[0])


if __name__ == "__main__":
    unittest.main()
