"""An external loopback HTTP fault injector; neither application selects its faults."""
import argparse
import http.client
import json
from pathlib import Path
import socket
import threading
import time

from .common import Handler, Problem, Server, identifier, request

PROFILES = ("clean", "slow", "drop_request", "drop_receipt", "duplicate", "drop_completion")


class FaultProxy:
    def __init__(self, upstream, assignments, delay=.3):
        if not 0 <= delay <= .75 or any(p not in PROFILES for p in assignments.values()):
            raise ValueError("Invalid fault profile or delay")
        self.upstream, self.assignments, self.delay = upstream, assignments, delay
        self.lock = threading.Lock()
        self.counts, self.dropped_completion, self.observations = {}, set(), []

    def observe(self, run_id, kind):
        with self.lock:
            self.observations.append({"id": run_id, "at": time.time(), "kind": kind})

    def forward(self, run_id, body):
        method = "GET" if body is None else "POST"
        with self.lock:
            key = (run_id, method)
            ordinal = self.counts.get(key, 0) + 1
            self.counts[key] = ordinal
        profile = self.assignments.get(run_id, "clean")
        first_post = method == "POST" and ordinal == 1
        if first_post and profile == "slow":
            self.observe(run_id, "DELAY_REQUEST")
            time.sleep(self.delay)
        if first_post and profile == "drop_request":
            self.observe(run_id, "DROP_BEFORE_FORWARD")
            return None
        suffix = "/commands" if body is not None else "/commands/" + run_id
        self.observe(run_id, "FORWARD_" + method)
        result = request(self.upstream + suffix, body)
        if first_post and profile == "duplicate":
            self.observe(run_id, "DUPLICATE_FORWARD")
            request(self.upstream + suffix, body)
        if first_post and profile == "drop_receipt":
            self.observe(run_id, "DROP_AFTER_FORWARD")
            return None
        if method == "GET" and profile == "drop_completion" and result[0] == 200 and result[1].get("state") == "COMPLETED":
            with self.lock:
                drop = run_id not in self.dropped_completion
                self.dropped_completion.add(run_id)
            if drop:
                self.observe(run_id, "DROP_COMPLETION_RESPONSE")
                return None
        return result


class ProxyHandler(Handler):
    def route(self):
        app = self.server.app
        if self.command == "GET" and self.path == "/health":
            self.respond(200, {"ok": True, "role": "proxy"})
            return
        if self.command == "GET" and self.path == "/observations":
            with app.lock:
                value = list(app.observations)
            self.respond(200, value)
            return
        if self.command == "POST" and self.path == "/commands":
            body = self.body()
            run_id = identifier(body.get("id"))
        elif self.command == "GET" and self.path.startswith("/commands/"):
            body = None
            run_id = identifier(self.path.removeprefix("/commands/"))
        else:
            # In particular, do not proxy diagnostics to the recovery controller.
            raise Problem(404, "Only command traffic crosses the fault proxy")
        try:
            result = app.forward(run_id, body)
        except (OSError, http.client.HTTPException):
            result = None
        if result is None:
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()
        else:
            self.respond(*result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--device-port", required=True, type=int)
    parser.add_argument("--schedule", required=True)
    parser.add_argument("--delay", type=float, default=.3)
    args = parser.parse_args()
    assignments = json.loads(Path(args.schedule).read_text(encoding="utf-8"))
    app = FaultProxy(f"http://127.0.0.1:{args.device_port}", assignments, args.delay)
    server = Server(args.port, ProxyHandler, app)
    try:
        server.serve_forever(poll_interval=.1)
    finally:
        server.server_close()
