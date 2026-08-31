import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.run_evidence import atomic_write, run, sha256_size


class EvidenceRunnerTest(unittest.TestCase):
    def test_hash_and_atomic_manifest_are_sanitized_by_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "catalog.jsonl"
            source.write_bytes(b"abc")
            digest, size = sha256_size(source)
            self.assertEqual(size, 3)
            target = root / "evidence_manifest.json"
            atomic_write(target, {"schema": "evidence-manifest-v1", "catalog": {"sha256": digest}})
            self.assertEqual(json.loads(target.read_text())["schema"], "evidence-manifest-v1")

    def test_failed_subprocess_returns_nonzero_without_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("tools.run_evidence.subprocess.run") as mocked:
                mocked.return_value.returncode = 2
                self.assertNotEqual(run(root, root / "catalog", root / "dataset", root / "results", root / "manifest"), 0)
                self.assertFalse((root / "manifest").exists())

    def test_success_manifest_excludes_per_session_results_and_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.jsonl"
            catalog.write_bytes(b"catalog")
            results = root / "results.json"
            results.write_text(json.dumps({"hit_rate_at_10": 1.0, "sessions": [{"target": "private"}]}), encoding="utf-8")
            manifest = root / "evidence_manifest.json"
            with patch("tools.run_evidence.subprocess.run") as process, patch(
                "tools.run_evidence.git_value", side_effect=lambda _root, *args: "abc123" if args[-1] == "HEAD" else ""
            ):
                process.return_value.returncode = 0
                self.assertEqual(run(root, catalog, root / "public.jsonl", results, manifest), 0)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["metrics"], {"hit_rate_at_10": 1.0})
            self.assertEqual(payload["commit"], "abc123")
            self.assertNotIn(str(root), json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
