"""Start two isolated loopback processes; stop both with Ctrl+C."""
import argparse
from pathlib import Path
import socket
import subprocess
import sys
import time

from lab.common import request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--device-port", type=int, default=8766)
    parser.add_argument("--data-dir", default=".lab")
    args = parser.parse_args()
    if args.port == args.device_port or not all(1024 <= p <= 65535 for p in (args.port, args.device_port)):
        parser.error("Choose two distinct ports between 1024 and 65535")
    for port in (args.port, args.device_port):
        with socket.socket() as check:
            try:
                check.bind(("127.0.0.1", port))
            except OSError:
                parser.error(f"Port {port} is busy. Choose --port and --device-port.")
    root = Path(__file__).resolve().parent
    data = Path(args.data_dir).resolve()
    data.mkdir(parents=True, exist_ok=True)
    children = []
    try:
        for role, port in (("device", args.device_port), ("service", args.port)):
            command = [sys.executable, "-m", f"lab.{role}", "--port", str(port), "--data", str(data / f"{role}.sqlite3")]
            if role == "service":
                command += ["--device-port", str(args.device_port)]
            child = subprocess.Popen(command, cwd=root)
            children.append(child)
            deadline = time.monotonic() + 10
            while True:
                if child.poll() is not None:
                    raise RuntimeError(f"{role} exited during startup")
                try:
                    status, result = request(f"http://127.0.0.1:{port}/health", timeout=0.25)
                    if status == 200 and result.get("role") == role:
                        break
                except (OSError, ValueError):
                    pass
                if time.monotonic() > deadline:
                    raise RuntimeError(f"{role} did not become healthy")
                time.sleep(0.05)
        print(f"Recovery Lab: http://127.0.0.1:{args.port} (Ctrl+C to stop)", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.25)
        raise RuntimeError("A lab process exited; stopping its peer")
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    main()
