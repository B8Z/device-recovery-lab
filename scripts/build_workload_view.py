"""Derive the browser's compact data from the retained experiment, without rerunning it."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / "measurements/concurrency.json"
    # Git stores text with LF; Windows checkouts may use CRLF.
    raw = source.read_bytes().replace(b"\r\n", b"\n")
    report = json.loads(raw)
    result = {key: report[key] for key in (
        "recorded_at_utc", "tested_commit", "environment", "configuration", "summary"
    )}
    result["raw_sha256"] = hashlib.sha256(raw).hexdigest()
    result["raw_hash_encoding"] = "UTF-8 with LF line endings, matching the Git source blob"
    result["raw_source"] = "https://github.com/B8Z/device-recovery-lab/blob/main/measurements/concurrency.json"
    result["trials"] = []
    for trial in report["trials"]:
        if trial["warmup"]:
            continue
        item = {key: trial[key] for key in (
            "workers", "seed", "workload", "repetition", "warmup",
            "batch_seconds", "unaffected_median_seconds"
        )}
        item["operations"] = [
            {key: operation[key] for key in (
                "id", "profile", "classification", "completion_seconds"
            )} for operation in trial["operations"]
        ]
        result["trials"].append(item)
    (ROOT / "demo/workload.json").write_text(
        json.dumps(result, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    print(f"Derived {len(result['trials'])} measured batches; raw SHA-256 {result['raw_sha256']}")


if __name__ == "__main__":
    main()
