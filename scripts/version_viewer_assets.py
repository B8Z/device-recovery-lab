"""Version browser assets by their Git-normalized content to avoid stale deployments."""
import hashlib
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1] / "demo"
page = ROOT / "index.html"
original = page.read_text(encoding="utf-8")
updated = original
for asset in ("style.css", "instrument.css", "viewer.js", "workload.js"):
    source = (ROOT / asset).read_bytes().replace(b"\r\n", b"\n")
    version = hashlib.sha256(source).hexdigest()[:12]
    pattern = rf'((?:href|src)="){re.escape(asset)}(?:\?v=[a-f0-9]+)?(")'
    updated, count = re.subn(pattern, rf'\g<1>{asset}?v={version}\2', updated)
    if count != 1:
        raise SystemExit(f"Expected one reference to {asset}, found {count}")

if "--check" in sys.argv:
    if original != updated:
        raise SystemExit("Run python scripts/version_viewer_assets.py before publishing")
    print("Viewer asset versions match source content")
else:
    page.write_text(updated, encoding="utf-8")
    print("Versioned viewer CSS and JavaScript by source content")
