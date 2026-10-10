"""Check the complete retained sources without importing their runtime."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT / "source-copy-manifest.json").read_text())
    changed = []
    counts = {}
    for name in manifest["source_roots"]:
        directory = ROOT / name
        live = {p.relative_to(directory).as_posix(): p for p in directory.rglob("*") if p.is_file()}
        counts[name] = len(live)
        for relative in sorted(set(live) | set(manifest["source_files"])):
            path = live.get(relative)
            expected = manifest["source_files"].get(relative)
            if path is None or expected is None:
                changed.append(f"{name}/{relative}")
                continue
            raw = path.read_bytes()
            blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            if ({"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()} != expected
                    or blob != manifest["git_files"][relative]["git_blob_sha1"]):
                changed.append(f"{name}/{relative}")
    for relative, expected in manifest["protected_rehearsal_files"].items():
        path = ROOT / "rehearsal" / relative
        if not path.is_file() or {"bytes": path.stat().st_size,
                                 "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} != expected:
            changed.append("rehearsal/" + relative)
    license_hash = manifest["source_files"]["LICENSE"]["sha256"]
    if hashlib.sha256((ROOT / "LICENSE").read_bytes()).hexdigest() != license_hash:
        changed.append("LICENSE")
    print(json.dumps({"status": "source_verified" if not changed else "source_changed",
                      "source_files": counts, "rehearsal_files": len(manifest["protected_rehearsal_files"]),
                      "changed": changed}, indent=2))
    return bool(changed)


if __name__ == "__main__":
    sys.exit(main())
