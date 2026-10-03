"""Durable operation queue and recovery controller, communicating only over HTTP."""
import argparse
import http.client
from pathlib import Path
import time
import urllib.error

from .common import Handler, Problem, SCENARIOS, Server, database, event, events, identifier, initialize, request, run_server

TRANSPORT_ERRORS = (OSError, urllib.error.URLError, http.client.HTTPException)
STATIC = Path(__file__).resolve().parent.parent / "web"


class Service:
    def __init__(self, path, device_url, interval=0.6, max_failures=6, max_backoff=2.4):
        self.path, self.device_url = path, device_url
        self.interval, self.max_failures, self.max_backoff = interval, max_failures, max_backoff
        initialize(path, """CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, scenario TEXT NOT NULL, state TEXT NOT NULL,
            created REAL NOT NULL, next_at REAL NOT NULL, sends INTEGER NOT NULL DEFAULT 0,
            failures INTEGER NOT NULL DEFAULT 0, checks INTEGER NOT NULL DEFAULT 0,
            duplicate_sent INTEGER NOT NULL DEFAULT 0, reconciled INTEGER NOT NULL DEFAULT 0)""")

    def create(self, body):
        run_id = identifier(body.get("id"))
        scenario = body.get("scenario")
        if scenario not in SCENARIOS:
            raise Problem(400, "Unknown scenario")
        with database(self.path) as con:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if existing:
                if existing["scenario"] != scenario:
                    raise Problem(409, "Request ID already belongs to a different scenario")
                return dict(existing)
            now = time.time()
            con.execute("INSERT INTO runs(id,scenario,state,created,next_at) VALUES(?,?,'QUEUED',?,?)",
                        (run_id, scenario, now, now))
            event(con, run_id, "REQUEST_PERSISTED", "Release requested; no device completion evidence yet")
            return dict(con.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())

    def record(self, run_id, kind, detail, **changes):
        with database(self.path) as con:
            # Column names are exclusively internal keyword arguments.
            if changes:
                con.execute("UPDATE runs SET " + ",".join(f"{k}=?" for k in changes) + " WHERE id=?",
                            (*changes.values(), run_id))
            event(con, run_id, kind, detail)

    def uncertain(self, row, detail):
        failures = row["failures"] + 1
        exhausted = failures >= self.max_failures
        delay = min(self.max_backoff, self.interval * 2 ** (failures - 1))
        self.record(row["id"], "RETRY_BUDGET_EXHAUSTED" if exhausted else "OUTCOME_UNCERTAIN",
                    detail + ("; resume reconciliation after investigation" if exhausted else "; query journal before any resend"),
                    state="NEEDS_ATTENTION" if exhausted else "UNCERTAIN", failures=failures,
                    next_at=time.time() + delay, reconciled=1)

    def dispatch(self, row):
        run_id = row["id"]
        # Persist intent before I/O. A crash now resumes with a journal query.
        self.record(run_id, "COMMAND_SENT", "Deliver immutable release command " + run_id,
                    state="UNCERTAIN", sends=row["sends"] + 1, next_at=time.time() + self.interval)
        body = {"id": run_id, "locker": run_id, "action": "release", "scenario": row["scenario"]}
        status, value = request(self.device_url + "/commands", body)
        if status != 202:
            raise Problem(status, value.get("error", "Device rejected command"))
        self.record(run_id, "RECEIPT_ACKNOWLEDGED", "Device received the command; completion still requires journal evidence",
                    state="ACCEPTED", failures=0)
        if row["scenario"] == "duplicate" and not row["duplicate_sent"]:
            self.record(run_id, "DUPLICATE_INJECTED", "Test transport delivers the same command ID again",
                        duplicate_sent=1, sends=row["sends"] + 2)
            status, value = request(self.device_url + "/commands", body)
            if status != 202:
                raise Problem(status, value.get("error", "Duplicate delivery rejected"))

    def step(self, row):
        run_id = row["id"]
        try:
            if row["state"] == "QUEUED":
                self.dispatch(row)
                return
            self.record(run_id, "RECONCILIATION_QUERY" if row["state"] == "UNCERTAIN" else "COMPLETION_QUERY",
                        "Read controller journal by command ID", checks=row["checks"] + 1)
            status, value = request(self.device_url + "/commands/" + run_id)
            if status == 404:
                self.record(run_id, "JOURNAL_ABSENT", "Controller confirms no record; retry the same immutable command")
                self.dispatch(row)
            elif status != 200:
                raise Problem(status, value.get("error", "Journal lookup rejected"))
            elif value.get("id") != run_id or value.get("state") not in ("RECEIVED", "COMPLETED"):
                raise Problem(502, "Invalid controller evidence")
            elif value["state"] == "COMPLETED":
                reconciled = row["reconciled"] or row["state"] == "UNCERTAIN"
                self.record(run_id, "RECONCILED" if reconciled else "COMPLETION_CONFIRMED",
                            "Completed journal entry confirms the simulated release pulse",
                            state="COMPLETED", failures=0, reconciled=int(reconciled))
            else:
                # Bound total unanswered completion polls as well as transport failures.
                if row["checks"] + 1 >= 30:
                    self.record(run_id, "COMPLETION_DEADLINE", "Receipt persisted but completion not observed; investigate controller",
                                state="NEEDS_ATTENTION")
                else:
                    self.record(run_id, "AWAITING_COMPLETION", "Receipt exists; actuator completion not yet recorded",
                                state="ACCEPTED", failures=0, next_at=time.time() + self.interval)
        except TRANSPORT_ERRORS:
            self.uncertain(row, "Device response unavailable; action outcome is unknown")
        except Problem as exc:
            self.record(run_id, "PROTOCOL_REJECTED", exc.message, state="NEEDS_ATTENTION")

    def tick(self):
        with database(self.path) as con:
            rows = con.execute("""SELECT * FROM runs WHERE state IN ('QUEUED','ACCEPTED','UNCERTAIN')
                AND next_at<=? ORDER BY created LIMIT 20""", (time.time(),)).fetchall()
        for row in rows:
            self.step(dict(row))

    def snapshot(self, run_id):
        with database(self.path) as con:
            row = con.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise Problem(404, "Unknown experiment")
            result = dict(row)
            result["events"] = events(con, run_id, "service")
        # Test instrumentation only. The recovery controller never reads this endpoint.
        try:
            status, device = request(self.device_url + "/lab/snapshot/" + run_id)
            if status != 200:
                raise OSError
            result["device"] = {k: v for k, v in device.items() if k != "events"}
            result["events"].extend(device["events"])
        except TRANSPORT_ERRORS:
            result["device"] = None
        result["events"].sort(key=lambda e: (e["at"], e["source"], e["seq"]))
        return result

    def resume(self, run_id):
        with database(self.path) as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT state FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise Problem(404, "Unknown experiment")
            if row["state"] == "NEEDS_ATTENTION":
                con.execute("UPDATE runs SET state='UNCERTAIN',failures=0,checks=0,next_at=? WHERE id=?", (time.time(), run_id))
                event(con, run_id, "RECONCILIATION_RESUMED", "Visitor resumed journal queries; command identity preserved")


