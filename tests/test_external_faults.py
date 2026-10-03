"""End-to-end faults outside both applications, including an interrupted owner."""
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

from lab.common import Server, database, request
from lab.fault_proxy import FaultProxy, ProxyHandler
from lab.service import Service
from scripts.workload import ports, start, trial
from scripts import workload


class ExternalFaultTest(unittest.TestCase):
    def test_oracle_rejects_a_worker_that_invents_completion_without_querying(self):
        original = workload.start
        def substitute(children, args, port, root):
            if args[:2] == ["-m", "lab.service"]:
                args = [str(Path(__file__).parent / "fixtures/no_evidence_service.py"), *args[2:]]
            return original(children, args, port, root)
        with tempfile.TemporaryDirectory() as temp, patch.object(workload, "start", substitute):
            result = trial(Path(temp) / "bad-worker", workers=4, seed=23, workload="clean", count=6)
        self.assertEqual(["invariant_violation"] * 6, [r["classification"] for r in result["operations"]])
        self.assertFalse(any(o["kind"] == "FORWARD_GET" for o in result["proxy_observations"]))

    def test_all_external_faults_preserve_execution_and_completion_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            result = trial(Path(temp) / "batch", workers=4, seed=23, workload="mixed", count=12, delay=.1)
        self.assertEqual(12, len(result["operations"]))
        for operation in result["operations"]:
            self.assertEqual("completed", operation["classification"], operation)
            self.assertEqual(1, operation["pulses"])
            kinds = [e["kind"] for e in operation["device_events"]]
            self.assertIn("COMPLETION_REPORTED", kinds)
            if operation["profile"] == "duplicate":
                self.assertIn("DUPLICATE_SUPPRESSED", kinds)
            if operation["profile"] == "drop_request":
                self.assertEqual(2, operation["sends"])
            if operation["profile"] in ("drop_receipt", "drop_completion"):
                self.assertEqual(1, operation["sends"])

    def test_killed_service_recovers_abandoned_lease_without_second_action(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            device_port, service_port, replacement_port = ports(3)
            forwarded, release = threading.Event(), threading.Event()

            class HoldReceipt(FaultProxy):
                def forward(self, run_id, body):
                    result = super().forward(run_id, body)
                    if body is not None:
                        forwarded.set()
                        release.wait(5)
                    return result

            proxy = Server(0, ProxyHandler, HoldReceipt(f"http://127.0.0.1:{device_port}", {}))
            thread = threading.Thread(target=proxy.serve_forever, kwargs={"poll_interval":.02}, daemon=True)
            thread.start()
            children = []
            run_id = str(uuid.uuid4())
            path = root / "service.db"
            try:
                start(children, ["-m","lab.device","--port",str(device_port),"--data",str(root / "device.db")], device_port, root)
                start(children, ["-m","lab.service","--port",str(service_port),"--device-port",str(proxy.server_port),
                                 "--data",str(path),"--workers","4"], service_port, root)
                self.assertEqual(202, request(f"http://127.0.0.1:{service_port}/api/runs", {"id":run_id,"scenario":"healthy"})[0])
                self.assertTrue(forwarded.wait(5))
                # Kill after device receipt but before service receives that response.
                children[1][0].kill(); children[1][0].wait(timeout=5)
                with database(path) as con:
                    row = dict(con.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
                self.assertEqual("UNCERTAIN", row["state"])
                self.assertIsNotNone(row["lease_owner"])
                release.set()
                start(children, ["-m","lab.service","--port",str(replacement_port),"--device-port",str(proxy.server_port),
                                 "--data",str(path),"--workers","4"], replacement_port, root)
                deadline = time.monotonic()+9
                while time.monotonic() < deadline:
                    with database(path) as con:
                        final = dict(con.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
                    if final["state"] == "COMPLETED":
                        break
                    time.sleep(.05)
                self.assertEqual("COMPLETED", final["state"])
                self.assertEqual(1, final["sends"])
                self.assertGreater(final["epoch"], row["epoch"])
                with database(root / "device.db") as con:
                    self.assertEqual(1, con.execute("SELECT pulses FROM commands WHERE id=?", (run_id,)).fetchone()[0])
                with proxy.app.lock:
                    observations = list(proxy.app.observations)
                self.assertEqual(1, sum(o["kind"] == "FORWARD_POST" for o in observations))
                self.assertGreaterEqual(sum(o["kind"] == "FORWARD_GET" for o in observations), 1)
            finally:
                release.set()
                for process, log in children:
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=5)
                    log.close()
                proxy.shutdown(); proxy.server_close(); thread.join(timeout=2)
