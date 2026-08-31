"""Run the official evaluator and write a sanitized reproducibility manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


def sha256_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def git_value(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-c", f"safe.directory={root.as_posix()}", *args], cwd=root,
                            text=True, capture_output=True, check=True)
    return result.stdout.strip()


def atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run(root: Path, catalog: Path, dataset: Path, results: Path, manifest: Path) -> int:
    command = [sys.executable, "-m", "evaluator.local_evaluator", "--catalog", str(catalog),
               "--dataset", str(dataset), "--output", str(results)]
    started = time.monotonic()
    completed = subprocess.run(command, cwd=root, text=True, capture_output=True)
    duration = time.monotonic() - started
    if completed.returncode != 0:
        print("evaluator failed", file=sys.stderr)
        return completed.returncode or 1
    try:
        aggregate = json.loads(results.read_text(encoding="utf-8"))
        digest, size = sha256_size(catalog)
        manifest_data = {
            "schema": "evidence-manifest-v1",
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(duration, 6),
            "python": platform.python_version(),
            "platform": platform.platform(aliased=True),
            "commit": git_value(root, "rev-parse", "HEAD"),
            "tracked_worktree_dirty": bool(git_value(root, "status", "--porcelain", "--untracked-files=no")),
            "catalog": {"sha256": digest, "size_bytes": size},
            "commands": [f"{Path(sys.executable).name} -m evaluator.local_evaluator --catalog data/catalog.jsonl --dataset data/public_set.jsonl --output results.json"],
            "metrics": {key: value for key, value in aggregate.items() if key != "sessions"},
        }
        atomic_write(manifest, manifest_data)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"evidence capture failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps(manifest_data["metrics"], sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--catalog", type=Path, default=Path("data/catalog.jsonl"))
    parser.add_argument("--dataset", type=Path, default=Path("data/public_set.jsonl"))
    parser.add_argument("--results", type=Path, default=Path("results.json"))
    parser.add_argument("--manifest", type=Path, default=Path("evidence_manifest.json"))
    args = parser.parse_args()
    root = args.root.resolve()
    return run(root, (root / args.catalog).resolve(), (root / args.dataset).resolve(),
               (root / args.results).resolve(), (root / args.manifest).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