class ServiceHandler(Handler):
    def route(self):
        app = self.server.app
        if self.command == "GET" and self.path in ("/", "/app.js", "/style.css"):
            file, mime = {"/": ("index.html", "text/html; charset=utf-8"),
                          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                          "/style.css": ("style.css", "text/css; charset=utf-8")}[self.path]
            self.respond(200, (STATIC / file).read_bytes(), mime)
        elif self.command == "GET" and self.path == "/health":
            self.respond(200, {"ok": True, "role": "service"})
        elif self.command == "POST" and self.path == "/api/runs":
            self.respond(202, app.create(self.body()))
        elif self.command == "GET" and self.path == "/api/runs":
            with database(app.path) as con:
                self.respond(200, [dict(r) for r in con.execute("SELECT id,scenario,state FROM runs ORDER BY created DESC LIMIT 30")])
        elif self.path.startswith("/api/runs/"):
            parts = self.path.removeprefix("/api/runs/").split("/")
            run_id = identifier(parts[0])
            if self.command == "GET" and len(parts) == 1:
                self.respond(200, app.snapshot(run_id))
            elif self.command == "POST" and len(parts) == 2 and parts[1] in ("reconnect", "resume"):
                self.body()
                if parts[1] == "reconnect":
                    # Validate the service operation exists before changing the lab link.
                    with database(app.path) as con:
                        if not con.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone():
                            raise Problem(404, "Unknown experiment")
                    try:
                        status, value = request(app.device_url + "/lab/reconnect/" + run_id, {})
                    except TRANSPORT_ERRORS:
                        raise Problem(503, "Simulator unavailable; restart it and retry") from None
                    if status != 200:
                        raise Problem(status, value.get("error", "Reconnect failed"))
                app.resume(run_id)
                self.respond(200, {"ok": True})
            else:
                raise Problem(404, "Unknown endpoint")
        else:
            raise Problem(404, "Unknown endpoint")


def serve(port, path, device_url):
    app = Service(path, device_url)
    server = Server(port, ServiceHandler, app)
    run_server(server, 0.05)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--device-port", type=int, default=8766)
    parser.add_argument("--data", default=".lab/service.sqlite3")
    args = parser.parse_args()
    serve(args.port, args.data, f"http://127.0.0.1:{args.device_port}")
