"""Acceptance checks derived from docs/behavior.md; real loopback HTTP transport."""
from concurrent.futures import ThreadPoolExecutor
import http.client
from pathlib import Path
import tempfile
import threading
import time
import unittest
import uuid

from lab.common import Server, database, request, run_server
from lab.device import Device, DeviceHandler
from lab.service import Service, ServiceHandler


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.device = Device(root / "device.db", action_delay=0)
        self.server = Server(0, DeviceHandler, self.device)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval":0.01}, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.service = Service(root / "service.db", self.url, interval=0, max_failures=3)
        self.api = Server(0, ServiceHandler, self.service)
        self.api_thread = threading.Thread(target=self.api.serve_forever, kwargs={"poll_interval":0.01}, daemon=True)
        self.api_thread.start()
        self.api_url = f"http://127.0.0.1:{self.api.server_port}"

    def tearDown(self):
        for server, thread in ((self.api,self.api_thread),(self.server,self.thread)):
            server.shutdown(); server.server_close(); thread.join()
        self.temp.cleanup()

    def create(self, scenario):
        run_id = str(uuid.uuid4())
        status, _ = request(self.api_url + "/api/runs", {"id":run_id,"scenario":scenario})
        self.assertEqual(202, status)
        return run_id

    def snapshot(self, run_id):
        status, result = request(self.api_url + "/api/runs/" + run_id)
        self.assertEqual(200, status)
        return result

    def kinds(self, snapshot):
        return [e["kind"] for e in snapshot["events"]]

    def completed(self, run_id):
        result = self.snapshot(run_id)
        self.assertEqual("COMPLETED", result["state"])
        self.assertEqual(1, result["device"]["pulses"])
        self.assertEqual(1, self.kinds(result).count("PHYSICAL_ACTION_PERFORMED"))
        return result

    def test_receipt_is_not_completion(self):
        run_id = self.create("healthy")
        self.service.tick()
        result = self.snapshot(run_id)
        self.assertEqual("ACCEPTED", result["state"])
        self.assertEqual(0, result["device"]["pulses"])
        self.service.tick()
        self.assertEqual("ACCEPTED", self.snapshot(run_id)["state"])
        self.device.tick(); self.service.tick()
        self.completed(run_id)

    def test_duplicate_delivery_suppressed_before_and_after_completion(self):
        run_id = self.create("duplicate")
        self.service.tick(); self.device.tick(); self.service.tick()
        result = self.completed(run_id)
        self.assertEqual(2, result["sends"])
        self.assertIn("DUPLICATE_SUPPRESSED", self.kinds(result))
        status, _ = request(self.url + "/commands", {"id":run_id,"locker":run_id,"action":"release","scenario":"duplicate"})
        self.assertEqual(202, status)
        self.device.tick()
        self.completed(run_id)

    def test_lost_completion_is_reconciled_without_resend(self):
        run_id = self.create("lost_ack")
        self.service.tick(); self.device.tick(); self.service.tick()
        result = self.snapshot(run_id)
        self.assertEqual("UNCERTAIN", result["state"])
        self.assertEqual(1, result["device"]["pulses"])
        self.service.tick()
        result = self.completed(run_id)
        self.assertEqual(1, result["sends"])
        for kind in ("ACK_DROPPED","OUTCOME_UNCERTAIN","RECONCILIATION_QUERY","RECONCILED"):
            self.assertIn(kind, self.kinds(result))

    def test_disconnect_exhausts_budget_and_reconnect_recovers_same_id(self):
        run_id = self.create("disconnected")
        for _ in range(6): self.service.tick(); self.device.tick()
        result = self.snapshot(run_id)
        self.assertEqual("NEEDS_ATTENTION", result["state"])
        self.assertEqual(0, result["device"]["pulses"])
        self.assertEqual(3, result["failures"])
        status, _ = request(self.api_url + f"/api/runs/{run_id}/reconnect", {})
        self.assertEqual(200, status)
        self.service.tick(); self.device.tick(); self.service.tick()
        result = self.completed(run_id)
        self.assertEqual(run_id, result["id"])
        self.assertEqual(2, result["sends"])
        self.assertIn("JOURNAL_ABSENT", self.kinds(result))

    def test_service_restart_after_dispatch_queries_before_resend(self):
        run_id = self.create("healthy")
        self.service.tick(); self.device.tick()
        # Simulate a crash before the service persisted the receipt response.
        with database(self.service.path) as con:
            con.execute("UPDATE runs SET state='UNCERTAIN' WHERE id=?", (run_id,))
        restarted = Service(self.service.path, self.url, interval=0)
        restarted.tick()
        result = self.completed(run_id)
        self.assertEqual(1, result["sends"])
        self.assertIn("RECONCILED", self.kinds(result))

    def test_controller_restart_preserves_receipt_and_completed_deduplication(self):
        run_id = self.create("healthy")
        self.service.tick()
        self.server.app = Device(self.device.path, action_delay=0)
        self.server.app.tick(); self.service.tick()
        self.completed(run_id)
        self.server.app = Device(self.device.path, action_delay=0)
        status, _ = request(self.url + "/commands", {"id":run_id,"locker":run_id,"action":"release","scenario":"healthy"})
        self.assertEqual(202, status)
        self.server.app.tick()
        self.completed(run_id)

    def test_concurrent_client_requests_create_one_operation(self):
        run_id = str(uuid.uuid4())
        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(lambda _: request(self.api_url + "/api/runs", {"id":run_id,"scenario":"healthy"}), range(6)))
        self.assertTrue(all(status == 202 for status, _ in responses))
        self.service.tick(); self.device.tick(); self.service.tick()
        result = self.completed(run_id)
        self.assertEqual(1, self.kinds(result).count("REQUEST_PERSISTED"))

    def test_conflicting_request_and_device_scenario_rejected(self):
        run_id = self.create("healthy")
        status, _ = request(self.api_url + "/api/runs", {"id":run_id,"scenario":"duplicate"})
        self.assertEqual(409, status)
        self.service.tick()
        for change in ({"action":"close"},{"locker":str(uuid.uuid4())}):
            body = {"id":run_id,"locker":run_id,"action":"release","scenario":"healthy", **change}
            self.assertEqual(409, request(self.url + "/commands", body)[0])
        status, _ = request(self.url + "/commands", {"id":run_id,"locker":run_id,"action":"release","scenario":"duplicate"})
        self.assertEqual(409, status)
        self.device.tick(); self.service.tick(); self.completed(run_id)

    def test_completed_runs_are_not_reexecuted_by_resume(self):
        run_id = self.create("healthy")
        self.service.tick(); self.device.tick(); self.service.tick()
        request(self.api_url + f"/api/runs/{run_id}/resume", {})
        for _ in range(3): self.service.tick(); self.device.tick()
        self.completed(run_id)

    def test_receipt_without_actuation_eventually_requires_attention(self):
        run_id = self.create("healthy")
        self.service.tick()
        for _ in range(35): self.service.tick()
        result = self.snapshot(run_id)
        self.assertEqual("NEEDS_ATTENTION", result["state"])
        self.assertEqual(0, result["device"]["pulses"])

    def test_http_input_host_origin_and_static_boundaries(self):
        for body in ({"id":"invalid","scenario":"healthy"},{"id":str(uuid.uuid4()),"scenario":"unknown"}):
            self.assertEqual(400, request(self.api_url + "/api/runs", body)[0])
        conn = http.client.HTTPConnection("127.0.0.1", self.api.server_port)
        conn.request("POST", "/api/runs", b"{", {"Content-Type":"application/json"})
        self.assertEqual(400, conn.getresponse().status); conn.close()
        for headers in ({"Host":"attacker.example"},{"Origin":"https://attacker.example"}):
            conn = http.client.HTTPConnection("127.0.0.1", self.api.server_port)
            conn.request("GET", "/health", headers=headers)
            self.assertEqual(403, conn.getresponse().status); conn.close()
        self.assertEqual(404, request(self.api_url + "/../.git/config")[0])

    def test_unexpected_worker_failure_stops_http_server(self):
        class BrokenWorker:
            def tick(self):
                raise RuntimeError("Synthetic storage failure")
        server = Server(0, DeviceHandler, BrokenWorker())
        with self.assertRaisesRegex(RuntimeError, "worker failed"):
            run_server(server, 0.01)
        self.assertEqual(-1, server.socket.fileno())


if __name__ == "__main__":
    unittest.main()
