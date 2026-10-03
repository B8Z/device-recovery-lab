"""Small shared HTTP/SQLite plumbing; no shared service/device state."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid

SCENARIOS = ("healthy", "duplicate", "lost_ack", "disconnected")


class Problem(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


@contextmanager
def database(path):
    con = sqlite3.connect(path, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()


def initialize(path, schema):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with database(path) as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(schema)
        con.execute("""CREATE TABLE IF NOT EXISTS events (
            seq INTEGER PRIMARY KEY, run_id TEXT NOT NULL, at REAL NOT NULL,
            kind TEXT NOT NULL, detail TEXT NOT NULL)""")


def event(con, run_id, kind, detail):
    con.execute("INSERT INTO events(run_id,at,kind,detail) VALUES(?,?,?,?)",
                (run_id, time.time(), kind, detail))


def events(con, run_id, source):
    return [dict(row, source=source) for row in con.execute(
        "SELECT * FROM events WHERE run_id=? ORDER BY seq", (run_id,))]


def identifier(value):
    try:
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError):
        raise Problem(400, "id must be a canonical UUID") from None
    return value


# Ignore proxy environment variables: lab traffic never leaves loopback.
_http = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(url, body=None, timeout=1):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with _http.open(req, timeout=timeout) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, json.load(exc)


class Handler(BaseHTTPRequestHandler):
    server_version = "RecoveryLab/1"

    def log_message(self, *_):
        pass

    def respond(self, status, value, content_type="application/json"):
        body = json.dumps(value).encode() if content_type == "application/json" else value
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except ConnectionError:
            pass

    def body(self):
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            raise Problem(415, "Use application/json")
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 4096:
                raise ValueError
            result = json.loads(self.rfile.read(size))
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (ValueError, UnicodeError):
            raise Problem(400, "Expected a JSON object of at most 4096 bytes") from None

    def handle_request(self):
        try:
            port = self.server.server_port
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if self.headers.get("Host") not in hosts:
                raise Problem(403, "Loopback host required")
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + h for h in hosts}:
                raise Problem(403, "Same origin required")
            self.route()
        except Problem as exc:
            self.respond(exc.status, {"error": exc.message})

    do_GET = handle_request
    do_POST = handle_request


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, handler, app):
        super().__init__(("127.0.0.1", port), handler)
        self.app = app


def run_server(server, interval):
    """Fail the process if its worker fails, rather than serve a dead controller."""
    stop = threading.Event()
    failures = []

    def worker():
        try:
            while not stop.wait(interval):
                server.app.tick()
        except Exception as exc:
            failures.append(exc)
            server.shutdown()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        stop.set()
        thread.join(timeout=3)
        server.server_close()
    if failures:
        raise RuntimeError("Recovery worker failed; HTTP server stopped") from failures[0]
