"""Deliberately incorrect worker used only to prove the workload oracle rejects it."""
import argparse
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from lab.service import Service, serve


def assume_completion(self, row):
    if row["state"] == "QUEUED":
        self.dispatch(row)
    else:
        time.sleep(.5)
        self.record_owned(row,"COMPLETION_CONFIRMED","Incorrect assumption without a controller query",state="COMPLETED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port",type=int)
    parser.add_argument("--device-port",type=int)
    parser.add_argument("--data")
    parser.add_argument("--workers",type=int)
    args = parser.parse_args()
    Service.step = assume_completion
    serve(args.port,args.data,f"http://127.0.0.1:{args.device_port}",args.workers)
