"""Simulated controller with its own durable command and actuation journal."""
import argparse
import socket
import time

from .common import Handler, Problem, SCENARIOS, Server, database, event, events, identifier, initialize, run_server


class Device:
    def __init__(self, path, action_delay=0.35):
        self.path, self.action_delay = path, action_delay
        initialize(path, """
            CREATE TABLE IF NOT EXISTS links (
                id TEXT PRIMARY KEY, scenario TEXT NOT NULL, online INTEGER NOT NULL,
                ack_dropped INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS commands (
                id TEXT PRIMARY KEY, locker TEXT NOT NULL, action TEXT NOT NULL,
                state TEXT NOT NULL, due REAL NOT NULL, pulses INTEGER NOT NULL DEFAULT 0);
        """)

    def accept(self, body):
        run_id = identifier(body.get("id"))
        scenario = body.get("scenario")
        with database(self.path) as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT * FROM commands WHERE id=?", (run_id,)).fetchone()
            if row and (row["locker"], row["action"]) != (body.get("locker"), body.get("action")):
                raise Problem(409, "Command ID already has another payload")
            if scenario not in SCENARIOS or body.get("action") != "release" or body.get("locker") != run_id:
                raise Problem(400, "Expected a release command for this experiment's locker")
            link = con.execute("SELECT * FROM links WHERE id=?", (run_id,)).fetchone()
            if not link:
                online = scenario != "disconnected"
                con.execute("INSERT INTO links(id,scenario,online) VALUES(?,?,?)", (run_id, scenario, online))
                event(con, run_id, "LINK_ONLINE" if online else "LINK_OFFLINE", "Synthetic device link initialized")
            elif link["scenario"] != scenario:
                raise Problem(409, "Scenario cannot change for an existing command")
            link = con.execute("SELECT * FROM links WHERE id=?", (run_id,)).fetchone()
            if not link["online"]:
                event(con, run_id, "DELIVERY_BLOCKED", "Disconnected: command did not reach controller")
                return None
            if row:
                event(con, run_id, "DUPLICATE_SUPPRESSED", "Existing journal entry returned; no new pulse scheduled")
                return dict(row)
            con.execute("INSERT INTO commands(id,locker,action,state,due) VALUES(?,?,?,'RECEIVED',?)",
                        (run_id, run_id, "release", time.time() + self.action_delay))
            event(con, run_id, "COMMAND_RECEIVED", "Receipt only: actuator has not completed")
            return {"id": run_id, "state": "RECEIVED", "pulses": 0}

    def lookup(self, run_id):
        with database(self.path) as con:
            con.execute("BEGIN IMMEDIATE")
            link = con.execute("SELECT * FROM links WHERE id=?", (run_id,)).fetchone()
            if link and not link["online"]:
                return None
            row = con.execute("SELECT * FROM commands WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise Problem(404, "No command in this controller's journal")
            if row["state"] == "COMPLETED" and link["scenario"] == "lost_ack" and not link["ack_dropped"]:
                con.execute("UPDATE links SET ack_dropped=1 WHERE id=?", (run_id,))
                event(con, run_id, "ACK_DROPPED", "Completion response lost after durable simulated actuation")
                return None
            if row["state"] == "COMPLETED":
                event(con, run_id, "COMPLETION_REPORTED", "Completed command journal entry returned")
            return dict(row)

    def reconnect(self, run_id):
        with database(self.path) as con:
            if not con.execute("SELECT 1 FROM links WHERE id=?", (run_id,)).fetchone():
                raise Problem(409, "Wait for the first command attempt before reconnecting")
            con.execute("UPDATE links SET online=1 WHERE id=?", (run_id,))
            event(con, run_id, "LINK_RECONNECTED", "Visitor restored the simulated network link")

    def tick(self):
        with database(self.path) as con:
            con.execute("BEGIN IMMEDIATE")
            rows = con.execute("""SELECT commands.id FROM commands JOIN links USING(id)
                WHERE state='RECEIVED' AND due<=? AND online=1""", (time.time(),)).fetchall()
            for row in rows:
                con.execute("UPDATE commands SET state='COMPLETED', pulses=pulses+1 WHERE id=?", (row["id"],))
                event(con, row["id"], "PHYSICAL_ACTION_PERFORMED", "Release pulse applied; simulated locker is OPEN")

    def snapshot(self, run_id):
        with database(self.path) as con:
            link = con.execute("SELECT * FROM links WHERE id=?", (run_id,)).fetchone()
            row = con.execute("SELECT * FROM commands WHERE id=?", (run_id,)).fetchone()
            return {"online": bool(link["online"]) if link else None,
                    "state": row["state"] if row else "NOT_RECEIVED",
                    "pulses": row["pulses"] if row else 0,
                    "events": events(con, run_id, "device")}


class DeviceHandler(Handler):
    def route(self):
        app = self.server.app
        if self.command == "GET" and self.path == "/health":
            self.respond(200, {"ok": True, "role": "device"})
            return
        if self.command == "POST" and self.path == "/commands":
            value = app.accept(self.body())
        elif self.command == "GET" and self.path.startswith("/commands/"):
            value = app.lookup(identifier(self.path.removeprefix("/commands/")))
        elif self.command == "GET" and self.path.startswith("/lab/snapshot/"):
            self.respond(200, app.snapshot(identifier(self.path.removeprefix("/lab/snapshot/"))))
            return
        elif self.command == "POST" and self.path.startswith("/lab/reconnect/"):
            self.body()
            app.reconnect(identifier(self.path.removeprefix("/lab/reconnect/")))
            self.respond(200, {"online": True})
            return
        else:
            raise Problem(404, "Unknown endpoint")
        if value is None:
            # Close the actual transport without an HTTP response.
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()
        else:
            self.respond(202 if self.command == "POST" else 200, value)


def serve(port, path, action_delay=0.35):
    app = Device(path, action_delay)
    server = Server(port, DeviceHandler, app)
    run_server(server, 0.025)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--data", default=".lab/device.sqlite3")
    args = parser.parse_args()
    serve(args.port, args.data)
